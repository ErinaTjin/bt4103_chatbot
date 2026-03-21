from pathlib import Path

from nl2sql.semantic.loader import SemanticLayerLoader
from nl2sql.core.engine import NL2SQLEngine

semantic = SemanticLayerLoader(Path("backend/nl2sql/semantic")).load()
engine = NL2SQLEngine(semantic_api=semantic)

result = engine.translate("count patients by gender")

print("=== VALID ===")
print(result.valid)

print("\n=== PLAN ===")
print(result.plan)

print("\n=== AGENT1 ===")
print(result.plan_agent1)

print("\n=== AGENT2 ===")
print(result.plan_agent2)

print("\n=== SQL ===")
print(result.sql)

print("\n=== WARNINGS ===")
print(result.warnings)
