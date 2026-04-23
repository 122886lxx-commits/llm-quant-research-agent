import asyncio
import unittest
from pathlib import Path

from quant_research_agent.engine.core.engine import PipelineEngine


class EngineTests(unittest.TestCase):
    def test_runs_momentum_pipeline_without_llm_step_when_report_is_used(self) -> None:
        pipeline = {
            "pipeline_id": "test",
            "name": "Test",
            "steps": [
                {
                    "id": "trigger",
                    "kind": "trigger.manual",
                    "config": {"universe": ["AAPL", "MSFT", "NVDA"]},
                    "next": ["bars"],
                },
                {
                    "id": "bars",
                    "kind": "data.market_bars",
                    "config": {"symbols": "$trigger['universe']", "lookback_days": 5},
                    "next": ["momentum"],
                },
                {
                    "id": "momentum",
                    "kind": "factor.momentum",
                    "config": {"bars": "$bars", "window": 3},
                    "next": ["rank"],
                },
                {
                    "id": "rank",
                    "kind": "factor.rank",
                    "config": {"values": "$momentum['scores']", "descending": True},
                    "next": ["report"],
                },
                {
                    "id": "report",
                    "kind": "output.report",
                    "config": {"sections": ["Ranking result: $rank['top']"]},
                },
            ],
        }

        result = asyncio.run(PipelineEngine().run_pipeline(pipeline))

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["outputs"]["rank"]["top"], ["NVDA", "AAPL", "MSFT"])
        self.assertIn("NVDA", result["outputs"]["report"]["sections"][0])

    def test_example_yaml_parses(self) -> None:
        path = Path(__file__).resolve().parents[1] / "examples" / "momentum_pipeline.yaml"
        pipeline = PipelineEngine()._load_pipeline(path)
        self.assertEqual(pipeline.pipeline_id, "momentum_demo")
        self.assertEqual([step.id for step in pipeline.steps], ["trigger", "bars", "momentum", "rank", "chat"])

