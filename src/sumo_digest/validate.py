"""Проверка выпуска до публикации. Провал — выпуск не выходит.

Уровень 1 — схема. Уровень 2 — ссылки и факты: каждая ссылка обязана быть
во входном корпусе. Ссылка, которой там нет, — выдумка модели, и это
единственная ошибка такой системы, которая по-настоящему дорого стоит:
читатель идёт проверить факт и упирается в 404.

Уровень 3 (линтер транслитерации) появится на E3.
"""

from __future__ import annotations

from datetime import date, timedelta

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

# Статья, вышедшая сегодня, описывает вчерашнюю тренировку или позавчерашнее
# решение Ассоциации, поэтому дата события законно бывает раньше начала периода.
# Ограничение нужно только против дат из другого сезона.
DATE_SLACK_DAYS = 7


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
    by_id = {article.id: article for article in corpus.articles}
    earliest = (date.fromisoformat(digest["period"]["from"])
                - timedelta(days=DATE_SLACK_DAYS)).isoformat()

    for number, block in enumerate(digest.get("blocks", []), start=1):
        articles = []
        for article_id in block.get("source_ids", []):
            article = by_id.get(article_id)
            if article is None:
                problems.append(
                    f"блок {number}: статьи {article_id} нет во входном корпусе")
                continue
            articles.append(article)

        block_date = block.get("date")
        if block_date is None:
            continue
        if not earliest <= block_date <= digest["period"]["to"]:
            problems.append(
                f"блок {number}: дата {block_date} вне окна {earliest} — "
                f"{digest['period']['to']}")
        # Если у всех источников блока даты не было, модель не имела права
        # проставить её сама (ТЗ §3.2).
        if articles and all(a.date_confidence == "low" for a in articles):
            problems.append(
                f"блок {number}: дата {block_date} при date_confidence=low у всех источников")

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


def resolve_sources(digest: dict, corpus: Corpus) -> dict:
    """Подставляет издание и адрес по идентификаторам статей.

    Адреса в выпуск пишет код, а не модель: тогда ссылка на несуществующую
    статью невозможна не по правилу в промпте, а по устройству.
    """
    by_id = {article.id: article for article in corpus.articles}
    for block in digest.get("blocks", []):
        block["sources"] = [
            {"name": by_id[article_id].source_name, "url": by_id[article_id].url}
            for article_id in block.get("source_ids", [])
            if article_id in by_id
        ]
    return digest


def validate(digest: dict, corpus: Corpus) -> dict:
    """Возвращает выпуск с проставленными ссылками и порядком либо падает."""
    problems = check_schema(digest)
    if problems:
        raise ValidationFailed(problems)
    problems = check_facts(digest, corpus)
    if problems:
        raise ValidationFailed(problems)
    return sort_blocks(resolve_sources(digest, corpus))
