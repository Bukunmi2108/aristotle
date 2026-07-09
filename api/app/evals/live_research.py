from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any

from app.evals.research import evaluate_case, load_eval_cases


async def collect_chat_events(
    ws_url: str,
    prompt: str,
    *,
    use_search: bool = True,
    max_search_results: int = 5,
    timeout_seconds: float = 180,
) -> list[dict[str, Any]]:
    from websockets.asyncio.client import connect

    events: list[dict[str, Any]] = []
    async with connect(ws_url, open_timeout=timeout_seconds) as websocket:
        await websocket.send(
            json.dumps(
                {
                    "type": "user.message",
                    "message": prompt,
                    "options": {
                        "use_search": use_search,
                        "max_search_results": max_search_results,
                    },
                }
            )
        )
        while True:
            raw = await asyncio.wait_for(websocket.recv(), timeout=timeout_seconds)
            event = json.loads(raw)
            if isinstance(event, dict):
                events.append(event)
                if event.get("type") in {"session.completed", "error"}:
                    return events


async def run_live_research_evals(
    fixture_dir: Path,
    *,
    ws_url: str,
    runs: int,
    timeout_seconds: float,
) -> int:
    cases = load_eval_cases(fixture_dir)
    results = []
    for case in cases:
        captured_runs = []
        for _ in range(runs):
            captured_runs.append(
                await collect_chat_events(
                    ws_url,
                    case.prompt,
                    timeout_seconds=timeout_seconds,
                )
            )
        live_case = case.model_copy(update={"runs": captured_runs, "events": []})
        results.append(evaluate_case(live_case))

    passed = sum(result.passed for result in results)
    print(f"{len(results)} live research fixtures")
    print(f"{passed} passed")
    print(f"{len(results) - passed} failed")
    for result in results:
        status = "PASS" if result.passed else "FAIL"
        print(
            f"- {status} {result.case_id}: pass_rate={result.pass_rate:.2f} "
            f"avg_score={result.average_score:.2f}"
        )
        for failure in result.failures:
            print(f"  - {failure}")
    return 0 if passed == len(results) else 1


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run research eval fixtures against a live Aristotle WebSocket."
    )
    parser.add_argument(
        "--ws-url",
        default="ws://localhost:8400/ws/chat",
        help="Aristotle chat WebSocket URL.",
    )
    parser.add_argument(
        "--fixtures",
        default="tests/evals/research",
        help="Directory containing research eval JSON fixtures.",
    )
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--timeout", type=float, default=180)
    args = parser.parse_args()

    return asyncio.run(
        run_live_research_evals(
            Path(args.fixtures),
            ws_url=args.ws_url,
            runs=max(1, args.runs),
            timeout_seconds=args.timeout,
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
