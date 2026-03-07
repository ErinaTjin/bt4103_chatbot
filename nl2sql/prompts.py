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
  "metric": "count_patients",
  "dimensions": ["..."],
  "filters": [{{"field": "...", "op": "=|!=|>|<|>=|<=|in", "value": "..."}}],
  "sort": [{{"field": "...", "direction": "desc|asc"}}],
  "limit": 50,
  "output": {{"preferred_visualization": "bar|line|pie|table|null"}}
}}

Rules:
- Output JSON only.
- The `field` in a filter and items in `dimensions` must strictly map to one of the concepts/columns in the AVAILABLE SCHEMA METADATA.
- Set `output.preferred_visualization` if the user explicitly asks for a chart (pie, bar, etc.) or if the query intent suggests a specific visualization.
- If the question is ambiguous, set needs_clarification=true and add a short clarification_question.
- If unsupported, set intent="unsupported".
"""
