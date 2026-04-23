import asyncio
import tempfile
import unittest
from pathlib import Path

from quant_research_agent.agent.tracing import load_trace, write_trace
from quant_research_agent.engine.core.engine import PipelineEngine
from quant_research_agent.permissions import (
    DESTRUCTIVE,
    NETWORK,
    WRITE_ARTIFACT,
    PermissionDenied,
    PermissionPolicy,
)


class PermissionTests(unittest.TestCase):
    def test_policy_denies_network_by_default_and_records_decision(self) -> None:
        policy = PermissionPolicy()

        with self.assertRaises(PermissionDenied):
            policy.require(NETWORK, "fetch live data")

        self.assertEqual(policy.to_trace()[0]["permission"], NETWORK)
        self.assertFalse(policy.to_trace()[0]["allowed"])

    def test_destructive_permission_is_blocked_by_default_even_if_allowed(self) -> None:
        policy = PermissionPolicy([DESTRUCTIVE])

        with self.assertRaises(PermissionDenied):
            policy.require(DESTRUCTIVE, "delete files")

        self.assertEqual(policy.to_trace()[0]["mode"], "blocked")

    def test_live_market_bars_requires_network_permission(self) -> None:
        pipeline = {
            "pipeline_id": "live_permission",
            "name": "Live Permission",
            "steps": [
                {
                    "id": "bars",
                    "kind": "data.market_bars",
                    "config": {"symbols": ["sh.600000"], "lookback_days": 5},
                    "next": [],
                }
            ],
        }

        with self.assertRaisesRegex(RuntimeError, "Permission 'network' is required"):
            asyncio.run(PipelineEngine(permission_policy=PermissionPolicy()).run_pipeline(pipeline))

    def test_write_trace_requires_write_artifact_permission_when_policy_is_provided(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            with self.assertRaises(PermissionDenied):
                write_trace(
                    {"kind": "test", "final_status": "success"},
                    runs_dir=Path(tmpdir),
                    permission_policy=PermissionPolicy(),
                )

    def test_write_trace_logs_permission_decisions(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            policy = PermissionPolicy([WRITE_ARTIFACT])
            trace_path = write_trace(
                {"kind": "test", "final_status": "success"},
                runs_dir=Path(tmpdir),
                permission_policy=policy,
            )
            trace = load_trace(trace_path)

        self.assertEqual(trace["permission_decisions"][0]["permission"], WRITE_ARTIFACT)
        self.assertTrue(trace["permission_decisions"][0]["allowed"])

