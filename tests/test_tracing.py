import asyncio
import json
import tempfile
import unittest
from pathlib import Path

from quant_research_agent.agent.tracing import (
    REDACTED,
    build_plan_trace,
    format_trace_summary,
    replay_trace,
    sanitize_for_trace,
    write_trace,
)


def _replayable_trace() -> dict:
    return {
        "trace_version": 1,
        "kind": "agent",
        "prompt": "Rank fixture symbols by momentum",
        "model": "test-model",
        "messages": [
            {
                "role": "assistant",
                "tool_calls": [
                    {"id": "call_1", "function": {"name": "add_step", "arguments": "{}"}},
                ],
            },
            {"role": "tool", "content": "{}"},
        ],
        "pipeline": {
            "pipeline_id": "trace_replay",
            "name": "Trace Replay",
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
                    "config": {"sections": ["Trace replay ranking: $rank['top']"]},
                    "next": [],
                },
            ],
        },
        "execution_result": {"outputs": {"rank": {"top": ["NVDA", "AAPL", "MSFT"]}}},
        "repairs": {"attempts": 1},
        "errors": [],
        "final_status": "success",
    }


class TraceTests(unittest.TestCase):
    def test_write_trace_redacts_secrets_and_updates_latest(self) -> None:
        payload = _replayable_trace()
        payload["api_key"] = "sk-raw-secret-value"
        payload["messages"].append({"role": "user", "content": "api_key=sk-another-secret-value"})

        with tempfile.TemporaryDirectory() as tmpdir:
            trace_path = write_trace(payload, runs_dir=Path(tmpdir))
            latest_path = Path(tmpdir) / "latest" / "trace.json"

            self.assertTrue(trace_path.exists())
            self.assertTrue(latest_path.exists())
            raw = trace_path.read_text(encoding="utf-8")
            self.assertNotIn("sk-raw-secret-value", raw)
            self.assertNotIn("sk-another-secret-value", raw)
            self.assertIn(REDACTED, raw)

    def test_summary_counts_pipeline_outputs_and_tool_activity(self) -> None:
        summary = format_trace_summary(_replayable_trace())

        self.assertIn("status: success", summary)
        self.assertIn("trigger:trigger.manual", summary)
        self.assertIn("outputs: rank", summary)
        self.assertIn("tool_calls: 1", summary)
        self.assertIn("repairs: 1", summary)

    def test_replay_trace_reruns_saved_pipeline(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            trace_path = Path(tmpdir) / "trace.json"
            trace_path.write_text(json.dumps(_replayable_trace()), encoding="utf-8")

            result = asyncio.run(replay_trace(trace_path))

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["result"]["outputs"]["rank"]["top"], ["NVDA", "AAPL", "MSFT"])

    def test_sanitize_for_trace_redacts_secret_keys_and_bearer_values(self) -> None:
        sanitized = sanitize_for_trace(
            {
                "OPENAI_API_KEY": "sk-test-secret-value",
                "headers": {"Authorization": "Bearer sk-header-secret-value"},
                "safe": "not secret",
            }
        )

        self.assertEqual(sanitized["OPENAI_API_KEY"], REDACTED)
        self.assertEqual(sanitized["headers"]["Authorization"], REDACTED)
        self.assertEqual(sanitized["safe"], "not secret")

    def test_plan_trace_records_planning_failure(self) -> None:
        trace = build_plan_trace(
            "rank momentum",
            {},
            None,
            "failed_planning",
            [{"stage": "plan", "message": "missing API key"}],
        )

        self.assertEqual(trace["stage_history"][0], {"stage": "plan", "status": "failed"})
        self.assertEqual(trace["final_status"], "failed_planning")
        self.assertEqual(trace["errors"][0]["message"], "missing API key")
