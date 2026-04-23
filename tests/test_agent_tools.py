import asyncio
import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from quant_research_agent.agent.tools import _pipeline_validation_error, bind_builder
from quant_research_agent.engine.core.builder import PipelineBuilder
from quant_research_agent.engine.nodes.ai.research_chat import ResearchChatStep


class ToolValidationTests(unittest.TestCase):
    def test_rejects_disconnected_later_step(self) -> None:
        pipeline = {
            "pipeline_id": "builder_pipeline",
            "name": "Untitled Pipeline",
            "steps": [
                {"id": "trigger", "kind": "trigger.manual", "config": {"universe": ["AAPL"]}, "next": ["bars"]},
                {"id": "bars", "kind": "data.market_bars", "config": {"symbols": "$trigger['universe']"}, "next": []},
                {"id": "chat", "kind": "research_chat", "config": {"prompt": "Explain static text"}, "next": []},
            ],
        }

        self.assertEqual(
            _pipeline_validation_error(pipeline),
            "Pipeline has disconnected non-initial steps: chat",
        )

    def test_builder_surfaces_unresolved_reference(self) -> None:
        builder = PipelineBuilder()
        bind_builder(builder)
        step_id = builder.add_step("factor.momentum", {"bars": "$missing", "window": 3}, step_id="momentum")

        with self.assertRaisesRegex(RuntimeError, "missing"):
            asyncio.run(builder.execute_step(step_id))


class ResearchChatTests(unittest.TestCase):
    def test_retries_with_env_default_model(self) -> None:
        step = ResearchChatStep()
        completion = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="Recovered explanation"), finish_reason="stop")],
            model="qwen-plus",
        )
        step._create_completion = AsyncMock(side_effect=[RuntimeError("model_not_found: gpt-3.5-turbo"), completion])

        with patch.dict(
            os.environ,
            {"OPENAI_API_KEY": "test-key", "RESEARCH_CHAT_MODEL": "qwen-plus"},
            clear=False,
        ), patch("openai.AsyncOpenAI", return_value=object()):
            result = asyncio.run(step.execute({"prompt": "Explain", "model": "gpt-3.5-turbo"}, None))

        self.assertEqual(result["content"], "Recovered explanation")
        self.assertEqual(result["model"], "qwen-plus")
        self.assertEqual(step._create_completion.await_args_list[0].args[1], "gpt-3.5-turbo")
        self.assertEqual(step._create_completion.await_args_list[1].args[1], "qwen-plus")

