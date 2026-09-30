"""Словарь терминов: термин → определение.

Зачем он есть. Модель поясняет термин в квадратных скобках при первом
упоминании в блоке, и до 30.09.2026 писала эти пояснения заново каждый раз:
у ёрикири набралось три определения, у уватенаге — четыре, часть в косвенном
падеже («броском через руку»), часть оборвана («катасукаши — подсечк»).
Читателю, который открыл два выпуска подряд, это выглядит как разные термины.

Устройство то же, что у словаря имён: данные побеждают там, где они есть.
Рендерер берёт определение отсюда, пояснение модели идёт в дело только для
терминов, которых в словаре нет, и такой термин попадает в отчёт прогона
кандидатом. Определений модель писать не перестаёт — она видит контекст
и решает, что пояснять, — но формулировка на сайте одна на все выпуски.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

GLOSSARY_PATH = Path("data/glossary.json")


def load_glossary(path: Path = GLOSSARY_PATH) -> dict[str, str]:
    """Термин в нижнем регистре → определение. Нет файла — пустой словарь."""
    if not path.exists():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    return {term.casefold(): definition
            for term, definition in (raw.get("terms") or {}).items()}


@lru_cache(maxsize=1)
def glossary() -> dict[str, str]:
    """Словарь, прочитанный один раз за прогон."""
    return load_glossary()


def definition(term: str, known: dict[str, str] | None = None) -> str | None:
    """Определение термина из словаря. None — термина там нет."""
    return (known if known is not None else glossary()).get(term.casefold())
