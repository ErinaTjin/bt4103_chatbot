import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from nl2sql.semantic.loader import SemanticLayerLoader
from nl2sql.core.engine import NL2SQLEngine


def main() -> None:
    semantic_dir = os.path.join(ROOT, "backend", "nl2sql", "semantic")
    sl = None
    if os.path.isdir(semantic_dir):
        sl = SemanticLayerLoader(semantic_dir).load()

    engine = NL2SQLEngine(semantic_api=sl)

    print("NCCS NL2SQL Demo (type 'exit' to quit)")
    if engine.allowed_tables:
        print(f"Loaded semantic layer: {len(engine.allowed_tables)} tables")
    else:
        print("Semantic layer not found; schema context disabled")

    while True:
        question = input("\nAsk: ").strip()
        if question.lower() in {"exit", "quit"}:
            break
        if not question:
            continue

        result = engine.translate(question)

        print("\nPlan JSON:")
        print(json.dumps(result.plan, indent=2))
        print("\nAgent1 JSON:")
        print(json.dumps(result.plan_agent1, indent=2))
        print("\nAgent2 JSON:")
        print(json.dumps(result.plan_agent2, indent=2))
        print("\nSQL:")
        print(result.sql)
        print("\nGuardrails:")
        print(json.dumps({"ok": result.valid, "warnings": result.warnings}, indent=2))


if __name__ == "__main__":
    main()
