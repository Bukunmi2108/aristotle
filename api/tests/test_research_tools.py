import asyncio
import unittest
from types import SimpleNamespace
from typing import Any, cast

from app.agent.capabilities.research import (
    RESEARCH_TOOL_NAMES,
    ResearchSource,
    ResearchTools,
    _build_citations,
    _canonical_url,
    _cap_unique_strings,
    _extract_facts,
    _rank_source,
)


class ResearchToolsHelpersTest(unittest.TestCase):
    def test_caps_unique_strings(self):
        self.assertEqual(
            _cap_unique_strings([" first  query ", "FIRST QUERY", "", "second"], 2),
            ["first query", "second"],
        )

    def test_canonical_url_removes_tracking_params(self):
        self.assertEqual(
            _canonical_url("https://Example.com/path/?utm_source=x&ok=1&fbclid=y"),
            "https://example.com/path?ok=1",
        )

    def test_extract_facts_returns_bounded_source_facts(self):
        source = ResearchSource(
            url="https://example.com",
            title="Example",
            content=(
                "This first sentence is long enough to become a usable source fact. "
                "This second sentence is also long enough to become a separate fact."
            ),
        )

        facts = _extract_facts(source, max_facts=1)

        self.assertEqual(len(facts), 1)
        self.assertEqual(facts[0].url, source.url)
        self.assertIn("first sentence", facts[0].fact)

    def test_rank_source_uses_goal_overlap(self):
        ranked = _rank_source(
            "renewable energy policy",
            ResearchSource(
                url="https://example.com",
                title="Renewable energy report",
                content="Policy analysis on renewable power.",
            ),
        )

        self.assertGreater(ranked.relevance_score, 0)
        self.assertTrue(ranked.reasons)

    def test_build_citations_uses_known_sources_only(self):
        result = _build_citations(
            "Renewable energy policy is changing.",
            [
                ResearchSource(
                    url="https://example.com/report",
                    title="Energy report",
                    content="Renewable energy policy details.",
                )
            ],
            max_sources=3,
        )

        self.assertEqual(len(result.citations), 1)
        self.assertEqual(result.citations[0].marker, "[1]")
        self.assertEqual(result.citations[0].url, "https://example.com/report")

    def test_prepare_tools_hides_research_tools_when_disabled(self):
        tools = [SimpleNamespace(name=name) for name in sorted(RESEARCH_TOOL_NAMES)]
        tools.append(SimpleNamespace(name="calculate"))
        ctx = SimpleNamespace(
            deps=SimpleNamespace(web_tools_enabled=False),
        )

        filtered = asyncio.run(
            ResearchTools().prepare_tools(cast(Any, ctx), cast(Any, tools))
        )

        self.assertEqual([tool.name for tool in filtered], ["calculate"])

    def test_research_tools_do_not_expose_fetch_many(self):
        self.assertNotIn("fetch_many", RESEARCH_TOOL_NAMES)
        instructions = ResearchTools().get_instructions()(
            cast(Any, SimpleNamespace(deps=SimpleNamespace(web_tools_enabled=True)))
        )

        assert instructions is not None
        self.assertNotIn("fetch_many", instructions)
        self.assertIn("fetch_url", instructions)


if __name__ == "__main__":
    unittest.main()
