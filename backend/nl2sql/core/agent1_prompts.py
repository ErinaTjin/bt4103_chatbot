SYSTEM_PROMPT = (
    "You are Agent1 (Context Agent) in an NL2SQL pipeline. "
    "Do lightweight semantic understanding only. "
    "Do not generate SQL and do not generate a complex query plan. "
    "Output ONLY valid JSON."
)

USER_PROMPT_TEMPLATE = """
Current user question:
{question}
 
Conversation history (latest last):
{history}
 
Active filters (already applied in UI):
{active_filters}
 
Return JSON in this shape:
{{
  "intent": "count|distribution|trend|topN|mutation_prevalence|cohort_comparison|unsupported",
  "intent_summary": "short plain-English summary of what SQL should answer",
  "needs_clarification": false,
  "clarification_question": null,
  "extracted_filters": [{{"field": "...", "op": "=|!=|>|<|>=|<=|in|like|or_like|between", "value": "..."}}],
  "active_filters": {{"field": "value"}}
}}
 
Rules:
- Output JSON only.
- Keep this lightweight: summarize intent and extract likely filters.
- Reuse active filters as-is in active_filters.
- Use intent='distribution' when the question asks for a breakdown using NON-TIME dimensions 'by X', 'for each X', or 'per X'. 
  e.g. 'how many patients by gender' = distribution. 
- Use intent='count' when a filter is applied to get a single number. 
  e.g. 'how many female patients have KRAS mutations' = count (female is a filter, not a grouping).
- 'What are the total deaths and their proportion?' → intent='count' (two scalar metrics, not a breakdown)"
- Use intent='count' only when a single aggregate number is expected.
- If the ask is ambiguous, set needs_clarification=true with a short clarification_question.
- Never output SQL.
- Valid operators are ONLY: =, !=, >, <, >=, <=, in, like, or_like
- NEVER use op='between' — it is not supported.
  For year or date ranges always use TWO separate filters:
  {{"field": "year", "op": ">=", "value": "2010"}},
  {{"field": "year", "op": "<=", "value": "2020"}}
 
DATA AVAILABILITY — set intent='unsupported' for any of the following:
- The question asks about a cancer type NOT in this dataset. The ONLY cancer types currently available are colorectal cancers.
  Examples that must be unsupported:
    "how many lung cancer patients" → unsupported (C34 not in dataset)
    "show breast cancer cases by year" → unsupported (C50 not in dataset)
- The question asks for data that cannot be computed from the available tables
  (e.g. 5-year survival rates, insurance claims, treatment costs, genomic sequences).
- The question requires writing, updating, or deleting data.
When intent='unsupported', set:
  intent_summary = brief explanation of why this cannot be answered
  needs_clarification = false
  clarification_question = null
  extracted_filters = []
"""
