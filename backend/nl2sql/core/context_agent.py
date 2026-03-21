import json
import re
from typing import Any

from pydantic import ValidationError

from .llm_adapter import LLMAdapter
from .models import ContextResolution
from .context_prompts import SYSTEM_PROMPT, USER_PROMPT_TEMPLATE


class ContextAgent:
    """
    Context resolver for follow-up user turns.
    """

    def __init__(self, llm: LLMAdapter | None = None) -> None:
        self.llm = llm or LLMAdapter()

    def _build_prompt(
        self,
        question: str,
        conversation_history: list[dict[str, Any] | str] | None,
        active_filters: dict[str, Any] | None,
    ) -> str:
        return USER_PROMPT_TEMPLATE.format(
            question=question.strip(),
            history=json.dumps(conversation_history or [], ensure_ascii=True, indent=2),
            active_filters=json.dumps(active_filters or {}, ensure_ascii=True, indent=2),
        )

    def resolve(
        self,
        question: str,
        conversation_history: list[dict[str, Any] | str] | None = None,
        active_filters: dict[str, Any] | None = None,
    ) -> ContextResolution:
        prompt = self._build_prompt(question, conversation_history, active_filters)
        raw = self.llm.generate(prompt=prompt, system=SYSTEM_PROMPT)
        try:
            return ContextResolution.model_validate_json(self._clean_json(raw))
        except (ValidationError, json.JSONDecodeError):
            retry_prompt = prompt + "\nIMPORTANT: Output ONLY valid JSON. No markdown, no extra text."
            raw_retry = self.llm.generate(prompt=retry_prompt, system=SYSTEM_PROMPT)
            return ContextResolution.model_validate_json(self._clean_json(raw_retry))

    @staticmethod
    def _clean_json(text: str) -> str:
        if "```" in text:
            text = text.replace("```json", "").replace("```", "").strip()
        match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        return match.group(0).strip() if match else text.strip()
