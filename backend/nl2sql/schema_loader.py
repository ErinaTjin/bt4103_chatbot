#loads CDM dictionary from CSV
import csv
from dataclasses import dataclass
from typing import Dict, Set

#normalize text by: lowercasing, trimmming, removing non-alphanumeric characters
def _norm(text: str) -> str:
    return "".join(ch for ch in text.lower().strip() if ch.isalnum())


@dataclass
class CdmDictionary:
    fields: Set[str]
    data_element_to_fields: Dict[str, Set[str]]


def load_cdm_dictionary(path: str) -> CdmDictionary:
    fields: Set[str] = set()
    data_element_to_fields: Dict[str, Set[str]] = {}

    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            field = (row.get("CDM Field") or "").strip()
            if field:
                fields.add(field)
            data_element = (row.get("Data Element") or "").strip()
            if data_element:
                key = _norm(data_element)
                data_element_to_fields.setdefault(key, set()).add(field)

    return CdmDictionary(fields=fields, data_element_to_fields=data_element_to_fields)
