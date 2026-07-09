from pathlib import Path
import unittest

from app.evals.research import (
    ResearchEvalCase,
    ResearchEvalExpectations,
    evaluate_case,
    load_eval_cases,
    trace_from_events,
)


FIXTURE_DIR = Path(__file__).parent / "evals" / "research"


class ResearchEvalFixturesTest(unittest.TestCase):
    def test_research_eval_fixtures_pass(self):
        cases = load_eval_cases(FIXTURE_DIR)

        self.assertGreaterEqual(len(cases), 4)
        for case in cases:
            with self.subTest(case=case.id):
                result = evaluate_case(case)
                self.assertTrue(result.passed, result.failures)

    def test_required_search_failure_is_reported(self):
        case = ResearchEvalCase(
            id="missing_search",
            category="current_fact",
            prompt="What changed today?",
            expectations=ResearchEvalExpectations(search="required"),
            events=[{"type": "message.completed", "message": "It changed."}],
        )

        result = evaluate_case(case)

        self.assertFalse(result.passed)
        self.assertTrue(
            any("expected search tool usage" in failure for failure in result.failures)
        )

    def test_unlisted_answer_url_failure_is_reported(self):
        case = ResearchEvalCase(
            id="hallucinated_url",
            category="source_integrity",
            prompt="Answer with sources.",
            expectations=ResearchEvalExpectations(min_sources=1),
            events=[
                {
                    "type": "tool.result",
                    "tool": "search_web",
                    "result_preview": [
                        {
                            "title": "Known source",
                            "url": "https://example.com/source",
                        }
                    ],
                },
                {
                    "type": "message.completed",
                    "message": "See https://not-a-source.example/page",
                },
            ],
        )

        result = evaluate_case(case)

        self.assertFalse(result.passed)
        self.assertTrue(
            any("answer contains unlisted URLs" in failure for failure in result.failures)
        )

    def test_required_freshness_failure_is_reported(self):
        case = ResearchEvalCase(
            id="missing_freshness",
            category="current_fact",
            prompt="What is the current launch date?",
            expectations=ResearchEvalExpectations(
                search="required",
                require_freshness=True,
            ),
            events=[
                {
                    "type": "tool.started",
                    "tool": "search_web",
                    "input": {"query": "launch date"},
                },
                {
                    "type": "tool.result",
                    "tool": "search_web",
                    "result_preview": [
                        {
                            "title": "Launch date",
                            "url": "https://example.com/launch",
                            "snippet": "A launch date page.",
                        }
                    ],
                },
                {"type": "message.completed", "message": "The launch date is soon."},
            ],
        )

        result = evaluate_case(case)

        self.assertFalse(result.passed)
        self.assertTrue(
            any("expected freshness input" in failure for failure in result.failures)
        )

    def test_raw_citation_section_failure_is_reported(self):
        case = ResearchEvalCase(
            id="raw_citations",
            category="citation_integrity",
            prompt="Answer with sources.",
            expectations=ResearchEvalExpectations(),
            events=[
                {
                    "type": "message.completed",
                    "message": "Answer.\n\nCitations:\n[1] https://example.com",
                }
            ],
        )

        result = evaluate_case(case)

        self.assertFalse(result.passed)
        self.assertTrue(
            any("duplicate raw citation" in failure for failure in result.failures)
        )

    def test_multi_run_aggregation_reports_failed_run(self):
        case = ResearchEvalCase(
            id="multi_run",
            category="stable_concept",
            prompt="Explain DNA.",
            expectations=ResearchEvalExpectations(search="forbidden"),
            runs=[
                [
                    {
                        "type": "message.completed",
                        "message": "DNA carries genetic information.",
                    }
                ],
                [
                    {"type": "tool.started", "tool": "search_web", "input": {"query": "DNA"}},
                    {
                        "type": "message.completed",
                        "message": "DNA carries genetic information.",
                    },
                ],
            ],
        )

        result = evaluate_case(case)

        self.assertFalse(result.passed)
        self.assertEqual(result.metrics["run_count"], 2)
        self.assertEqual(result.metrics["passed_runs"], 1)
        self.assertTrue(any("run 2" in failure for failure in result.failures))

    def test_trace_counts_queries_fetches_sources_and_citations(self):
        trace = trace_from_events(
            [
                {
                    "type": "tool.started",
                    "tool": "search_multi_query",
                    "input": {"queries": ["one", "two"]},
                },
                {
                    "type": "tool.started",
                    "tool": "fetch_many",
                    "input": {"urls": ["https://a.example", "https://b.example"]},
                },
                {
                    "type": "tool.result",
                    "tool": "search_multi_query",
                    "result_preview": [
                        {"url": "https://a.example/path?utm_source=x"},
                        {"url": "https://a.example/path"},
                    ],
                },
                {"type": "message.completed", "message": "Answer [1]."},
            ]
        )

        self.assertEqual(trace.query_count, 2)
        self.assertEqual(trace.fetched_url_count, 2)
        self.assertEqual(len(trace.source_urls), 1)
        self.assertEqual(len(set(trace.citation_numbers)), 1)


if __name__ == "__main__":
    unittest.main()
