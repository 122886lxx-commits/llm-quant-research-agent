import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import yaml

from ..agent.workflow import AgentRunState, AgentWorkflowRunner, PipelineVerifier
from ..engine.core.engine import PipelineEngine
from ..permissions import WRITE_ARTIFACT, PermissionPolicy


class EvaluationRunner:
    def __init__(
        self,
        engine: Optional[PipelineEngine] = None,
        verifier: Optional[PipelineVerifier] = None,
        permission_policy: Optional[PermissionPolicy] = None,
    ) -> None:
        self.permission_policy = permission_policy
        self.engine = engine or PipelineEngine(permission_policy=permission_policy)
        self.verifier = verifier or PipelineVerifier()

    async def run_path(self, path: Path, output: Optional[Path] = None) -> Dict[str, Any]:
        tasks = list(self._load_tasks(path))
        results = [await self._run_task(task) for task in tasks]
        summary = self._summarize(results)
        if output is not None:
            self._write_outputs(summary, output)
        return summary

    def _load_tasks(self, path: Path) -> Iterable[Dict[str, Any]]:
        paths = sorted(path.glob("*.yaml")) + sorted(path.glob("*.yml")) if path.is_dir() else [path]
        for task_path in paths:
            with open(task_path, "r", encoding="utf-8") as handle:
                payload = yaml.safe_load(handle) or {}
            raw_tasks = payload.get("tasks", [payload])
            for index, task in enumerate(raw_tasks, start=1):
                task = dict(task)
                task.setdefault("id", "{0}#{1}".format(task_path.stem, index))
                task["_source"] = str(task_path)
                yield task

    async def _run_task(self, task: Dict[str, Any]) -> Dict[str, Any]:
        mode = task.get("mode", "pipeline")
        result = self._base_result(task)
        try:
            if mode == "workflow" or task.get("repair_pipeline") is not None:
                result.update(await self._run_workflow_task(task))
            else:
                result.update(await self._run_pipeline_task(task))
        except Exception as exc:
            result["errors"].append(str(exc))

        assertion_result = self._check_expectations(task.get("expect", {}), result)
        result["output_assertions"] = assertion_result
        result["passed"] = (
            result["planning_validity"]
            and assertion_result["success"]
            and self._matches_expected_success(task.get("expect", {}), result)
        )
        return result

    def _base_result(self, task: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "id": task.get("id"),
            "prompt": task.get("prompt", ""),
            "mode": task.get("mode", "pipeline"),
            "source": task.get("_source"),
            "planning_validity": False,
            "execution_success": False,
            "verification_success": False,
            "repair_success": False,
            "repair_attempts": 0,
            "tool_call_count": int(task.get("tool_call_count", 0)),
            "final_status": "not_run",
            "outputs": {},
            "errors": [],
        }

    async def _run_pipeline_task(self, task: Dict[str, Any]) -> Dict[str, Any]:
        pipeline = self._resolve_pipeline(task, "pipeline")
        self.engine._load_pipeline(pipeline)
        try:
            execution_result = await self.engine.run_pipeline(pipeline)
        except Exception as exc:
            return {
                "planning_validity": True,
                "execution_success": False,
                "verification_success": False,
                "final_status": "failed_execution",
                "outputs": {},
                "errors": [{"stage": "run", "message": str(exc)}],
            }
        verification = self.verifier.verify(pipeline, execution_result)
        return {
            "planning_validity": True,
            "execution_success": execution_result.get("status") == "success",
            "verification_success": verification.success,
            "final_status": execution_result.get("status", "unknown"),
            "outputs": execution_result.get("outputs", {}),
            "verifier_errors": verification.errors,
        }

    async def _run_workflow_task(self, task: Dict[str, Any]) -> Dict[str, Any]:
        pipeline = self._resolve_pipeline(task, "pipeline")
        repair_pipeline = self._resolve_pipeline(task, "repair_pipeline") if task.get("repair_pipeline") else None

        async def planner(_: str) -> Dict[str, Any]:
            return {"pipeline": pipeline, "messages": [], "model": "deterministic-eval"}

        async def repairer(_: AgentRunState) -> Dict[str, Any]:
            if repair_pipeline is None:
                return {"pipeline": pipeline, "messages": [], "model": "deterministic-eval"}
            return {"pipeline": repair_pipeline, "messages": [], "model": "deterministic-eval"}

        state = await AgentWorkflowRunner(
            planner=planner,
            repairer=repairer,
            permission_policy=self.permission_policy,
        ).run(
            task.get("prompt", ""),
            max_repairs=int(task.get("max_repairs", 0)),
        )
        verification_success = state.verifier_result.success if state.verifier_result else False
        return {
            "planning_validity": state.current_pipeline is not None,
            "execution_success": bool(state.execution_result and state.execution_result.get("status") == "success"),
            "verification_success": verification_success,
            "repair_success": state.status == "success" and state.repair_attempts > 0,
            "repair_attempts": state.repair_attempts,
            "final_status": state.status,
            "outputs": (state.execution_result or {}).get("outputs", {}),
            "errors": state.errors,
            "stage_history": state.stage_history,
        }

    def _resolve_pipeline(self, task: Dict[str, Any], key: str) -> Dict[str, Any]:
        if key in task:
            return task[key]
        file_key = "{0}_file".format(key)
        if file_key in task:
            with open(Path(task[file_key]), "r", encoding="utf-8") as handle:
                payload = yaml.safe_load(handle) or {}
            return payload.get("pipeline", payload)
        raise ValueError("Task '{0}' is missing {1}".format(task.get("id"), key))

    def _check_expectations(self, expect: Dict[str, Any], result: Dict[str, Any]) -> Dict[str, Any]:
        failures: List[str] = []
        for key in ["final_status", "planning_validity", "execution_success", "verification_success", "repair_attempts"]:
            if key in expect and result.get(key) != expect[key]:
                failures.append("Expected {0}={1}, got {2}".format(key, expect[key], result.get(key)))

        for assertion in expect.get("outputs", []):
            self._check_output_assertion(assertion, result, failures)
        return {"success": not failures, "failures": failures}

    def _check_output_assertion(self, assertion: Dict[str, Any], result: Dict[str, Any], failures: List[str]) -> None:
        path = assertion["path"]
        try:
            actual = self._read_path(result, path)
        except Exception as exc:
            failures.append("{0}: {1}".format(path, exc))
            return

        if "equals" in assertion and actual != assertion["equals"]:
            failures.append("{0}: expected {1}, got {2}".format(path, assertion["equals"], actual))
        if "contains" in assertion and assertion["contains"] not in actual:
            failures.append("{0}: expected to contain {1}, got {2}".format(path, assertion["contains"], actual))
        if "length" in assertion and len(actual) != assertion["length"]:
            failures.append("{0}: expected length {1}, got {2}".format(path, assertion["length"], len(actual)))
        for operator in ["gt", "gte", "lt", "lte"]:
            if operator in assertion and not self._compare(actual, assertion[operator], operator):
                failures.append("{0}: expected {1} {2}, got {3}".format(path, operator, assertion[operator], actual))

    def _read_path(self, payload: Dict[str, Any], path: str) -> Any:
        current: Any = payload
        for part in path.split("."):
            if isinstance(current, list):
                current = current[int(part)]
            elif isinstance(current, dict):
                current = current[part]
            else:
                raise ValueError("Cannot read '{0}' from non-container value".format(part))
        return current

    def _compare(self, actual: Any, expected: Any, operator: str) -> bool:
        if operator == "gt":
            return actual > expected
        if operator == "gte":
            return actual >= expected
        if operator == "lt":
            return actual < expected
        if operator == "lte":
            return actual <= expected
        raise ValueError("Unsupported comparison operator: {0}".format(operator))

    def _matches_expected_success(self, expect: Dict[str, Any], result: Dict[str, Any]) -> bool:
        if "execution_success" in expect:
            return result["execution_success"] == expect["execution_success"]
        if "final_status" in expect:
            return result["final_status"] == expect["final_status"]
        return result["execution_success"]

    def _summarize(self, results: List[Dict[str, Any]]) -> Dict[str, Any]:
        total = len(results)
        passed = sum(1 for result in results if result["passed"])
        repair_tasks = [result for result in results if result["repair_attempts"] > 0 or result.get("repair_expected")]
        return {
            "total": total,
            "passed": passed,
            "failed": total - passed,
            "planning_success_rate": self._rate(results, "planning_validity"),
            "execution_success_rate": self._rate(results, "execution_success"),
            "verification_success_rate": self._rate(results, "verification_success"),
            "repair_success_rate": self._rate(repair_tasks, "repair_success") if repair_tasks else None,
            "tasks": results,
        }

    def _rate(self, results: List[Dict[str, Any]], key: str) -> float:
        if not results:
            return 0.0
        return round(sum(1 for result in results if result.get(key)) / len(results), 6)

    def _write_outputs(self, summary: Dict[str, Any], output: Path) -> None:
        if self.permission_policy is not None:
            self.permission_policy.require(WRITE_ARTIFACT, "write evaluation result artifacts")
        output.parent.mkdir(parents=True, exist_ok=True)
        with open(output, "w", encoding="utf-8") as handle:
            json.dump(summary, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
        markdown_path = output.with_suffix(".md")
        markdown_path.write_text(self.render_markdown(summary), encoding="utf-8")

    def render_markdown(self, summary: Dict[str, Any]) -> str:
        lines = [
            "# Evaluation Summary",
            "",
            "- Total: {0}".format(summary["total"]),
            "- Passed: {0}".format(summary["passed"]),
            "- Failed: {0}".format(summary["failed"]),
            "- Planning success rate: {0}".format(summary["planning_success_rate"]),
            "- Execution success rate: {0}".format(summary["execution_success_rate"]),
            "- Verification success rate: {0}".format(summary["verification_success_rate"]),
            "- Repair success rate: {0}".format(summary["repair_success_rate"]),
            "",
            "| Task | Status | Final Status | Execution | Verification |",
            "| --- | --- | --- | --- | --- |",
        ]
        for result in summary["tasks"]:
            status = "pass" if result["passed"] else "fail"
            lines.append(
                "| {0} | {1} | {2} | {3} | {4} |".format(
                    result["id"],
                    status,
                    result["final_status"],
                    result["execution_success"],
                    result["verification_success"],
                )
            )
        return "\n".join(lines) + "\n"
