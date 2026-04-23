import os
from typing import Any, Dict

from ..base import BaseStep


class ResearchChatStep(BaseStep):
    async def execute(self, config: Dict[str, Any], context: Any) -> Dict[str, Any]:
        prompt = str(config.get("prompt", "")).strip()
        if not prompt:
            raise ValueError("research_chat requires a non-empty prompt")

        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("research_chat requires OPENAI_API_KEY to be set")

        try:
            from openai import AsyncOpenAI
        except ImportError as exc:
            raise RuntimeError("openai is required for research_chat.") from exc

        requested_model = str(config.get("model", "")).strip()
        fallback_model = str(os.getenv("RESEARCH_CHAT_MODEL") or os.getenv("REACT_MODEL") or "gpt-4o-mini").strip()
        model = requested_model or fallback_model
        client = AsyncOpenAI(api_key=api_key, base_url=os.getenv("OPENAI_BASE_URL"))

        try:
            completion = await self._create_completion(client, model, prompt)
        except Exception as exc:
            if self._should_retry_with_fallback(exc, requested_model, fallback_model):
                completion = await self._create_completion(client, fallback_model, prompt)
                model = fallback_model
            else:
                raise RuntimeError("research_chat API call failed: {0}".format(exc)) from exc

        if not completion.choices:
            raise RuntimeError("research_chat returned no choices")

        choice = completion.choices[0]
        content = self._extract_text(choice.message.content if choice.message else "")
        if not content:
            raise RuntimeError("research_chat returned empty content")
        return {"content": content, "model": completion.model or model, "finish_reason": choice.finish_reason}

    async def _create_completion(self, client: Any, model: str, prompt: str) -> Any:
        return await client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
        )

    def _should_retry_with_fallback(self, exc: Exception, requested_model: str, fallback_model: str) -> bool:
        if not requested_model or requested_model == fallback_model:
            return False
        message = str(exc)
        return "model_not_found" in message or "does not exist" in message or "No such model" in message

    def _extract_text(self, content: Any) -> str:
        if isinstance(content, str):
            return content.strip()
        if isinstance(content, list):
            parts = []
            for item in content:
                text = getattr(item, "text", None)
                if text:
                    parts.append(str(text))
                elif isinstance(item, dict) and item.get("type") == "text":
                    parts.append(str(item.get("text", "")))
            return "".join(parts).strip()
        return ""

