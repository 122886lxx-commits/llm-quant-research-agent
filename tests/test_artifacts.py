import asyncio
import tempfile
import unittest
from pathlib import Path

from quant_research_agent.agent.artifacts import render_markdown_report, write_run_artifacts
from quant_research_agent.engine.core.engine import PipelineEngine
from quant_research_agent.permissions import WRITE_ARTIFACT, PermissionPolicy


def _artifact_pipeline() -> dict:
    return {
        "pipeline_id": "artifact_demo",
        "name": "Artifact Demo",
        "steps": [
            {"id": "trigger", "kind": "trigger.manual", "config": {"universe": ["AAPL", "MSFT", "NVDA"]}, "next": ["bars"]},
            {"id": "bars", "kind": "data.market_bars", "config": {"symbols": "$trigger['universe']", "lookback_days": 5}, "next": ["momentum"]},
            {"id": "momentum", "kind": "factor.momentum", "config": {"bars": "$bars", "window": 3}, "next": ["rank"]},
            {"id": "rank", "kind": "factor.rank", "config": {"values": "$momentum['scores']", "descending": True}, "next": ["report"]},
            {"id": "report", "kind": "output.report", "config": {"sections": ["Artifact ranking: $rank['top']"]}, "next": []},
        ],
    }


class ArtifactTests(unittest.TestCase):
    def test_write_artifacts_and_rerun_saved_pipeline(self) -> None:
        pipeline = _artifact_pipeline()
        result = asyncio.run(PipelineEngine().run_pipeline(pipeline))

        with tempfile.TemporaryDirectory() as tmpdir:
            paths = write_run_artifacts(
                prompt="Rank fixture symbols by momentum",
                pipeline=pipeline,
                execution_result=result,
                output_dir=Path(tmpdir),
                permission_policy=PermissionPolicy([WRITE_ARTIFACT]),
            )
            rerun = asyncio.run(PipelineEngine().run_pipeline(paths["pipeline"]))
            report = Path(paths["report"]).read_text(encoding="utf-8")

        self.assertEqual(rerun["outputs"]["rank"]["top"], ["NVDA", "AAPL", "MSFT"])
        self.assertIn("## Prompt", report)
        self.assertIn("## Pipeline Summary", report)
        self.assertIn("| 1 | NVDA | 0.067308 |", report)
        self.assertIn("## Final Explanation", report)

    def test_render_report_includes_chat_content_as_final_explanation(self) -> None:
        report = render_markdown_report(
            "Explain ranking",
            {"steps": [{"id": "chat", "kind": "research_chat", "next": []}]},
            {"outputs": {"chat": {"content": "NVDA leads because it has the strongest momentum."}}},
        )

        self.assertIn("NVDA leads", report)

