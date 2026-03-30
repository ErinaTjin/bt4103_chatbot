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

    _COMPARE_PATTERN = re.compile(
        r"\b(compare|comparison|versus|vs\.?|against|difference|different)\b",
        flags=re.IGNORECASE,
    )
    _EXPLICIT_REF_PATTERN = re.compile(
        r"\b(those groups|the same groups|compare them)\b",
        flags=re.IGNORECASE,
    )
    _TEMPORAL_PATTERN = re.compile(
        r"\b(by\s+year|by\s+month|by\s+quarter|by\s+date|over\s+time|year\s+over\s+year)\b",
        flags=re.IGNORECASE,
    )
    _TEMPORAL_VS_PATTERN = re.compile(
        r"\b(19|20)\d{2}\s*(vs\.?|versus)\s*(19|20)\d{2}\b",
        flags=re.IGNORECASE,
    )
    _CATEGORICAL_GROUP_TERMS = (
        "gender",
        "sex",
        "race",
        "ethnicity",
        "age group",
        "age_group",
        "stage",
        "cohort",
        "region",
        "country",
        "icd10",
        "diagnosis",
        "measurement",
        "mutation",
    )
    _TEMPORAL_GROUP_TERMS = ("year", "month", "quarter", "date", "time")

    def _build_prompt(
        self,
        question: str,
        conversation_history: list[dict[str, Any] | str] | None,
        active_filters: dict[str, Any] | None,
    ) -> str:
        # Keep only the last 6 messages (3 turns) for context resolution, to avoid using too many unecessary tokens.
        # Agent 0 only needs recent context to resolve pronouns and ellipsis.
        recent_history = (conversation_history or [])[-6:]

        # Strip to role+content only, drop any extra fields (kind, timestamp etc.)
        # Use compact JSON (no indent) to minimise token count.
        slim_history = []
        for msg in recent_history:
            if isinstance(msg, dict):
                slim_history.append({
                    "role": msg.get("role", ""),
                    "content": str(msg.get("content", ""))[:300],  # cap each message at 300 chars
                })
            else:
                slim_history.append({"role": "unknown", "content": str(msg)[:300]})

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
            resolution = ContextResolution.model_validate_json(self._clean_json(raw))
        except (ValidationError, json.JSONDecodeError):
            retry_prompt = prompt + "\nIMPORTANT: Output ONLY valid JSON. No markdown, no extra text."
            raw_retry = self.llm.generate(prompt=retry_prompt, system=SYSTEM_PROMPT)
            resolution = ContextResolution.model_validate_json(self._clean_json(raw_retry))

        return self._apply_compare_clarification_rules(
            question=question,
            resolution=resolution,
            conversation_history=conversation_history,
        )

    def _apply_compare_clarification_rules(
        self,
        *,
        question: str,
        resolution: ContextResolution,
        conversation_history: list[dict[str, Any] | str] | None,
    ) -> ContextResolution:
        if not self._COMPARE_PATTERN.search(question):
            return resolution

        q_lower = question.lower()
        has_explicit_temporal_grouping = bool(
            self._TEMPORAL_PATTERN.search(q_lower) or self._TEMPORAL_VS_PATTERN.search(q_lower)
        )
        has_explicit_categorical_grouping = self._has_explicit_categorical_grouping(q_lower)
        has_explicit_grouping = has_explicit_temporal_grouping or has_explicit_categorical_grouping

        # Current turn explicitly provides grouping, so no inheritance is needed.
        if has_explicit_grouping:
            return resolution

        has_explicit_reference = bool(self._EXPLICIT_REF_PATTERN.search(q_lower))
        previous_group = self._extract_previous_explicit_grouping(conversation_history)

        # Only categorical group-by can be inherited, and only with explicit reference.
        if (
            has_explicit_reference
            and previous_group is not None
            and previous_group["kind"] == "categorical"
        ):
            group_term = previous_group["term"]
            if f"by {group_term}" not in resolution.standalone_question.lower():
                resolution.standalone_question = (
                    resolution.standalone_question.rstrip(" ?") + f" by {group_term}"
                )
            resolution.needs_clarification = False
            resolution.clarification_question = None
            return resolution

        resolution.needs_clarification = True
        resolution.clarification_question = (
            "Which groups should I compare? Please specify explicitly (e.g., by gender, by stage, or 2020 vs 2021)."
        )
        return resolution

    def _has_explicit_categorical_grouping(self, text: str) -> bool:
        for term in self._CATEGORICAL_GROUP_TERMS:
            if re.search(rf"\b(by|across|per)\s+{re.escape(term)}\b", text):
                return True
        return False

    def _extract_previous_explicit_grouping(
        self,
        conversation_history: list[dict[str, Any] | str] | None,
    ) -> dict[str, str] | None:
        for message in reversed(conversation_history or []):
            content = ""
            if isinstance(message, dict):
                content = str(message.get("content", ""))
            else:
                content = str(message)
            text = content.lower()

            for term in self._CATEGORICAL_GROUP_TERMS:
                if re.search(rf"\b(by|across|per)\s+{re.escape(term)}\b", text):
                    return {"kind": "categorical", "term": term}

            for term in self._TEMPORAL_GROUP_TERMS:
                if re.search(rf"\b(by|across|per)\s+{re.escape(term)}\b", text):
                    return {"kind": "temporal", "term": term}
        return None

    @staticmethod
    def _clean_json(text: str) -> str:
        if "```" in text:
            text = text.replace("```json", "").replace("```", "").strip()
        match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        return match.group(0).strip() if match else text.strip()
