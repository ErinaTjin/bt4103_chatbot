import json
import re
from typing import Any

from json_repair import repair_json
from pydantic import ValidationError

from .llm_adapter import LLMAdapter
from .models import Agent1ContextSummary
from .agent1_prompts import SYSTEM_PROMPT, USER_PROMPT_TEMPLATE

# DEBUG
import logging
log = logging.getLogger(__name__)

class Agent1QueryPlanExtractor:
    """
    Agent 1 (Context Agent): lightweight semantic understanding only.
    """

    def __init__(self, llm: LLMAdapter | None = None) -> None:
        self.llm = llm or LLMAdapter()

    def _build_prompt(
        self,
        question: str,
        conversation_history: list[dict[str, Any] | str] | None = None,
        active_filters: dict[str, Any] | None = None,
    ) -> str:
        history_str = json.dumps(conversation_history or [], ensure_ascii=True, indent=2)
        active_filters_str = json.dumps(active_filters or {}, ensure_ascii=True, indent=2)
        return USER_PROMPT_TEMPLATE.format(
            question=question.strip(),
            history=history_str,
            active_filters=active_filters_str,
        )

    def extract(
        self,
        question: str,
        conversation_history: list[dict[str, Any] | str] | None = None,
        active_filters: dict[str, Any] | None = None,
    ) -> Agent1ContextSummary:
        # DEBUG
        log.info("Agent1 START: %s", question)
        
        prompt = self._build_prompt(question, conversation_history, active_filters)
        raw = self.llm.generate(prompt=prompt, system=SYSTEM_PROMPT)

        # DEBUG
        log.info("Agent1 raw output: %s", raw)

        try:
            return Agent1ContextSummary.model_validate_json(self._clean_json(raw))
        except (ValidationError, json.JSONDecodeError) as e:
            # DEBUG
            log.error("Agent1 parse error: %s", e)

            # First try: structurally repair the broken JSON before retrying the LLM
            try:
                repaired = repair_json(self._clean_json(raw))
                return Agent1ContextSummary.model_validate_json(repaired)
            except (ValidationError, json.JSONDecodeError, Exception) as repair_err:
                log.warning("Agent1 repair failed (%s), falling back to LLM retry", repair_err)

            retry_prompt = prompt + "\nIMPORTANT: Output ONLY valid JSON. No markdown, no extra text. Ensure all objects and arrays are properly closed."
            raw_retry = self.llm.generate(prompt=retry_prompt, system=SYSTEM_PROMPT)

            try:
                return Agent1ContextSummary.model_validate_json(self._clean_json(raw_retry))
            except (ValidationError, json.JSONDecodeError) as retry_err:
                log.error("Agent1 retry parse error: %s", retry_err)
                # Last resort: repair the retry output too
                repaired_retry = repair_json(self._clean_json(raw_retry))            

            return Agent1ContextSummary.model_validate_json(self._clean_json(repaired_retry))

    @staticmethod
    def _clean_json(text: str) -> str:
        if "```" in text:
            text = text.replace("```json", "").replace("```", "").strip()
        match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        return match.group(0).strip() if match else text.strip()
