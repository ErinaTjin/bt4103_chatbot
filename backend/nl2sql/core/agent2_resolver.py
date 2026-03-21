import json
import re
from typing import Any

from pydantic import ValidationError

from .llm_adapter import LLMAdapter
from .models import Agent2SQLWriterOutput
from .agent2_prompts import SYSTEM_PROMPT, USER_PROMPT_TEMPLATE

# DEBUG
import logging
log = logging.getLogger(__name__)

class Agent2QueryPlanResolver:
    """
    Agent 2 (SQL Writer): direct SQL generation from rich context.
    """

    def __init__(self, llm: LLMAdapter | None = None) -> None:
        self.llm = llm or LLMAdapter()

    def _build_prompt(
        self,
        user_question: str,
        intent_summary: str,
        schema_context: str,
        terminology_mappings: str,
        business_rules: str,
        sql_snippets: str,
        safety_instructions: str,
        conversation_history: list[dict[str, Any] | str] | None = None,
        active_filters: dict[str, Any] | None = None,
    ) -> str:
        history_str = json.dumps(conversation_history or [], ensure_ascii=True, indent=2)
        active_filters_str = json.dumps(active_filters or {}, ensure_ascii=True, indent=2)
        return USER_PROMPT_TEMPLATE.format(
            user_question=user_question.strip(),
            intent_summary=intent_summary.strip(),
            history=history_str,
            schema_context=schema_context.strip(),
            terminology_mappings=terminology_mappings.strip(),
            business_rules=business_rules.strip(),
            sql_snippets=sql_snippets.strip(),
            safety_instructions=safety_instructions.strip(),
            active_filters=active_filters_str,
        )

    def resolve(
        self,
        *,
        user_question: str,
        intent_summary: str,
        schema_context: str,
        terminology_mappings: str,
        business_rules: str,
        sql_snippets: str,
        safety_instructions: str,
        conversation_history: list[dict[str, Any] | str] | None = None,
        active_filters: dict[str, Any] | None = None,
    ) -> Agent2SQLWriterOutput:
        prompt = self._build_prompt(
            user_question=user_question,
            intent_summary=intent_summary,
            schema_context=schema_context,
            terminology_mappings=terminology_mappings,
            business_rules=business_rules,
            sql_snippets=sql_snippets,
            safety_instructions=safety_instructions,
            conversation_history=conversation_history,
            active_filters=active_filters,
        )
        raw = self.llm.generate(prompt=prompt, system=SYSTEM_PROMPT)

        # DEBUG
        log.info("Agent2 raw LLM response: %s", raw) 
        
        try:
            return Agent2SQLWriterOutput.model_validate_json(self._clean_json(raw))
        except (ValidationError, json.JSONDecodeError):
            retry_prompt = (
                prompt
                + "\nIMPORTANT: Output ONLY valid JSON with keys sql/reasoning_summary/assumptions/warnings."
            )
            raw_retry = self.llm.generate(prompt=retry_prompt, system=SYSTEM_PROMPT)
            # DEBUG 
            log.info("Agent2 retry LLM response: %s", raw_retry)
            return Agent2SQLWriterOutput.model_validate_json(self._clean_json(raw_retry))

    @staticmethod
    def _clean_json(text: str) -> str:
        if "```" in text:
            text = text.replace("```json", "").replace("```", "").strip()
        match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        return match.group(0).strip() if match else text.strip()
