"""Проверка выпуска до публикации. Провал — выпуск не выходит.

Уровень 1 — схема. Уровень 2 — ссылки и факты: каждая ссылка обязана быть
во входном корпусе. Ссылка, которой там нет, — выдумка модели, и это
единственная ошибка такой системы, которая по-настоящему дорого стоит:
читатель идёт проверить факт и упирается в 404.

Уровень 3 (линтер транслитерации) появится на E3.
"""

from __future__ import annotations

from jsonschema import Draft202012Validator

from .models import Corpus
from .schema import load_schema

# Порядок значимости из спецификации: макуути и дзюрё → бандзуке → травмы →
# тренировки → низшие дивизионы → прочее.
CATEGORY_RANK = {
    "makuuchi_juryo": 0,
    "banzuke": 1,
    "injury": 2,
    "training": 3,
    "lower_divisions": 4,
    "other": 5,
}

MIN_BLOCKS = 5
MAX_BLOCKS = 10


class ValidationFailed(Exception):
    """Выпуск не может быть опубликован. В аргументе — список причин."""

    def __init__(self, problems: list[str]) -> None:
        super().__init__("; ".join(problems))
        self.problems = problems


def check_schema(digest: dict) -> list[str]:
    validator = Draft202012Validator(load_schema())
    return [f"схема: {'/'.join(str(p) for p in error.path) or '(корень)'} — {error.message}"
            for error in validator.iter_errors(digest)]


def check_facts(digest: dict, corpus: Corpus) -> list[str]:
    """Уровень 2: ссылки, издания, даты, объём."""
    problems: list[str] = []
    by_url = {article.url: article for article in corpus.articles}

    for number, block in enumerate(digest.get("blocks", []), start=1):
        for source in block.get("sources", []):
            article = by_url.get(source["url"])
            if article is None:
                problems.append(
                    f"блок {number}: ссылки нет во входном корпусе — {source['url']}")
                continue
            if source["name"] != article.source_name:
                problems.append(
                    f"блок {number}: издание не то — в выпуске «{source['name']}», "
                    f"в корпусе «{article.source_name}»")

        date = block.get("date")
        if date is None:
            continue
        if not (digest["period"]["from"] <= date <= digest["period"]["to"]):
            problems.append(f"блок {number}: дата {date} вне периода выпуска")
        # Если у всех источников блока даты не было, модель не имела права
        # проставить её сама (ТЗ §3.2).
        articles = [by_url[s["url"]] for s in block.get("sources", []) if s["url"] in by_url]
        if articles and all(a.date_confidence == "low" for a in articles):
            problems.append(
                f"блок {number}: дата {date} при date_confidence=low у всех источников")

    count = len(digest.get("blocks", []))
    if not digest.get("quiet_period") and not MIN_BLOCKS <= count <= MAX_BLOCKS:
        problems.append(
            f"блоков {count}, нужно {MIN_BLOCKS}–{MAX_BLOCKS} либо quiet_period: true")

    return problems


def sort_blocks(digest: dict) -> dict:
    """Порядок блоков определяет код, а не модель.

    Модель систематически ставит первым то, о чём написала подробнее,
    а не то, что важнее.
    """
    digest["blocks"] = sorted(
        digest.get("blocks", []),
        key=lambda block: (
            CATEGORY_RANK.get(block.get("category", "other"), 9),
            -int(block.get("importance", 1)),
            block.get("date") or "",
        ),
    )
    return digest


def validate(digest: dict, corpus: Corpus) -> dict:
    """Возвращает выпуск с отсортированными блоками либо падает с причинами."""
    problems = check_schema(digest)
    if problems:
        raise ValidationFailed(problems)
    problems = check_facts(digest, corpus)
    if problems:
        raise ValidationFailed(problems)
    return sort_blocks(digest)
