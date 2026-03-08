import json
import re

from pydantic import ValidationError

from .llm_adapter import LLMAdapter
from .models import QueryPlan
from .agent2_prompts import SYSTEM_PROMPT, USER_PROMPT_TEMPLATE


class Agent2QueryPlanResolver:
    """
    Agent 2: schema-aware QueryPlan resolver.
    Input: logical QueryPlan + semantic schema context.
    Output: resolved QueryPlan with canonical fields/values.
    """

    def __init__(self, llm: LLMAdapter | None = None) -> None:
        self.llm = llm or LLMAdapter()

    def _build_prompt(self, plan: QueryPlan, schema_context: str, constraints: str) -> str:
        return USER_PROMPT_TEMPLATE.format(
            query_plan_json=plan.model_dump_json(indent=2),
            schema_context=schema_context.strip(),
            constraints=constraints.strip(),
        )

    def resolve(
        self,
        plan: QueryPlan,
        schema_context: str = "",
        constraints: str = "",
    ) -> QueryPlan:
        prompt = self._build_prompt(plan, schema_context, constraints)
        raw = self.llm.generate(prompt=prompt, system=SYSTEM_PROMPT)
        try:
            return QueryPlan.model_validate_json(self._clean_json(raw))
        except (ValidationError, json.JSONDecodeError):
            retry_prompt = (
                prompt
                + "\nIMPORTANT: Output ONLY valid JSON QueryPlan. No markdown or extra text."
            )
            raw_retry = self.llm.generate(prompt=retry_prompt, system=SYSTEM_PROMPT)
            return QueryPlan.model_validate_json(self._clean_json(raw_retry))

    @staticmethod
    def _clean_json(text: str) -> str:
        if "```" in text:
            text = text.replace("```json", "").replace("```", "").strip()
        match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        return match.group(0).strip() if match else text.strip()

