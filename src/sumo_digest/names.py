"""Словарь имён: кандзи → русское написание.

Зачем он есть. До 30.09.2026 модель решала написание имени заново в каждом
выпуске, опираясь только на статьи этого прогона. Отсюда «Какгаяки», жившее
три выпуска, «Икутаме» вместо «Набатаме» и знак «?» у борцов макуути, чьи
иероглифы были в прошлом выпуске, но не в этом.

Чего словарь НЕ делает: не подставляет имена в текст вместо модели. Модель
по-прежнему пишет прозу целиком — подстановка требовала бы плейсхолдеров
в тексте, а это ломает и линтер, и фид, и чтение JSON глазами. Словарь
работает тремя способами, и все три — на своих местах:

1. уходит модели отдельным блоком системного промпта, чтобы написание бралось
   из списка, а не сочинялось заново;
2. даёт линтеру список канонических имён — слово, отличающееся от известного
   имени на одну-две буквы, попадает в лог как вероятная опечатка;
3. даёт рендереру кандзи по романизации: «Таканошо (romaji: Takanosho —
   требует проверки)» превращается в «Таканошо (隆の勝)», если имя в словаре.

`verified` — сверено ли написание человеком. Несверённое имя остаётся в тексте
со знаком «?»: это и есть его обещанный смысл, а не «в статьях этого выпуска
не нашлось иероглифов».
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

NAMES_PATH = Path("data/names.json")


@dataclass(frozen=True)
class Name:
    kanji: str
    ru: str
    romaji: str = ""
    role: str = "rikishi"
    verified: bool = False


def load_names(path: Path = NAMES_PATH) -> list[Name]:
    """Словарь с диска. Нет файла — пустой список, пайплайн работает как раньше."""
    if not path.exists():
        return []
    raw = json.loads(path.read_text(encoding="utf-8"))
    return [Name(kanji=kanji, ru=entry["ru"], romaji=entry.get("romaji", ""),
                 role=entry.get("role", "rikishi"), verified=bool(entry.get("verified")))
            for kanji, entry in (raw.get("names") or {}).items()]


@lru_cache(maxsize=1)
def names() -> tuple[Name, ...]:
    """Словарь, прочитанный один раз за прогон."""
    return tuple(load_names())


def by_romaji(dictionary: tuple[Name, ...] | None = None) -> dict[str, Name]:
    """Романизация в нижнем регистре → имя. Пустые романизации не попадают."""
    return {name.romaji.casefold(): name
            for name in (dictionary if dictionary is not None else names())
            if name.romaji}


def canonical_names(dictionary: tuple[Name, ...] | None = None) -> list[str]:
    """Русские написания для линтера: с ними сверяются похожие слова."""
    return [name.ru for name in (dictionary if dictionary is not None else names())]


def as_prompt(dictionary: tuple[Name, ...] | None = None) -> str:
    """Блок системного промпта. Компактно: строка на имя, без служебных полей."""
    entries = sorted(dictionary if dictionary is not None else names(),
                     key=lambda name: name.ru)
    if not entries:
        return ""
    listed = "\n".join(
        f"{name.kanji} — {name.ru}" + (f" ({name.romaji})" if name.romaji else "")
        for name in entries)
    return (
        "# Словарь имён\n\n"
        "Написание имени берётся отсюда, а не придумывается заново. Слева —\n"
        "иероглифы, справа — как это имя пишется в «Сумо-дайджесте». Если имя\n"
        "встретилось в статье и есть в списке, пиши его ровно так; иероглифы\n"
        "в скобках при первом упоминании — те же, что здесь.\n\n"
        "Имени нет в списке — транслитерируй по руководству, пометь как\n"
        "требующее подтверждения и добавь в new_terms. Список не полон\n"
        "и пополняется владельцем.\n\n"
        f"{listed}\n"
    )
