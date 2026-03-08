SYSTEM_PROMPT = (
    "You are an NL2SQL semantic resolver. "
    "Resolve a logical QueryPlan into schema-valid canonical fields and values. "
    "Output ONLY valid JSON QueryPlan. Do NOT output SQL."
)


USER_PROMPT_TEMPLATE = """
Logical QueryPlan (JSON):
{query_plan_json}

---
AVAILABLE SCHEMA METADATA:
{schema_context}

CONSTRAINTS:
{constraints}
---

Return a JSON object matching QueryPlan schema:
{{
  "intent": "count|distribution|trend|topN|mutation_prevalence|cohort_comparison|unsupported",
  "metric": "count_patients|avg_age|percentage_patients|percentage_of_total",
  "dimensions": ["..."],
  "filters": [{{"field": "...", "op": "=|!=|>|<|>=|<=|in|like|or_like", "value": "..."}}],
  "sort": [{{"field": "...", "direction": "desc|asc"}}],
  "limit": 50,
  "output": {{"preferred_visualization": "bar|line|pie|table|null"}},
  "needs_clarification": false,
  "clarification_question": null
}}

Rules:
- Output JSON only.
- Keep user intent, but map fields/values to canonical schema terms.
- Use only fields present in the AVAILABLE SCHEMA METADATA.
- If mapping is ambiguous, set needs_clarification=true with a short question.
- Do not generate SQL.
"""

