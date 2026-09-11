"""Проверка выпуска до публикации. Провал — выпуск не выходит.

Уровень 1 — схема. Уровень 2 — ссылки и факты: каждая ссылка обязана быть
во входном корпусе. Ссылка, которой там нет, — выдумка модели, и это
единственная ошибка такой системы, которая по-настоящему дорого стоит:
читатель идёт проверить факт и упирается в 404. Уровень 3 — транслитерация.
"""

from __future__ import annotations

import re
from datetime import date, timedelta

from jsonschema import Draft202012Validator

from .models import Corpus
from .schema import load_schema
from .translit import LintReport, lint_digest

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

# jsonschema по умолчанию игнорирует "format": "date" — это задокументированное
# поведение библиотеки. Добавить "pattern" в саму схему нельзя, она же уходит
# в structured outputs, поэтому формат проверяется здесь. Без проверки кривая
# дата доживает до date.fromisoformat в сортировке и падает голым ValueError.
ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


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
        if not ISO_DATE.fullmatch(block_date):
            problems.append(
                f"блок {number}: дата «{block_date}» не в формате ГГГГ-ММ-ДД")
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


def block_order(block: dict) -> tuple[int, int, int]:
    """Ключ сортировки: значимость, потом категория, потом свежесть.

    Категории спецификации пересекаются — снятие ёкодзуны это и `injury`,
    и новость макуути, — и при сортировке по категории дебют в дзюрё оказывался
    выше снятия ёкодзуны (находка приёмки 10.09.2026). Поэтому первым идёт
    `importance`: что важнее, решает содержание, а не рубрика.
    Блоки без даты уходят вниз своей группы.
    """
    when = block.get("date")
    return (
        -int(block.get("importance", 1)),
        CATEGORY_RANK.get(block.get("category", "other"), 9),
        -date.fromisoformat(when).toordinal() if when else 0,
    )


def sort_blocks(digest: dict) -> dict:
    """Порядок блоков определяет код, а не модель.

    Модель систематически ставит первым то, о чём написала подробнее,
    а не то, что важнее.
    """
    digest["blocks"] = sorted(digest.get("blocks", []), key=block_order)
    return digest


def resolve_period(digest: dict, corpus: Corpus) -> dict:
    """Ставит период и дату выпуска из корпуса, а не из ответа модели.

    Тот же приём, что со ссылками, на поле левее. Период — проверяемое
    утверждение о работе системы, и до сих пор `check_facts` сверял даты
    блоков с границами, которые модель сама же и назвала: проверка показаний
    их же показаниями. Истину знает корпус — он и пишет.
    """
    digest["period"] = {"from": corpus.period_from, "to": corpus.period_to}
    digest["issue_date"] = corpus.period_to
    return digest


def resolve_sources_reviewed(digest: dict, corpus: Corpus) -> dict:
    """Ставит перечень просмотренных источников из результата обхода.

    Строка «просмотрено N источников; не открылись: …» — факт о прогоне,
    который читатель может проверить. Модель переписывала статусы из
    пользовательского сообщения от руки и склонна нормализовать их к `ok`.
    """
    digest["sources_reviewed"] = [
        {"name": source.name, "status": source.status,
         "articles_used": source.articles_used}
        for source in corpus.sources
    ]
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


def validate(digest: dict, corpus: Corpus) -> tuple[dict, LintReport]:
    """Три уровня подряд. Возвращает готовый выпуск и отчёт линтера.

    Порядок важен: схема — прежде чем ходить по полям, ссылки — прежде чем
    тратить время на текст, и только потом транслитерация, которая текст меняет.

    Падают только уровни 1 и 2: там ломаются факты, и такой выпуск публиковать
    нельзя. Уровень 3 возвращает замечания отчётом.
    """
    # Поля о самой системе — период, дата выпуска, перечень источников —
    # ставятся из корпуса до всех проверок. Что бы ни вернула модель, читатель
    # увидит результат обхода; заодно даты блоков сверяются с настоящими
    # границами, а не с теми, которые модель назвала сама.
    digest = resolve_sources_reviewed(resolve_period(digest, corpus), corpus)

    problems = check_schema(digest)
    if problems:
        raise ValidationFailed(problems)
    problems = check_facts(digest, corpus)
    if problems:
        raise ValidationFailed(problems)

    # Уровень 3 публикацию не останавливает: он про написание, а не про факты.
    # Что делать с оставшимися замечаниями, решает вызывающий — обычно одна
    # попытка правки текста и публикация с записью в лог.
    digest, report = lint_digest(digest)

    return sort_blocks(resolve_sources(digest, corpus)), report
