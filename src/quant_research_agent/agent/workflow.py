from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional

from ..engine.core.engine import PipelineEngine
from .react_loop import ReactLoopAgent
from .tools import _pipeline_validation_error

SUCCESS = "success"
FAILED_PLANNING = "failed_planning"
FAILED_EXECUTION = "failed_execution"
FAILED_VERIFICATION = "failed_verification"
MAX_REPAIRS_EXCEEDED = "max_repairs_exceeded"

Planner = Callable[[str], Awaitable[Dict[str, Any]]]
Repairer = Callable[["AgentRunState"], Awaitable[Dict[str, Any]]]


@dataclass
class VerificationResult:
    success: bool
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {"success": self.success, "errors": list(self.errors), "warnings": list(self.warnings)}


@dataclass
class AgentRunState:
    prompt: str
    current_pipeline: Optional[Dict[str, Any]] = None
    execution_result: Optional[Dict[str, Any]] = None
    verifier_result: Optional[VerificationResult] = None
    errors: List[Dict[str, str]] = field(default_factory=list)
    repair_attempts: int = 0
    status: str = "running"
    stage_history: List[Dict[str, Any]] = field(default_factory=list)
    messages: List[Dict[str, Any]] = field(default_factory=list)

    def record_stage(self, stage: str, status: str, details: Optional[Dict[str, Any]] = None) -> None:
        entry: Dict[str, Any] = {"stage": stage, "status": status}
        if details:
            entry["details"] = details
        self.stage_history.append(entry)

    def add_error(self, stage: str, message: str) -> None:
        self.errors.append({"stage": stage, "message": message})

    def to_dict(self) -> Dict[str, Any]:
        return {
            "prompt": self.prompt,
            "status": self.status,
            "repair_attempts": self.repair_attempts,
            "pipeline": self.current_pipeline,
            "execution_result": self.execution_result,
            "verifier_result": self.verifier_result.to_dict() if self.verifier_result else None,
            "errors": list(self.errors),
            "stage_history": list(self.stage_history),
            "messages": list(self.messages),
        }


class PipelineVerifier:
    def verify(self, pipeline: Dict[str, Any], execution_result: Dict[str, Any]) -> VerificationResult:
        errors: List[str] = []
        warnings: List[str] = []

        validation_error = _pipeline_validation_error(pipeline)
        if validation_error:
            errors.append(validation_error)

        outputs = execution_result.get("outputs", {}) if isinstance(execution_result, dict) else {}
        if not outputs:
            errors.append("Execution produced no outputs")

        steps = pipeline.get("steps", []) if isinstance(pipeline, dict) else []
        for step in steps:
            step_id = step.get("id", "")
            kind = step.get("kind", "")
            output = outputs.get(step_id)
            if step_id and step_id not in outputs:
                errors.append("Step '{0}' produced no output".format(step_id))
                continue
            self._verify_step_output(step_id, kind, output, errors, warnings)

        self._verify_final_output(steps, outputs, errors, warnings)
        return VerificationResult(success=not errors, errors=errors, warnings=warnings)

    def _verify_step_output(
        self,
        step_id: str,
        kind: str,
        output: Any,
        errors: List[str],
        warnings: List[str],
    ) -> None:
        if kind == "factor.momentum":
            scores = output.get("scores", {}) if isinstance(output, dict) else {}
            if not scores:
                errors.append("Momentum step '{0}' produced empty scores".format(step_id))
            if isinstance(output, dict) and output.get("coverage", 0) <= 0:
                errors.append("Momentum step '{0}' has zero coverage".format(step_id))
        elif kind == "factor.rank":
            ordered = output.get("ordered", []) if isinstance(output, dict) else []
            if not ordered:
                errors.append("Rank step '{0}' produced an empty ordering".format(step_id))
        elif kind == "research_chat":
            content = output.get("content", "") if isinstance(output, dict) else ""
            if not str(content).strip():
                errors.append("Research chat step '{0}' produced empty content".format(step_id))
        elif kind == "output.report":
            sections = output.get("sections", []) if isinstance(output, dict) else []
            non_empty_sections = [section for section in sections if str(section).strip()]
            if not non_empty_sections:
                errors.append("Report step '{0}' produced no non-empty sections".format(step_id))
            elif len(" ".join(str(section) for section in non_empty_sections)) < 20:
                warnings.append("Report step '{0}' is very short".format(step_id))

    def _verify_final_output(
        self,
        steps: List[Dict[str, Any]],
        outputs: Dict[str, Any],
        errors: List[str],
        warnings: List[str],
    ) -> None:
        final_steps = [step for step in steps if not step.get("next")]
        final_kinds = {step.get("kind") for step in final_steps}
        if "research_chat" in final_kinds or "output.report" in final_kinds:
            return
        if steps:
            warnings.append("Pipeline has no final research_chat or output.report step")


class AgentWorkflowRunner:
    def __init__(
        self,
        planner: Optional[Planner] = None,
        repairer: Optional[Repairer] = None,
        verifier: Optional[PipelineVerifier] = None,
        engine: Optional[PipelineEngine] = None,
    ) -> None:
        self.planner = planner or self._run_react_planner
        self.repairer = repairer or self._run_react_repairer
        self.verifier = verifier or PipelineVerifier()
        self.engine = engine or PipelineEngine()

    async def run(self, prompt: str, max_repairs: int = 1) -> AgentRunState:
        state = AgentRunState(prompt=prompt)
        planned = await self._plan(state)
        if not planned:
            return state

        while True:
            executed = await self._run_pipeline(state)
            if not executed:
                if await self._repair_or_finish(state, max_repairs, FAILED_EXECUTION):
                    continue
                return state

            verified = self._verify(state)
            if verified:
                state.status = SUCCESS
                state.record_stage("finalize", SUCCESS)
                return state

            if await self._repair_or_finish(state, max_repairs, FAILED_VERIFICATION):
                continue
            return state

    async def _plan(self, state: AgentRunState) -> bool:
        state.record_stage("plan", "started")
        try:
            result = await self.planner(state.prompt)
            pipeline = result.get("pipeline") if isinstance(result, dict) else None
            if not isinstance(pipeline, dict):
                raise ValueError("Planner did not return a pipeline dictionary")
            state.current_pipeline = pipeline
            state.messages = list(result.get("messages", [])) if isinstance(result, dict) else []
        except Exception as exc:
            state.status = FAILED_PLANNING
            state.add_error("plan", str(exc))
            state.record_stage("plan", "failed", {"error": str(exc)})
            state.record_stage("finalize", FAILED_PLANNING)
            return False

        state.record_stage("plan", "success", {"step_count": len(pipeline.get("steps", []))})
        return True

    async def _run_pipeline(self, state: AgentRunState) -> bool:
        state.record_stage("run", "started", {"repair_attempts": state.repair_attempts})
        try:
            state.execution_result = await self.engine.run_pipeline(state.current_pipeline or {})
        except Exception as exc:
            state.execution_result = None
            state.add_error("run", str(exc))
            state.record_stage("run", "failed", {"error": str(exc)})
            return False

        state.record_stage("run", "success", {"status": state.execution_result.get("status")})
        return True

    def _verify(self, state: AgentRunState) -> bool:
        state.record_stage("verify", "started")
        result = self.verifier.verify(state.current_pipeline or {}, state.execution_result or {})
        state.verifier_result = result
        if not result.success:
            state.add_error("verify", "; ".join(result.errors))
            state.record_stage("verify", "failed", result.to_dict())
            return False
        state.record_stage("verify", "success", result.to_dict())
        return True

    async def _repair_or_finish(self, state: AgentRunState, max_repairs: int, failure_status: str) -> bool:
        if state.repair_attempts >= max_repairs:
            state.status = MAX_REPAIRS_EXCEEDED if max_repairs > 0 else failure_status
            state.record_stage("finalize", state.status)
            return False

        state.repair_attempts += 1
        state.record_stage("repair", "started", {"attempt": state.repair_attempts})
        try:
            result = await self.repairer(state)
            pipeline = result.get("pipeline") if isinstance(result, dict) else None
            if not isinstance(pipeline, dict):
                raise ValueError("Repairer did not return a pipeline dictionary")
            state.current_pipeline = pipeline
            state.execution_result = None
            state.verifier_result = None
            state.messages.extend(result.get("messages", []))
        except Exception as exc:
            state.status = failure_status
            state.add_error("repair", str(exc))
            state.record_stage("repair", "failed", {"error": str(exc)})
            state.record_stage("finalize", failure_status)
            return False

        state.record_stage("repair", "success", {"attempt": state.repair_attempts})
        return True

    async def _run_react_planner(self, prompt: str) -> Dict[str, Any]:
        return await ReactLoopAgent().run(prompt)

    async def _run_react_repairer(self, state: AgentRunState) -> Dict[str, Any]:
        instruction = self._repair_instruction(state)
        return await ReactLoopAgent().run(instruction)

    def _repair_instruction(self, state: AgentRunState) -> str:
        recent_errors = "\n".join("- {0}: {1}".format(item["stage"], item["message"]) for item in state.errors[-5:])
        verifier_errors = ""
        if state.verifier_result and state.verifier_result.errors:
            verifier_errors = "\nVerifier errors:\n" + "\n".join("- {0}".format(error) for error in state.verifier_result.errors)
        return (
            "Repair the quant research pipeline for this user request:\n{prompt}\n\n"
            "Current pipeline:\n{pipeline}\n\n"
            "Recent errors:\n{errors}{verifier_errors}\n\n"
            "Return a coherent executable pipeline through tool calls. Preserve the original user intent."
        ).format(
            prompt=state.prompt,
            pipeline=state.current_pipeline,
            errors=recent_errors or "- none",
            verifier_errors=verifier_errors,
        )
