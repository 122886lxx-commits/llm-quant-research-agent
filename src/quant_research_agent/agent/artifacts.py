import json
from pathlib import Path
from typing import Any, Dict, Optional

import yaml

from ..permissions import WRITE_ARTIFACT, PermissionPolicy


def write_run_artifacts(
    prompt: str,
    pipeline: Dict[str, Any],
    execution_result: Optional[Dict[str, Any]],
    output_dir: Path,
    permission_policy: Optional[PermissionPolicy] = None,
    save_pipeline: bool = True,
    save_report: bool = True,
) -> Dict[str, str]:
    if permission_policy is not None:
        permission_policy.require(WRITE_ARTIFACT, "write run artifacts")
    output_dir.mkdir(parents=True, exist_ok=True)
    paths: Dict[str, str] = {}

    if save_pipeline:
        pipeline_path = output_dir / "generated_pipeline.yaml"
        pipeline_path.write_text(yaml.safe_dump({"pipeline": pipeline}, sort_keys=False), encoding="utf-8")
        paths["pipeline"] = str(pipeline_path)

    if execution_result is not None:
        result_path = output_dir / "run_result.json"
        result_path.write_text(json.dumps(execution_result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        paths["run_result"] = str(result_path)

    if save_report:
        report_path = output_dir / "research_report.md"
        report_path.write_text(render_markdown_report(prompt, pipeline, execution_result or {}), encoding="utf-8")
        paths["report"] = str(report_path)

    return paths


def render_markdown_report(prompt: str, pipeline: Dict[str, Any], execution_result: Dict[str, Any]) -> str:
    outputs = execution_result.get("outputs", {}) if isinstance(execution_result, dict) else {}
    sections = [
        "# Quant Research Report",
        "",
        "## Prompt",
        "",
        prompt or "(empty)",
        "",
        "## Pipeline Summary",
        "",
        "| Step | Kind | Next |",
        "| --- | --- | --- |",
    ]
    for step in pipeline.get("steps", []):
        sections.append(
            "| {0} | {1} | {2} |".format(
                step.get("id", ""),
                step.get("kind", ""),
                ", ".join(step.get("next", []) or []) or "-",
            )
        )

    _append_ranked_table(sections, outputs)
    _append_momentum_scores(sections, outputs)
    _append_final_explanation(sections, outputs)
    return "\n".join(sections) + "\n"


def _append_ranked_table(sections: list, outputs: Dict[str, Any]) -> None:
    rank_output = _first_output_with_key(outputs, "ordered")
    ordered = rank_output.get("ordered", []) if isinstance(rank_output, dict) else []
    if not ordered:
        return
    sections.extend(["", "## Ranked Output", "", "| Rank | Symbol | Score |", "| --- | --- | --- |"])
    for row in ordered:
        sections.append("| {0} | {1} | {2} |".format(row.get("rank"), row.get("symbol"), row.get("score")))


def _append_momentum_scores(sections: list, outputs: Dict[str, Any]) -> None:
    momentum_output = _first_output_with_key(outputs, "scores")
    scores = momentum_output.get("scores", {}) if isinstance(momentum_output, dict) else {}
    if not scores:
        return
    sections.extend(["", "## Momentum Scores", "", "| Symbol | Score |", "| --- | --- |"])
    for symbol, score in sorted(scores.items()):
        sections.append("| {0} | {1} |".format(symbol, score))


def _append_final_explanation(sections: list, outputs: Dict[str, Any]) -> None:
    explanation = _find_explanation(outputs)
    if not explanation:
        return
    sections.extend(["", "## Final Explanation", "", explanation])


def _find_explanation(outputs: Dict[str, Any]) -> str:
    for output in outputs.values():
        if isinstance(output, dict) and str(output.get("content", "")).strip():
            return str(output["content"]).strip()
    for output in outputs.values():
        if isinstance(output, dict) and isinstance(output.get("sections"), list):
            return "\n\n".join(str(section) for section in output["sections"] if str(section).strip())
    return ""


def _first_output_with_key(outputs: Dict[str, Any], key: str) -> Dict[str, Any]:
    for output in outputs.values():
        if isinstance(output, dict) and key in output:
            return output
    return {}
