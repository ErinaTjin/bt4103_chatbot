# NL2SQL Implementation Details

This project uses a two-agent NL2SQL pipeline with a lightweight context resolver in front of the SQL writer. The goal is to turn a natural-language question into a safe, executable DuckDB query against the semantic layer.

## High-Level Flow

1. The backend receives a user question, conversation history, and any active UI filters.
2. `ContextAgent` resolves the current turn into a standalone question and decides whether clarification is required.
3. `Agent1QueryPlanExtractor` converts the question into a lightweight semantic summary with intent and filter extraction.
4. `Agent2QueryPlanResolver` consumes the question, Agent 1 summary, schema context, terminology mappings, business rules, SQL snippets, and safety instructions.
5. The SQL writer returns JSON containing the SQL and short reasoning metadata.
6. The backend validates the SQL and, if valid, executes it in DuckDB.

## Core Components

### 1. Context resolution

`backend/nl2sql/core/context_agent.py` handles follow-up turns. It trims conversation history, detects whether the current question depends on prior context, and applies clarification rules for comparison-style questions. If the user says things like “compare them”, the agent can inherit a previous categorical grouping; otherwise it asks for clarification.

### 2. Agent 1: semantic extraction

`backend/nl2sql/core/agent1_extractor.py` is a lightweight interpreter. It does not generate SQL. Instead, it produces an `Agent1ContextSummary` containing:

- intent classification such as count, distribution, trend, or cohort comparison
- a short `intent_summary`
- extracted filters
- clarification flags when the question is ambiguous
- active filters reused from the UI session

This keeps the SQL writer focused on query construction rather than intent parsing.

### 3. Agent 2: SQL generation

`backend/nl2sql/core/agent2_resolver.py` builds the final prompt for the SQL writer. It passes in:

- the original user question
- the Agent 1 intent summary
- recent conversation history
- schema context generated from the semantic layer
- terminology mappings from business terms to database fields
- business rules
- SQL snippet examples
- safety instructions
- active filters

`backend/nl2sql/core/agent2_prompts.py` defines the model instructions. The SQL writer is required to return JSON only, with a single read-only `SELECT` or `WITH` query and a short reasoning summary.

## Semantic Layer Usage

`backend/nl2sql/core/engine.py` builds the schema context from the semantic layer loaded at startup. That layer provides:

- table names and descriptions
- column names, types, and descriptions
- join definitions
- terminology mappings for field names and value names

The prompt also includes EAV guidance for tables that use `measurement_concept_name` and `value_as_concept_name`, so the model learns how to filter them correctly.

## Prompt Engineering Strategy

The NL2SQL prompts are intentionally structured to reduce ambiguity and constrain the model:

- Agent 1 only does semantic interpretation and filter extraction.
- Agent 2 only writes SQL.
- The SQL prompt includes explicit business rules and example snippets.
- The output schema is JSON, which makes the response easy to validate with Pydantic.
- The SQL must be DuckDB-compatible and read-only.

This split reduces the chance that the model mixes interpretation, planning, and SQL generation in one step.

## SQL Safety and Validation

After Agent 2 returns SQL, the engine validates it before execution. The implementation enforces rules such as:

- single-statement SQL only
- no comments
- `SELECT` or `WITH` must be the first keyword
- no disallowed keywords for write operations
- explicit joins only
- `anchor_view` schema prefixing for tables

The SQL writer prompt also contains domain-specific guardrails, such as handling mortality proportions, mutation prevalence, ICD10 filtering for cancer queries, and proper handling of active filters.

## Execution Layer

`backend/app/services/nl2sql_service.py` connects the NL2SQL pipeline to the application API.

- It loads the semantic layer at startup.
- It invokes the NL2SQL engine or LangGraph pipeline if enabled.
- If SQL is valid, it executes the query through DuckDB.
- It returns the generated SQL, the plan artifacts from each agent, warnings, and result rows to the frontend.

## Optional LangGraph Mode

`backend/nl2sql/core/langgraph_pipeline.py` provides an alternative orchestration path when `USE_LANGGRAPH=true`.

In that mode, the flow is:

- context agent
- Agent 1 context extraction
- query-plan validation
- Agent 2 SQL writing
- SQL validation
- finalization

This lets the project keep the same core agents while optionally using a graph-based orchestration layer.

## Summary

The NL2SQL implementation is built around a separation of concerns:

- context resolution for follow-up questions
- semantic intent extraction
- schema-aware SQL generation
- deterministic validation before execution

That design makes the pipeline easier to debug, safer to execute, and more maintainable as the semantic layer grows.