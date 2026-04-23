import asyncio
import tempfile
import unittest
from pathlib import Path

import yaml

from quant_research_agent.evaluation import EvaluationRunner


def _valid_pipeline() -> dict:
    return {
        "pipeline_id": "eval_valid",
        "name": "Eval Valid",
        "steps": [
            {"id": "trigger", "kind": "trigger.manual", "config": {"universe": ["AAPL", "MSFT", "NVDA"]}, "next": ["bars"]},
            {"id": "bars", "kind": "data.market_bars", "config": {"symbols": "$trigger['universe']", "lookback_days": 5}, "next": ["momentum"]},
            {"id": "momentum", "kind": "factor.momentum", "config": {"bars": "$bars", "window": 3}, "next": ["rank"]},
            {"id": "rank", "kind": "factor.rank", "config": {"values": "$momentum['scores']", "descending": True}, "next": ["report"]},
            {"id": "report", "kind": "output.report", "config": {"sections": ["Eval ranking: $rank['top']"]}, "next": []},
        ],
    }


def _broken_pipeline() -> dict:
    return {
        "pipeline_id": "eval_broken",
        "name": "Eval Broken",
        "steps": [
            {"id": "momentum", "kind": "factor.momentum", "config": {"bars": "$missing", "window": 3}, "next": ["report"]},
            {"id": "report", "kind": "output.report", "config": {"sections": ["Broken pipeline."]}, "next": []},
        ],
    }


class EvaluationRunnerTests(unittest.TestCase):
    def test_runner_executes_pipeline_and_workflow_repair_tasks(self) -> None:
        task_file = {
            "tasks": [
                {
                    "id": "momentum_order",
                    "prompt": "Rank fixture symbols by momentum",
                    "pipeline": _valid_pipeline(),
                    "expect": {
                        "execution_success": True,
                        "verification_success": True,
                        "outputs": [{"path": "outputs.rank.top", "equals": ["NVDA", "AAPL", "MSFT"]}],
                    },
                },
                {
                    "id": "repair_missing_ref",
                    "mode": "workflow",
                    "prompt": "Repair missing reference",
                    "pipeline": _broken_pipeline(),
                    "repair_pipeline": _valid_pipeline(),
                    "max_repairs": 1,
                    "expect": {
                        "final_status": "success",
                        "repair_attempts": 1,
                        "outputs": [{"path": "outputs.rank.top", "equals": ["NVDA", "AAPL", "MSFT"]}],
                    },
                },
            ]
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            task_path = Path(tmpdir) / "tasks.yaml"
            output_path = Path(tmpdir) / "results" / "latest.json"
            task_path.write_text(yaml.safe_dump(task_file, sort_keys=False), encoding="utf-8")

            summary = asyncio.run(EvaluationRunner().run_path(task_path, output=output_path))

            self.assertTrue(output_path.exists())
            self.assertTrue(output_path.with_suffix(".md").exists())

        self.assertEqual(summary["total"], 2)
        self.assertEqual(summary["passed"], 2)
        self.assertEqual(summary["failed"], 0)
        self.assertEqual(summary["planning_success_rate"], 1.0)
        self.assertEqual(summary["execution_success_rate"], 1.0)
        self.assertEqual(summary["verification_success_rate"], 1.0)
        self.assertEqual(summary["repair_success_rate"], 1.0)

