import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from ..engine.core.engine import PipelineEngine

TRACE_VERSION = 1
DEFAULT_RUNS_DIR = Path("runs")
REDACTED = "[REDACTED]"
SECRET_KEYWORDS = ("api_key", "apikey", "token", "secret", "password", "authorization")


def build_agent_trace(state: Any) -> Dict[str, Any]:
    return {
        "trace_version": TRACE_VERSION,
        "kind": "agent",
        "created_at": _now_iso(),
        "prompt": state.prompt,
        "model": getattr(state, "model", None),
        "messages": state.messages,
        "pipeline": state.current_pipeline,
        "execution_result": state.execution_result,
        "verifier_result": state.verifier_result.to_dict() if state.verifier_result else None,
        "repairs": {"attempts": state.repair_attempts},
        "stage_history": state.stage_history,
        "errors": state.errors,
        "final_status": state.status,
    }


def build_plan_trace(
    prompt: str,
    planning_result: Dict[str, Any],
    execution_result: Optional[Dict[str, Any]],
    final_status: str,
    errors: Optional[Any] = None,
) -> Dict[str, Any]:
    return {
        "trace_version": TRACE_VERSION,
        "kind": "plan_execute",
        "created_at": _now_iso(),
        "prompt": prompt,
        "model": planning_result.get("model"),
        "messages": planning_result.get("messages", []),
        "pipeline": planning_result.get("pipeline"),
        "execution_result": execution_result,
        "verifier_result": None,
        "repairs": {"attempts": 0},
        "stage_history": _plan_stage_history(execution_result, final_status),
        "errors": errors or [],
        "final_status": final_status,
    }


def write_trace(payload: Dict[str, Any], run_dir: Optional[Path] = None, runs_dir: Path = DEFAULT_RUNS_DIR) -> Path:
    destination = run_dir or _new_run_dir(runs_dir)
    destination.mkdir(parents=True, exist_ok=True)
    trace_path = destination / "trace.json"
    with open(trace_path, "w", encoding="utf-8") as handle:
        json.dump(sanitize_for_trace(payload), handle, indent=2, ensure_ascii=False)
        handle.write("\n")

    if run_dir is None:
        _update_latest(trace_path, runs_dir)
    return trace_path


def load_trace(path: Path) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def format_trace_summary(trace: Dict[str, Any]) -> str:
    summary = summarize_trace(trace)
    lines = [
        "Trace Summary",
        "  kind: {0}".format(summary["kind"]),
        "  status: {0}".format(summary["final_status"]),
        "  model: {0}".format(summary["model"] or "unknown"),
        "  prompt: {0}".format(summary["prompt"]),
        "  steps: {0}".format(", ".join(summary["steps"]) or "none"),
        "  outputs: {0}".format(", ".join(summary["output_keys"]) or "none"),
        "  tool_calls: {0}".format(summary["tool_call_count"]),
        "  repairs: {0}".format(summary["repair_attempts"]),
    ]
    if summary["errors"]:
        lines.append("  errors: {0}".format("; ".join(summary["errors"])))
    return "\n".join(lines)


def summarize_trace(trace: Dict[str, Any]) -> Dict[str, Any]:
    pipeline = trace.get("pipeline") or {}
    execution_result = trace.get("execution_result") or {}
    messages = trace.get("messages") or []
    steps = [
        "{0}:{1}".format(step.get("id", "?"), step.get("kind", "?"))
        for step in pipeline.get("steps", [])
    ]
    return {
        "kind": trace.get("kind"),
        "final_status": trace.get("final_status"),
        "model": trace.get("model"),
        "prompt": trace.get("prompt"),
        "steps": steps,
        "output_keys": sorted((execution_result.get("outputs") or {}).keys()),
        "tool_call_count": sum(len(message.get("tool_calls", [])) for message in messages),
        "tool_result_count": sum(1 for message in messages if message.get("role") == "tool"),
        "repair_attempts": (trace.get("repairs") or {}).get("attempts", 0),
        "errors": [item.get("message", str(item)) for item in trace.get("errors", [])],
    }


async def replay_trace(path: Path, engine: Optional[PipelineEngine] = None) -> Dict[str, Any]:
    trace = load_trace(path)
    pipeline = trace.get("pipeline")
    if not isinstance(pipeline, dict):
        raise ValueError("Trace does not contain a replayable pipeline")
    result = await (engine or PipelineEngine()).run_pipeline(pipeline)
    return {"trace_path": str(path), "status": result.get("status"), "result": result}


def sanitize_for_trace(value: Any) -> Any:
    if isinstance(value, dict):
        sanitized: Dict[str, Any] = {}
        for key, item in value.items():
            if _is_secret_key(key):
                sanitized[key] = REDACTED
            else:
                sanitized[key] = sanitize_for_trace(item)
        return sanitized
    if isinstance(value, list):
        return [sanitize_for_trace(item) for item in value]
    if isinstance(value, str):
        return _redact_string(value)
    return value


def _plan_stage_history(execution_result: Optional[Dict[str, Any]], final_status: str) -> Any:
    plan_status = "failed" if final_status == "failed_planning" else "success"
    stages = [{"stage": "plan", "status": plan_status}]
    if execution_result is not None:
        stages.append({"stage": "run", "status": execution_result.get("status", final_status)})
    elif final_status == "failed_execution":
        stages.append({"stage": "run", "status": "failed"})
    stages.append({"stage": "finalize", "status": final_status})
    return stages


def _new_run_dir(runs_dir: Path) -> Path:
    runs_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    candidate = runs_dir / stamp
    suffix = 1
    while candidate.exists():
        candidate = runs_dir / "{0}-{1}".format(stamp, suffix)
        suffix += 1
    return candidate


def _update_latest(trace_path: Path, runs_dir: Path) -> None:
    latest_dir = runs_dir / "latest"
    if latest_dir.exists():
        if latest_dir.is_dir():
            shutil.rmtree(latest_dir)
        else:
            latest_dir.unlink()
    latest_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(trace_path, latest_dir / "trace.json")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_secret_key(key: Any) -> bool:
    lowered = str(key).lower().replace("-", "_")
    return any(keyword in lowered for keyword in SECRET_KEYWORDS)


def _redact_string(value: str) -> str:
    value = re.sub(r"(?i)(api[_-]?key\s*[=:]\s*)[^\s,;]+", r"\1{0}".format(REDACTED), value)
    value = re.sub(r"(?i)(authorization\s*:\s*bearer\s+)[^\s,;]+", r"\1{0}".format(REDACTED), value)
    value = re.sub(r"sk-[A-Za-z0-9_-]{8,}", REDACTED, value)
    return value
