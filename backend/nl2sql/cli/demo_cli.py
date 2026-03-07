import json
import os
import sys
from pathlib import Path

# Allow running this file directly: `python nl2sql/demo_cli.py`
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from nl2sql.semantic.loader import SemanticLayerLoader
from nl2sql.core.engine import NL2SQLEngine


def main() -> None:
    semantic_dir = os.path.join(ROOT, "backend", "semantic_layer") #points to where semantic layer files are expected
    sl = None
    if os.path.isdir(semantic_dir):
        sl = SemanticLayerLoader(semantic_dir).load()

    engine = NL2SQLEngine(semantic_api=sl) #creates engine

    print("NCCS NL→SQL MVP Demo (type 'exit' to quit)")
    if engine.allowed_fields:
        print(f"Loaded semantic layer: {len(engine.allowed_fields)} fields")
    else:
        print("Semantic layer not found; field validation disabled")

    while True:
        question = input("\nAsk: ").strip()
        if question.lower() in {"exit", "quit"}:
            break
        if not question:
            continue

        result = engine.translate(question) #natural language goes in, structured plan and SQL comes out

        print("\nQueryPlan JSON:")
        print(json.dumps(result.plan.model_dump(), indent=2))
        print("\nSQL:")
        print(result.sql)
        print("\nGuardrails:")
        print(json.dumps({"ok": result.valid, "warnings": result.warnings}, indent=2))


if __name__ == "__main__":
    main()
