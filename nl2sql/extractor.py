import json
import re

from pydantic import ValidationError

from .llm_adapter import LLMAdapter
from .models import QueryPlan
from .prompts import SYSTEM_PROMPT, USER_PROMPT_TEMPLATE


class QueryExtractor:
    def __init__(self, llm: LLMAdapter | None = None) -> None:
        self.llm = llm or LLMAdapter()

    def _build_prompt(self, question: str, schema_context: str, constraints: str) -> str:
        return USER_PROMPT_TEMPLATE.format(
            question=question.strip(),
            schema_context=schema_context.strip(),
            constraints=constraints.strip()
        )

    def extract(self, question: str, schema_context: str = "", constraints: str = "") -> QueryPlan:
        prompt = self._build_prompt(question, schema_context, constraints)
        raw = self.llm.generate(prompt=prompt, system=SYSTEM_PROMPT)
        try:
            return QueryPlan.model_validate_json(self._clean_json(raw))
        except (ValidationError, json.JSONDecodeError):
            # Retry once with a strict reminder
            retry_prompt = (
                prompt
                + "\nIMPORTANT: Output ONLY valid JSON. No markdown, no extra text."
            )
            raw_retry = self.llm.generate(prompt=retry_prompt, system=SYSTEM_PROMPT)
            return QueryPlan.model_validate_json(self._clean_json(raw_retry))

    @staticmethod
    def _clean_json(text: str) -> str:
        # Strip markdown fences if present and extract the first JSON object
        if "```" in text:
            text = text.replace("```json", "").replace("```", "").strip()
        match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        return match.group(0).strip() if match else text.strip()
