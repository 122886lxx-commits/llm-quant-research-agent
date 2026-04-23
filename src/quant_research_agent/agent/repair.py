from typing import Any, Dict, List, Optional

PLANNING_ERROR = "planning_error"
CONFIG_ERROR = "config_error"
DATA_ERROR = "data_error"
PROVIDER_ERROR = "provider_error"
VERIFICATION_ERROR = "verification_error"


def classify_error(stage: str, message: str) -> str:
    lowered = message.lower()
    if stage == "plan":
        return PLANNING_ERROR
    if _is_provider_error(lowered):
        return PROVIDER_ERROR
    if _is_data_error(lowered):
        return DATA_ERROR
    if stage == "verify" or _is_verification_error(lowered):
        return VERIFICATION_ERROR
    return CONFIG_ERROR


def build_repair_prompt(
    prompt: str,
    pipeline: Optional[Dict[str, Any]],
    errors: List[Dict[str, str]],
    verifier_errors: Optional[List[str]] = None,
) -> str:
    primary_class = errors[-1].get("class", CONFIG_ERROR) if errors else CONFIG_ERROR
    sections = [
        "Repair the quant research pipeline for this user request:",
        prompt,
        "",
        "Current pipeline:",
        str(pipeline),
        "",
        "Recent errors:",
    ]
    if errors:
        sections.extend(
            "- {stage} [{klass}]: {message}".format(
                stage=error.get("stage", "unknown"),
                klass=error.get("class", classify_error(error.get("stage", ""), error.get("message", ""))),
                message=error.get("message", ""),
            )
            for error in errors[-5:]
        )
    else:
        sections.append("- none")

    if verifier_errors:
        sections.append("")
        sections.append("Verifier errors:")
        sections.extend("- {0}".format(error) for error in verifier_errors)

    sections.extend(["", "Repair strategy:", _guidance_for(primary_class)])
    sections.append("Return a coherent executable pipeline through tool calls. Preserve the original user intent.")
    return "\n".join(sections)


def diff_pipelines(before: Optional[Dict[str, Any]], after: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    before_steps = _steps_by_id(before)
    after_steps = _steps_by_id(after)
    before_ids = set(before_steps)
    after_ids = set(after_steps)

    changed_steps = []
    for step_id in sorted(before_ids & after_ids):
        before_step = before_steps[step_id]
        after_step = after_steps[step_id]
        changes = {}
        for field in ["kind", "config", "next"]:
            if before_step.get(field) != after_step.get(field):
                changes[field] = {"before": before_step.get(field), "after": after_step.get(field)}
        if changes:
            changed_steps.append({"id": step_id, "changes": changes})

    return {
        "added_steps": sorted(after_ids - before_ids),
        "removed_steps": sorted(before_ids - after_ids),
        "changed_steps": changed_steps,
        "added_edges": sorted(_edges(after) - _edges(before)),
        "removed_edges": sorted(_edges(before) - _edges(after)),
    }


def _is_provider_error(message: str) -> bool:
    markers = [
        "openai_api_key",
        "api key",
        "model_not_found",
        "does not exist",
        "no such model",
        "api call failed",
        "returned no choices",
        "returned empty content",
    ]
    return any(marker in message for marker in markers)


def _is_data_error(message: str) -> bool:
    markers = [
        "unsupported demo symbols",
        "no daily bars",
        "baostock",
        "requires at least one symbol",
        "lookback_days",
    ]
    return any(marker in message for marker in markers)


def _is_verification_error(message: str) -> bool:
    markers = [
        "empty scores",
        "zero coverage",
        "empty ordering",
        "disconnected",
        "multiple steps but no connections",
        "produced no output",
        "non-empty sections",
    ]
    return any(marker in message for marker in markers)


def _guidance_for(error_class: str) -> str:
    if error_class == PLANNING_ERROR:
        return "Rebuild a minimal valid plan from the catalog, then export only after all required steps are connected."
    if error_class == DATA_ERROR:
        return "Use supported fixture symbols or a live-data symbol with the required provider; keep lookback windows valid."
    if error_class == PROVIDER_ERROR:
        return "Avoid hardcoded legacy models, omit the model field when possible, and rely on configured provider defaults."
    if error_class == VERIFICATION_ERROR:
        return "Preserve executable steps but fix missing edges, empty outputs, or weak final report content."
    return "Fix invalid configs, wrong field names, missing references, and dependency edges before retrying execution."


def _steps_by_id(pipeline: Optional[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    if not isinstance(pipeline, dict):
        return {}
    return {step.get("id"): step for step in pipeline.get("steps", []) if step.get("id")}


def _edges(pipeline: Optional[Dict[str, Any]]) -> set:
    edges = set()
    if not isinstance(pipeline, dict):
        return edges
    for step in pipeline.get("steps", []):
        source = step.get("id")
        for target in step.get("next", []) or []:
            edges.add("{0}->{1}".format(source, target))
    return edges
