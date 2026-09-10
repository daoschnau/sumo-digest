"""Схема выпуска: полная — для валидации, урезанная — для API.

Structured outputs принимает не весь JSON Schema: ограничения длин строк,
числовые границы, размеры массивов и default он не поддерживает. Поэтому
в API уходит очищенная копия, а проверяется выпуск по полной схеме — иначе
`minLength` на «Главном» и потолок в десять блоков просто перестанут работать.
"""

from __future__ import annotations

import json
from pathlib import Path

SCHEMA_PATH = Path("schema/digest.schema.json")

# Ключи, которых structured outputs не понимает.
UNSUPPORTED = frozenset({
    "minLength", "maxLength",
    "minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum", "multipleOf",
    "minItems", "maxItems", "uniqueItems",
    "default",
})


def load_schema(path: Path = SCHEMA_PATH) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def api_schema(schema: dict) -> dict:
    """Копия схемы без неподдерживаемых ключей."""
    if isinstance(schema, dict):
        return {key: api_schema(value) for key, value in schema.items()
                if key not in UNSUPPORTED and key not in ("$schema", "$id")}
    if isinstance(schema, list):
        return [api_schema(item) for item in schema]
    return schema
