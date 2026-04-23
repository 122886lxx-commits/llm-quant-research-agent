import asyncio
import unittest
from typing import Any, Dict

from quant_research_agent.agent.repair import (
    CONFIG_ERROR,
    DATA_ERROR,
    PROVIDER_ERROR,
    VERIFICATION_ERROR,
    build_repair_prompt,
    classify_error,
    diff_pipelines,
)
from quant_research_agent.agent.workflow import SUCCESS, AgentRunState, AgentWorkflowRunner


def _edge_broken_pipeline() -> Dict[str, Any]:
    return {
        "pipeline_id": "edge_broken",
        "name": "Edge Broken",
        "steps": [
            {"id": "trigger", "kind": "trigger.manual", "config": {"universe": ["AAPL"]}, "next": []},
            {"id": "bars", "kind": "data.market_bars", "config": {"symbols": ["AAPL"], "lookback_days": 5}, "next": ["momentum"]},
            {"id": "momentum", "kind": "factor.momentum", "config": {"bars": "$bars", "window": 3}, "next": ["rank"]},
            {"id": "rank", "kind": "factor.rank", "config": {"values": "$momentum['scores']"}, "next": ["report"]},
            {"id": "report", "kind": "output.report", "config": {"sections": ["Ranking: $rank['top']"]}, "next": []},
        ],
    }


def _edge_repaired_pipeline() -> Dict[str, Any]:
    pipeline = _edge_broken_pipeline()
    pipeline["steps"][0]["next"] = ["bars"]
    pipeline["steps"][1]["config"] = {"symbols": "$trigger['universe']", "lookback_days": 5}
    return pipeline


class RepairTests(unittest.TestCase):
    def test_classifies_common_repair_error_classes(self) -> None:
        self.assertEqual(classify_error("run", "Step failed: 'missing'"), CONFIG_ERROR)
        self.assertEqual(classify_error("run", "factor.rank requires a score mapping in config.values"), CONFIG_ERROR)
        self.assertEqual(classify_error("run", "Unsupported demo symbols without fixture data: TSLA"), DATA_ERROR)
        self.assertEqual(classify_error("run", "research_chat requires OPENAI_API_KEY to be set"), PROVIDER_ERROR)
        self.assertEqual(classify_error("run", "model_not_found: gpt-3.5-turbo does not exist"), PROVIDER_ERROR)
        self.assertEqual(classify_error("verify", "Momentum step produced empty scores"), VERIFICATION_ERROR)

    def test_repair_prompt_contains_class_specific_guidance(self) -> None:
        prompt = build_repair_prompt(
            prompt="Explain a ranking",
            pipeline={"steps": []},
            errors=[{"stage": "run", "class": PROVIDER_ERROR, "message": "model_not_found"}],
        )

        self.assertIn("[provider_error]", prompt)
        self.assertIn("Avoid hardcoded legacy models", prompt)

    def test_diff_pipelines_tracks_edge_and_config_changes(self) -> None:
        diff = diff_pipelines(_edge_broken_pipeline(), _edge_repaired_pipeline())

        self.assertIn("trigger->bars", diff["added_edges"])
        changed_ids = [item["id"] for item in diff["changed_steps"]]
        self.assertIn("trigger", changed_ids)
        self.assertIn("bars", changed_ids)

    def test_workflow_repairs_missing_dependency_edge_and_records_diff(self) -> None:
        async def planner(_: str) -> Dict[str, Any]:
            return {"pipeline": _edge_broken_pipeline(), "messages": []}

        async def repairer(state: AgentRunState) -> Dict[str, Any]:
            self.assertEqual(state.errors[-1]["class"], VERIFICATION_ERROR)
            return {"pipeline": _edge_repaired_pipeline(), "messages": []}

        state = asyncio.run(AgentWorkflowRunner(planner=planner, repairer=repairer).run("rank momentum", max_repairs=1))

        self.assertEqual(state.status, SUCCESS)
        self.assertEqual(state.repair_attempts, 1)
        self.assertIn("trigger->bars", state.repair_diffs[0]["diff"]["added_edges"])
