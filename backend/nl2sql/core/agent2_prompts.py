SYSTEM_PROMPT = (
    "You are Agent2 (SQL Writer) in an NL2SQL pipeline. "
    "Generate a single safe read-only SQL query based on provided context. "
    "Output ONLY valid JSON."
)


USER_PROMPT_TEMPLATE = """
User original question:
{user_question}

Agent1 intent summary:
{intent_summary}

Conversation history (latest last):
{history}

Relevant schema context:
{schema_context}

Terminology mappings:
{terminology_mappings}

Business rules:
{business_rules}

SQL snippet examples:
{sql_snippets}

Safety instructions:
{safety_instructions}

Active filters:
{active_filters}

Return JSON in this shape:
{{
  "sql": "SELECT ...",
  "reasoning_summary": "optional short summary",
  "assumptions": ["optional assumptions"],
  "warnings": ["optional warnings"]
}}

Rules:
- Output JSON only.
- SQL must be a single SELECT/WITH query.
- Prefer schema/table/column names from Relevant schema context.
- Apply active filters unless they conflict with the user question.
- Keep SQL executable in DuckDB dialect.
- Do not include markdown fences.
"""
