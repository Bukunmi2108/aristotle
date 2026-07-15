from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any, Literal
from urllib.parse import parse_qsl, urlencode, urlparse

from pydantic import BaseModel, Field


URL_RE = re.compile(r"https?://[^\s)\]}>,]+")
CITATION_RE = re.compile(r"\[(\d{1,3})\]")
RAW_CITATION_SECTION_RE = re.compile(
    r"(?:^|\n)\s*(?:#{1,4}\s*)?(citations|references|sources)\s*:?\s*(?:\n|$)",
    re.IGNORECASE,
)
SEARCH_TOOLS = {"search_web", "search_multi_query"}


class ResearchEvalExpectations(BaseModel):
    search: Literal["required", "forbidden", "optional"] = "optional"
    required_tools: list[str] = Field(default_factory=list)
    forbidden_tools: list[str] = Field(default_factory=list)
    min_queries: int = 0
    min_fetched_urls: int = 0
    min_sources: int = 0
    min_failed_sources: int = 0
    min_citations: int = 0
    required_source_domains: list[str] = Field(default_factory=list)
    forbidden_source_domains: list[str] = Field(default_factory=list)
    required_input_domains: list[str] = Field(default_factory=list)
    require_freshness: bool = False
    allow_unlisted_answer_urls: bool = False
    allow_raw_citation_section: bool = False


class ResearchEvalCase(BaseModel):
    id: str
    category: str
    prompt: str
    expectations: ResearchEvalExpectations
    events: list[dict[str, Any]] = Field(default_factory=list)
    runs: list[list[dict[str, Any]]] = Field(default_factory=list)
    notes: str | None = None


class ResearchRunTrace(BaseModel):
    tools: list[str]
    answer: str
    source_urls: list[str]
    source_domains: list[str]
    answer_urls: list[str]
    citation_numbers: list[int]
    failed_source_count: int
    tool_error_count: int
    query_count: int
    fetched_url_count: int
    freshness_count: int
    input_domains: list[str]
    first_token_latency_ms: int | None = None
    event_duration_ms: int | None = None
    completed: bool = False
    errored: bool = False


class ResearchRunEvalResult(BaseModel):
    run_index: int
    passed: bool
    failures: list[str] = Field(default_factory=list)
    metrics: dict[str, int | float | str | None] = Field(default_factory=dict)


class ResearchEvalResult(BaseModel):
    case_id: str
    passed: bool
    failures: list[str] = Field(default_factory=list)
    metrics: dict[str, int | float | str | None] = Field(default_factory=dict)
    runs: list[ResearchRunEvalResult] = Field(default_factory=list)


def load_eval_case(path: Path) -> ResearchEvalCase:
    return ResearchEvalCase.model_validate_json(path.read_text())


def load_eval_cases(directory: Path) -> list[ResearchEvalCase]:
    return [
        load_eval_case(path)
        for path in sorted(directory.glob("*.json"))
        if not path.name.startswith("_")
    ]


def evaluate_case(case: ResearchEvalCase) -> ResearchEvalResult:
    event_runs = case.runs or ([case.events] if case.events else [])
    run_results = [
        evaluate_run(case.expectations, events, run_index=index + 1)
        for index, events in enumerate(event_runs)
    ]
    failures = [
        f"run {run.run_index}: {failure}"
        for run in run_results
        for failure in run.failures
    ]
    if not run_results:
        failures.append("case has no event runs")
    return ResearchEvalResult(
        case_id=case.id,
        passed=not failures,
        failures=failures,
        metrics=_aggregate_metrics(run_results),
        runs=run_results,
    )


def evaluate_run(
    expectations: ResearchEvalExpectations,
    events: list[dict[str, Any]],
    *,
    run_index: int = 1,
) -> ResearchRunEvalResult:
    trace = trace_from_events(events)
    failures = evaluate_trace(expectations, trace)
    return ResearchRunEvalResult(
        run_index=run_index,
        passed=not failures,
        failures=failures,
        metrics=trace_metrics(trace),
    )


def trace_from_events(events: list[dict[str, Any]]) -> ResearchRunTrace:
    tools: list[str] = []
    source_urls: list[str] = []
    failed_source_count = 0
    tool_error_count = 0
    query_count = 0
    fetched_url_count = 0
    freshness_count = 0
    input_domains: list[str] = []
    first_token_latency_ms: int | None = None
    answer_parts: list[str] = []
    completed_answer = ""
    completed = False
    errored = False
    first_timestamp: datetime | None = None
    last_timestamp: datetime | None = None

    for event in events:
        timestamp = _parse_timestamp(event.get("timestamp"))
        if timestamp is not None:
            first_timestamp = first_timestamp or timestamp
            last_timestamp = timestamp

        event_type = event.get("type")
        tool = event.get("tool")
        if event_type == "tool.started" and isinstance(tool, str):
            tools.append(tool)
            query_count += _query_count(event)
            fetched_url_count += _fetch_count(event)
            freshness_count += _freshness_count(event)
            input_domains.extend(_input_domains(event))
        if event_type == "tool.result" and isinstance(tool, str):
            tools.append(tool)
            for preview in _result_previews(event):
                url = preview.get("url")
                if isinstance(url, str) and _is_http_url(url):
                    source_urls.append(_canonical_url(url))
                if preview.get("status") == "failed":
                    failed_source_count += 1
        if event_type == "tool.error":
            tool_error_count += 1
        if event_type == "model.first_token" and isinstance(event.get("latency_ms"), int):
            first_token_latency_ms = event["latency_ms"]
        if event_type == "message.delta" and isinstance(event.get("text"), str):
            answer_parts.append(event["text"])
        if event_type == "message.completed" and isinstance(event.get("message"), str):
            completed_answer = event["message"]
        if event_type == "session.completed":
            completed = True
        if event_type == "error":
            errored = True

    answer = completed_answer or "".join(answer_parts)
    source_urls = _dedupe(source_urls)
    event_duration_ms = None
    if first_timestamp is not None and last_timestamp is not None:
        event_duration_ms = max(0, int((last_timestamp - first_timestamp).total_seconds() * 1000))

    return ResearchRunTrace(
        tools=tools,
        answer=answer,
        source_urls=source_urls,
        source_domains=_dedupe(
            domain for domain in (_domain(url) for url in source_urls) if domain
        ),
        answer_urls=_dedupe(_canonical_url(url) for url in URL_RE.findall(answer)),
        citation_numbers=[int(value) for value in CITATION_RE.findall(answer)],
        failed_source_count=failed_source_count,
        tool_error_count=tool_error_count,
        query_count=query_count,
        fetched_url_count=fetched_url_count,
        freshness_count=freshness_count,
        input_domains=_dedupe(input_domains),
        first_token_latency_ms=first_token_latency_ms,
        event_duration_ms=event_duration_ms,
        completed=completed,
        errored=errored,
    )


def evaluate_trace(
    expectations: ResearchEvalExpectations,
    trace: ResearchRunTrace,
) -> list[str]:
    failures: list[str] = []
    tool_set = set(trace.tools)

    if expectations.search == "required" and not tool_set.intersection(SEARCH_TOOLS):
        failures.append("expected search tool usage")
    if expectations.search == "forbidden" and tool_set.intersection(SEARCH_TOOLS):
        failures.append("did not expect search tool usage")

    for tool in expectations.required_tools:
        if tool not in tool_set:
            failures.append(f"missing required tool: {tool}")
    for tool in expectations.forbidden_tools:
        if tool in tool_set:
            failures.append(f"used forbidden tool: {tool}")

    if trace.query_count < expectations.min_queries:
        failures.append(
            f"expected at least {expectations.min_queries} queries, got {trace.query_count}"
        )
    if trace.fetched_url_count < expectations.min_fetched_urls:
        failures.append(
            f"expected at least {expectations.min_fetched_urls} fetched URLs, got {trace.fetched_url_count}"
        )
    if len(trace.source_urls) < expectations.min_sources:
        failures.append(
            f"expected at least {expectations.min_sources} sources, got {len(trace.source_urls)}"
        )
    if trace.failed_source_count < expectations.min_failed_sources:
        failures.append(
            f"expected at least {expectations.min_failed_sources} failed sources, got {trace.failed_source_count}"
        )
    if len(set(trace.citation_numbers)) < expectations.min_citations:
        failures.append(
            f"expected at least {expectations.min_citations} citations, got {len(set(trace.citation_numbers))}"
        )

    if trace.citation_numbers and not trace.source_urls:
        failures.append("answer has citation markers but no source URLs")
    unresolved = [
        number
        for number in trace.citation_numbers
        if number < 1 or number > len(trace.source_urls)
    ]
    if unresolved:
        failures.append(f"citation markers without matching source: {unresolved}")

    for domain in expectations.required_source_domains:
        if not any(_domain_matches(source_domain, domain) for source_domain in trace.source_domains):
            failures.append(f"missing required source domain: {domain}")
    for domain in expectations.forbidden_source_domains:
        if any(_domain_matches(source_domain, domain) for source_domain in trace.source_domains):
            failures.append(f"used forbidden source domain: {domain}")
    for domain in expectations.required_input_domains:
        if not any(_domain_matches(input_domain, domain) for input_domain in trace.input_domains):
            failures.append(f"missing required input domain constraint: {domain}")

    if expectations.require_freshness and trace.freshness_count <= 0:
        failures.append("expected freshness input")

    if not expectations.allow_unlisted_answer_urls:
        unlisted = sorted(set(trace.answer_urls) - set(trace.source_urls))
        if unlisted:
            failures.append(f"answer contains unlisted URLs: {', '.join(unlisted)}")

    if not expectations.allow_raw_citation_section and RAW_CITATION_SECTION_RE.search(trace.answer):
        failures.append("answer includes duplicate raw citation/source section")

    return failures


def trace_metrics(trace: ResearchRunTrace) -> dict[str, int | float | str | None]:
    return {
        "tool_count": len(trace.tools),
        "query_count": trace.query_count,
        "fetched_url_count": trace.fetched_url_count,
        "source_count": len(trace.source_urls),
        "failed_source_count": trace.failed_source_count,
        "tool_error_count": trace.tool_error_count,
        "citation_count": len(set(trace.citation_numbers)),
        "freshness_count": trace.freshness_count,
        "first_token_latency_ms": trace.first_token_latency_ms,
        "event_duration_ms": trace.event_duration_ms,
    }


def _aggregate_metrics(
    run_results: list[ResearchRunEvalResult],
) -> dict[str, int | float | str | None]:
    if not run_results:
        return {}
    metrics: dict[str, int | float | str | None] = {
        "run_count": len(run_results),
        "passed_runs": sum(run.passed for run in run_results),
    }
    metric_names = sorted({name for run in run_results for name in run.metrics})
    for name in metric_names:
        values = [run.metrics.get(name) for run in run_results]
        numeric = [value for value in values if isinstance(value, int | float)]
        if numeric:
            metrics[f"avg_{name}"] = round(sum(numeric) / len(numeric), 4)
    return metrics


def _query_count(event: dict[str, Any]) -> int:
    payload = event.get("input")
    if not isinstance(payload, dict):
        return 0
    if event.get("tool") == "search_multi_query" and isinstance(payload.get("queries"), list):
        return len(payload["queries"])
    if event.get("tool") == "search_web" and payload.get("query"):
        return 1
    return 0


def _fetch_count(event: dict[str, Any]) -> int:
    payload = event.get("input")
    if not isinstance(payload, dict):
        return 0
    if event.get("tool") == "fetch_url" and payload.get("url"):
        return 1
    return 0


def _freshness_count(event: dict[str, Any]) -> int:
    payload = event.get("input")
    if not isinstance(payload, dict):
        return 0
    freshness = payload.get("freshness")
    return 1 if isinstance(freshness, str) and freshness else 0


def _input_domains(event: dict[str, Any]) -> list[str]:
    payload = event.get("input")
    if not isinstance(payload, dict) or not isinstance(payload.get("domains"), list):
        return []
    return [
        domain.lower().removeprefix("www.")
        for domain in payload["domains"]
        if isinstance(domain, str) and domain
    ]


def _result_previews(event: dict[str, Any]) -> list[dict[str, Any]]:
    previews = event.get("result_preview")
    if not isinstance(previews, list):
        return []
    return [preview for preview in previews if isinstance(preview, dict)]


def _domain_matches(actual: str, expected: str) -> bool:
    actual = actual.lower().removeprefix("www.")
    expected = expected.lower().removeprefix("www.")
    return actual == expected or actual.endswith(f".{expected}")


def _domain(url: str) -> str | None:
    parsed = urlparse(url)
    if not parsed.hostname:
        return None
    return parsed.hostname.lower().removeprefix("www.")


def _canonical_url(url: str) -> str:
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        return url
    params = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if not key.lower().startswith("utm_")
    ]
    return parsed._replace(
        scheme=parsed.scheme.lower(),
        netloc=parsed.netloc.lower(),
        fragment="",
        path=parsed.path.rstrip("/") or "/",
        query=urlencode(params, doseq=True),
    ).geturl()


def _is_http_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _dedupe(values) -> list:
    return list(dict.fromkeys(values))


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Run offline research protocol evals.")
    parser.add_argument(
        "fixtures",
        nargs="?",
        default="tests/evals/research",
        help="Directory containing research eval JSON fixtures.",
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    cases = load_eval_cases(Path(args.fixtures))
    results = [evaluate_case(case) for case in cases]
    passed = sum(result.passed for result in results)

    if args.json:
        print("[" + ",".join(result.model_dump_json(indent=2) for result in results) + "]")
        return 0 if passed == len(results) else 1

    print(f"{len(results)} research fixtures")
    print(f"{passed} passed")
    print(f"{len(results) - passed} failed")
    for result in results:
        status = "PASS" if result.passed else "FAIL"
        print(f"- {status} {result.case_id}")
        metric_text = ", ".join(
            f"{key}={value}" for key, value in sorted(result.metrics.items())
        )
        if metric_text:
            print(f"  metrics: {metric_text}")
        for failure in result.failures:
            print(f"  - {failure}")

    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
