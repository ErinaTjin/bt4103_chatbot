# loads the json files in semantic_layer/ and converts them into structured Python objects for use by the NL2SQL system, 
# especially Agent1 and Agent2 for context understanding and SQL generation. This layer abstracts away the raw JSON
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Any


@dataclass
class Column:
    name: str
    type: str
    description: str = ""


@dataclass
class Table:
    name: str
    description: str
    columns: List[Column]


@dataclass
class SemanticLayer:
    tables: Dict[str, Table]
    terminology_fields: Dict[str, List[str]]
    terminology_values: Dict[str, List[str]]
    metrics: Dict[str, Dict[str, Any]]
    joins: List[dict]


class SemanticLayerLoader:
    def __init__(self, base_dir: str | Path) -> None:
        self.base_dir = Path(base_dir)

    def load(self) -> SemanticLayer:
        schema = self._load_json("schema.json")
        terminology = self._load_json("terminology.json")
        metrics = self._load_json("metrics.json")

        tables: Dict[str, Table] = {}
        for table_name, t in schema.get("tables", {}).items():
            cols = [
                Column(
                    name=c.get("name", ""),
                    type=c.get("type", ""),
                    description=c.get("description", ""),
                )
                for c in t.get("columns", [])
            ]

            tables[table_name] = Table(
                name=table_name,
                description=t.get("description", ""),
                columns=cols,
            )

        return SemanticLayer(
            tables=tables,
            terminology_fields=terminology.get("fields", {}),
            terminology_values=terminology.get("values", {}),
            metrics=metrics,
            joins=schema.get("joins", []),
        )

    def _load_json(self, filename: str) -> dict:
        path = self.base_dir / filename
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)