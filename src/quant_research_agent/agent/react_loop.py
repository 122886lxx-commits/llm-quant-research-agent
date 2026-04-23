import json
import os
from typing import Any, Dict, List, Optional, Tuple

from openai import AsyncOpenAI

from ..engine.core.builder import PipelineBuilder
from .tools import bind_builder, execute_tool, get_tool_specs

SYSTEM_PROMPT = """You operate a draft builder for quant research workflows.

Available actions:
- add_step
- update_step
- connect_steps
- get_catalog
- get_details
- get_pipeline

Operating rules:
- Build the plan through tool calls, not plain-text answers.
- add_step and update_step evaluate a step immediately and return either output or an error.
- Use catalog inspection before guessing a config shape.
- If a tool reports an error, repair the affected step instead of abandoning the draft.
- Export a reusable runtime plan: downstream prompts should reference upstream outputs, not copy tool-output values into static text.
- Only call get_pipeline after the draft contains a coherent ordered path.

For a simple momentum-ranking request, a sensible draft usually includes:
trigger.manual -> data.market_bars -> factor.momentum -> factor.rank -> research_chat

When market symbols are not specified, use the local smoke-test universe:
AAPL, MSFT, NVDA

For research_chat:
- Prefer omitting the model field so the runtime can use RESEARCH_CHAT_MODEL.
- Do not hardcode legacy model names such as gpt-3.5-turbo.
- Write prompts with runtime references such as $rank['ordered'] so the exported plan remains reusable.
"""

MAX_TEXT_ONLY_TURNS = 2
MAX_CONSECUTIVE_TOOL_FAILURES = 3


class ReactLoopAgent:
    def __init__(self, builder: Optional[PipelineBuilder] = None):
        self.builder = builder or PipelineBuilder()
        bind_builder(self.builder)
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("ReactLoopAgent requires OPENAI_API_KEY to be set")
        self.client = AsyncOpenAI(api_key=api_key, base_url=os.getenv("OPENAI_BASE_URL"))
        self.model = os.getenv("REACT_MODEL", "gpt-4o-mini")
        self.max_iters = 12

    async def run(self, prompt: str) -> Dict[str, Any]:
        coordinator = _LoopCoordinator(
            client=self.client,
            model=self.model,
            prompt=prompt,
            iteration_limit=self.max_iters,
        )
        transcript = await coordinator.run()
        return {"pipeline": self.builder.get_pipeline(), "messages": transcript, "model": self.model}


class _LoopCoordinator:
    def __init__(self, client: AsyncOpenAI, model: str, prompt: str, iteration_limit: int) -> None:
        self.client = client
        self.model = model
        self.iteration_limit = iteration_limit
        self.messages: List[Dict[str, Any]] = self._starting_transcript(prompt)
        self._tool_specs = get_tool_specs()
        self._text_only_turns = 0
        self._consecutive_tool_failures = 0
        self._last_tool_failure: Optional[Dict[str, Any]] = None

    async def run(self) -> List[Dict[str, Any]]:
        turn_count = 0
        while turn_count < self.iteration_limit:
            turn_count += 1
            reply = await self._next_model_message()
            self.messages.append(self._format_assistant_turn(reply))

            if not reply.tool_calls:
                self._text_only_turns += 1
                if self._text_only_turns >= MAX_TEXT_ONLY_TURNS:
                    self.messages.append(self._stop_message("Stopped after repeated assistant turns without tool use."))
                    break
                self.messages.append(self._nudge_message())
                continue

            self._text_only_turns = 0
            should_finish, had_failure = await self._apply_requested_actions(reply.tool_calls)
            if should_finish:
                break
            if had_failure:
                self._consecutive_tool_failures += 1
                self.messages.append(self._repair_message())
                if self._consecutive_tool_failures >= MAX_CONSECUTIVE_TOOL_FAILURES:
                    self.messages.append(self._stop_message("Stopped after repeated tool failures."))
                    break
            else:
                self._consecutive_tool_failures = 0

        if turn_count >= self.iteration_limit:
            self.messages.append(self._stop_message("Stopped after reaching the iteration limit."))
        return self.messages

    async def _next_model_message(self) -> Any:
        completion = await self.client.chat.completions.create(
            model=self.model,
            messages=self.messages,
            tools=self._tool_specs,
            tool_choice="auto",
            temperature=0,
        )
        return completion.choices[0].message

    async def _apply_requested_actions(self, tool_calls: List[Any]) -> Tuple[bool, bool]:
        should_finish = False
        had_failure = False
        self._last_tool_failure = None
        for tool_call in tool_calls:
            tool_message = await self._run_one_tool(tool_call)
            self.messages.append(tool_message)
            result = json.loads(tool_message["content"])
            if not result.get("success"):
                had_failure = True
                self._last_tool_failure = result
            if tool_call.function.name == "get_pipeline" and result.get("success"):
                should_finish = True
        return should_finish, had_failure

    async def _run_one_tool(self, tool_call: Any) -> Dict[str, Any]:
        raw_arguments = tool_call.function.arguments or "{}"
        try:
            parsed_arguments = json.loads(raw_arguments)
        except json.JSONDecodeError as exc:
            result = {
                "success": False,
                "stage": "tooling",
                "error": "Invalid JSON arguments for {0}: {1}".format(tool_call.function.name, exc.msg),
            }
        else:
            result = await execute_tool(tool_call.function.name, parsed_arguments)
        return {
            "role": "tool",
            "tool_call_id": tool_call.id,
            "name": tool_call.function.name,
            "content": json.dumps(result, ensure_ascii=True),
        }

    def _starting_transcript(self, prompt: str) -> List[Dict[str, Any]]:
        return [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": prompt}]

    def _format_assistant_turn(self, message: Any) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"role": "assistant", "content": message.content or ""}
        if message.tool_calls:
            payload["tool_calls"] = [self._encode_tool_call(tool_call) for tool_call in message.tool_calls]
        return payload

    def _encode_tool_call(self, tool_call: Any) -> Dict[str, Any]:
        return {
            "id": tool_call.id,
            "type": "function",
            "function": {"name": tool_call.function.name, "arguments": tool_call.function.arguments},
        }

    def _nudge_message(self) -> Dict[str, str]:
        return {
            "role": "user",
            "content": "Continue through tool use. Inspect, repair, or extend the draft, then export it with get_pipeline.",
        }

    def _repair_message(self) -> Dict[str, str]:
        failure = self._last_tool_failure or {}
        parts = ["The previous tool call failed. Repair the existing draft instead of restarting it."]
        if failure.get("step_id"):
            parts.append("Failing step: {0}".format(failure["step_id"]))
        if failure.get("kind"):
            parts.append("Step kind: {0}".format(failure["kind"]))
        if failure.get("stage"):
            parts.append("Stage: {0}".format(failure["stage"]))
        if failure.get("error"):
            parts.append("Error: {0}".format(failure["error"]))
        parts.append("Use get_details if the config shape is unclear, then update or connect steps.")
        return {"role": "user", "content": "\n".join(parts)}

    def _stop_message(self, reason: str) -> Dict[str, str]:
        return {"role": "system", "content": reason}
