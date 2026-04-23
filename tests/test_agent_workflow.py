import asyncio
import unittest
from typing import Any, Dict

from quant_research_agent.agent.workflow import (
    FAILED_VERIFICATION,
    MAX_REPAIRS_EXCEEDED,
    SUCCESS,
    AgentRunState,
    AgentWorkflowRunner,
)


def _valid_report_pipeline() -> Dict[str, Any]:
    return {
        "pipeline_id": "workflow_success",
        "name": "Workflow Success",
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
                "config": {"sections": ["Momentum ranking with computed scores: $rank['ordered']"]},
                "next": [],
            },
        ],
    }


def _execution_failure_pipeline() -> Dict[str, Any]:
    return {
        "pipeline_id": "broken_reference",
        "name": "Broken Reference",
        "steps": [
            {
                "id": "momentum",
                "kind": "factor.momentum",
                "config": {"bars": "$missing", "window": 3},
                "next": ["report"],
            },
            {
                "id": "report",
                "kind": "output.report",
                "config": {"sections": ["This should not execute because momentum is broken."]},
                "next": [],
            },
        ],
    }


def _verification_failure_pipeline() -> Dict[str, Any]:
    return {
        "pipeline_id": "empty_scores",
        "name": "Empty Scores",
        "steps": [
            {
                "id": "momentum",
                "kind": "factor.momentum",
                "config": {"bars": {}, "window": 3},
                "next": ["report"],
            },
            {
                "id": "report",
                "kind": "output.report",
                "config": {"sections": ["Momentum report exists but scores are empty."]},
                "next": [],
            },
        ],
    }


class AgentWorkflowTests(unittest.TestCase):
    def test_successful_plan_run_verify(self) -> None:
        async def planner(_: str) -> Dict[str, Any]:
            return {"pipeline": _valid_report_pipeline(), "messages": [{"role": "assistant", "content": "planned"}]}

        state = asyncio.run(AgentWorkflowRunner(planner=planner).run("rank momentum", max_repairs=0))

        self.assertEqual(state.status, SUCCESS)
        self.assertEqual(state.repair_attempts, 0)
        self.assertEqual(state.execution_result["outputs"]["rank"]["top"], ["NVDA", "AAPL", "MSFT"])
        self.assertTrue(state.verifier_result.success)
        self.assertEqual(state.stage_history[0], {"stage": "plan", "status": "started"})
        self.assertEqual(state.stage_history[-1], {"stage": "finalize", "status": SUCCESS})
        self.assertIn({"stage": "verify", "status": "success", "details": state.verifier_result.to_dict()}, state.stage_history)

    def test_execution_failure_can_be_repaired(self) -> None:
        async def planner(_: str) -> Dict[str, Any]:
            return {"pipeline": _execution_failure_pipeline(), "messages": []}

        async def repairer(state: AgentRunState) -> Dict[str, Any]:
            self.assertTrue(any(error["stage"] == "run" for error in state.errors))
            return {"pipeline": _valid_report_pipeline(), "messages": [{"role": "assistant", "content": "repaired"}]}

        state = asyncio.run(AgentWorkflowRunner(planner=planner, repairer=repairer).run("rank momentum", max_repairs=1))

        self.assertEqual(state.status, SUCCESS)
        self.assertEqual(state.repair_attempts, 1)
        self.assertTrue(state.verifier_result.success)
        self.assertIn("repaired", [message.get("content") for message in state.messages])

    def test_verification_failure_without_repair_budget(self) -> None:
        async def planner(_: str) -> Dict[str, Any]:
            return {"pipeline": _verification_failure_pipeline(), "messages": []}

        state = asyncio.run(AgentWorkflowRunner(planner=planner).run("rank momentum", max_repairs=0))

        self.assertEqual(state.status, FAILED_VERIFICATION)
        self.assertFalse(state.verifier_result.success)
        self.assertIn("empty scores", "; ".join(state.verifier_result.errors))

    def test_max_repairs_exceeded_after_repeated_execution_failure(self) -> None:
        async def planner(_: str) -> Dict[str, Any]:
            return {"pipeline": _execution_failure_pipeline(), "messages": []}

        async def repairer(_: AgentRunState) -> Dict[str, Any]:
            return {"pipeline": _execution_failure_pipeline(), "messages": []}

        state = asyncio.run(AgentWorkflowRunner(planner=planner, repairer=repairer).run("rank momentum", max_repairs=1))

        self.assertEqual(state.status, MAX_REPAIRS_EXCEEDED)
        self.assertEqual(state.repair_attempts, 1)
        self.assertGreaterEqual(len([item for item in state.errors if item["stage"] == "run"]), 2)
