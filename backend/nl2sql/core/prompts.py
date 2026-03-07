#contains prompts given to the LLM
SYSTEM_PROMPT = (
    "You are a medical analytics assistant. "
    "Extract a structured QueryPlan JSON from the user's question, using only the allowed metadata from the semantic layer. "
    "Output ONLY valid JSON. Do NOT output SQL text."
)

USER_PROMPT_TEMPLATE = """
User question:
{question}

---
AVAILABLE SCHEMA MATADATA (Use ONLY these fields for dimensions and filters if they solve the user query):
{schema_context}

CONSTRAINTS (Adhere to these rules when planning the query):
{constraints}
---

Return a JSON object that matches this schema:
{{
  "intent": "count|distribution|trend|topN|mutation_prevalence|cohort_comparison|unsupported",
  "metric": "count_patients|avg_age|percentage_patients|percentage_of_total",
  "dimensions": ["..."],
  "filters": [{{"field": "...", "op": "=|!=|>|<|>=|<=|in|like|or_like", "value": "..."}}],
  "sort": [{{"field": "...", "direction": "desc|asc"}}],
  "limit": 50,
  "output": {{"preferred_visualization": "bar|line|pie|table|null"}}
}}

Rules:
- Output JSON only.
- The `field` in a filter and items in `dimensions` must strictly map to one of the concepts/columns in the AVAILABLE SCHEMA METADATA.
- For mutation prevalence questions (e.g. "what percentage of colorectal cancer cases have KRAS/BRAF/NRAS mutations") use metric='percentage_of_total' and set output.preferred_visualization='bar' to show each mutation's percentage out of ALL colorectal cancer patients.
- For general percentage questions within a group (e.g. "what percentage of patients are female") use metric='percentage_patients'.
- For mutation_prevalence queries, always include 'measurement_concept_name' in dimensions to show a breakdown per mutation type.
- When filtering for multiple values on the same field use op='in' with value as a list e.g. {{"field": "measurement_concept_name", "op": "in", "value": ["KRAS Mutation Conclusion", "BRAF Mutation Conclusion", "NRAS Mutation Conclusion"]}}. Never use op='=' when multiple values are needed.
- For partial text matches (histology type, topology, procedure type, drug names) use op='like' with value='%term%'.
- For matching multiple patterns on the same field with OR logic (e.g. colorectal cancer spanning C18, C19) use op='or_like' with value as a list e.g. ["%C18%", "%C19%"].
- For age filters, use field='year_of_birth' with a computed birth year. For example, patients under 50 in 2021 means year_of_birth >= 1971. Patients over 60 means year_of_birth <= YEAR(CURRENT_DATE) - 60.
- Set `output.preferred_visualization` if the user explicitly asks for a chart (pie, bar, etc.) or if the query intent suggests a specific visualization.
- If the question is ambiguous, set needs_clarification=true and add a short clarification_question.
- If unsupported, set intent="unsupported".
"""
