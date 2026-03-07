import json
from typing import Dict, Optional

from ..schema_loader import CdmDictionary, _norm


class FieldMapper:
    def __init__(self, mapping: Dict[str, str]) -> None:
        self.mapping = { _norm(k): v for k, v in mapping.items() }

    @classmethod
    def from_file(cls, path: str) -> "FieldMapper": #load mnappings from JSON file
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return cls(mapping=data)

    def resolve(self, name: str, cdm: Optional[CdmDictionary] = None) -> str: 
        # resolve a field name or synonym to its canonical column name 
        # falls back to retuning the orignal name if no mapping found but cdm is always passed as None in engine.py
        key = _norm(name)
        if key in self.mapping:
            return self.mapping[key]

        # cdm fallback (optional, pass None to skip)
        if cdm and hasattr(cdm, "data_element_to_fields"):
            if key in cdm.data_element_to_fields:
            fields = sorted(cdm.data_element_to_fields[key])
            if len(fields) == 1:
                return fields[0]

        return name
