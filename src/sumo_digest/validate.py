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
# тренировки → низшие дивизионы → прочее. Турнирные рубрики стоят перед ними:
# две недели из шести турнир и есть новость, и внутри одной значимости главная
# схватка периода читается раньше хроники дней, а хроника — раньше прочего.
CATEGORY_RANK = {
    "basho_bout": 0,
    "basho_day": 1,
    "makuuchi_juryo": 2,
    "banzuke": 3,
    "injury": 4,
    "training": 5,
    "lower_divisions": 6,
    "other": 7,
}

# Рубрики, существующие только на время басё. Между турнирами их в выпуске быть
# не может: источник хроники в межсезонье не обходится вовсе.
BASHO_CATEGORIES = frozenset({"basho_bout", "basho_day"})

# Дни турнира читаются по возрастанию: третий день перед шестым. Для остальных
# блоков первее свежесть — это сводка новостей, а не хроника.
CHRONOLOGICAL = frozenset({"basho_day"})

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


# Утверждения о полноте картины: «единственный», «не осталось», «никто больше».
# Судить их код не может — в корпусе японский текст, в выпуске русский, — но
# найти и назвать может, и это не мелочь. В выпуске 17.09.2026 модель написала
# «единственный чистый счёт в дзюрё после пяти дней у Кагаяки», имея в корпусе
# одну заметку о его пятой победе: из «есть статья про одного» вывела «такой
# один». На самом деле с 5-0 шли четверо. Корпус — не сводка всех результатов,
# а те статьи, которые удалось собрать, и раздел про дзюрё у Sumo Stomp закрыт
# подпиской, то есть молчание корпуса тут не значило ровно ничего.
#
# Правило в промпте (правило 3 в prompts/write.md) снижает частоту таких фраз,
# но не убирает их — как и с транслитерацией. Поэтому они попадают в отчёт
# прогона и в приёмку: не запрет, а место, куда смотреть.
COMPLETENESS_CLAIM = re.compile(
    r"единственн\w*|единолич\w*|(?:больше )?ни у кого(?: больше)?|"
    r"не осталось|никто|остался один|осталась одна",
    re.IGNORECASE)


def claims(text: str) -> list[str]:
    """Фразы об исключительности, найденные в тексте. Порядок — как в тексте."""
    return [match.group(0) for match in COMPLETENESS_CLAIM.finditer(text or "")]


def check_completeness_claims(digest: dict) -> list[str]:
    """Замечания об утверждениях полноты. Публикацию не останавливают.

    Отказать тут нельзя: «единственный» бывает и законным — если так сказано
    в источнике. Проверить это способен только человек, открыв ссылку; код
    называет, что и где искать.
    """
    notes: list[str] = []
    for found, where in ((claims(digest.get("lead", "")), "lead"),
                         (claims(digest.get("missed", "")), "missed")):
        if found:
            notes.append(f"{where}: утверждение о полноте — «{'», «'.join(found)}»")
    for number, block in enumerate(digest.get("blocks", []), start=1):
        found = claims(f"{block.get('subtitle', '')} {block.get('body', '')}")
        if found:
            notes.append(f"блок {number}: утверждение о полноте — "
                         f"«{'», «'.join(found)}»; сверить с источником")
    return notes


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


def check_tournament(digest: dict, corpus: Corpus) -> list[str]:
    """Замечания о турнирной части выпуска. Публикацию не останавливают.

    Отказать здесь было бы неверно: ни одно из этих замечаний не делает выпуск
    ложным. Выпуск, в котором модель забыла блок о главной схватке, лучше, чем
    ноль вместо выпуска, — та же политика, что с транслитерацией. Но видеть
    их нужно: по ним и станет понятно, что промпт разъезжается.
    """
    notes: list[str] = []
    categories = [block.get("category") for block in digest.get("blocks", [])]

    if corpus.basho is None:
        stray = sorted({c for c in categories if c in BASHO_CATEGORIES})
        if stray:
            notes.append(f"турнира в периоде нет, а блоки с рубриками "
                         f"{', '.join(stray)} в выпуске есть")
        return notes

    cited = {article_id for block in digest.get("blocks", [])
             if block.get("category") == "basho_day"
             for article_id in block.get("source_ids", [])}
    missing = [day for day in corpus.basho.reported_days if day.article_id not in cited]
    if missing:
        notes.append("дни турнира с отчётом в корпусе, но без блока: "
                     + "; ".join(f"день {day.day} ({day.article_id})" for day in missing))

    bouts = categories.count("basho_bout")
    if bouts != 1:
        notes.append(f"блоков о главной схватке периода {bouts}, нужен ровно один")

    return notes


def block_order(block: dict) -> tuple[int, int, int]:
    """Ключ сортировки: значимость, потом категория, потом свежесть.

    Категории спецификации пересекаются — снятие ёкодзуны это и `injury`,
    и новость макуути, — и при сортировке по категории дебют в дзюрё оказывался
    выше снятия ёкодзуны (находка приёмки 10.09.2026). Поэтому первым идёт
    `importance`: что важнее, решает содержание, а не рубрика.
    Блоки без даты уходят вниз своей группы.

    Исключение — хроника дней турнира: она читается по возрастанию, потому что
    это последовательность, а не лента. Третий день перед шестым, а не наоборот.
    """
    when = block.get("date")
    category = block.get("category", "other")
    try:
        ordinal = date.fromisoformat(when).toordinal() if when else 0
    except (TypeError, ValueError):
        # Сортировка идёт до проверки схемы, поэтому дата здесь бывает любой.
        # Кривую дату всё равно поймает check_facts; ронять сортировку голым
        # ValueError незачем — блок просто уходит вниз своей группы.
        ordinal = 0
    if not ordinal:
        # Дня турнира без даты быть не должно, но если он такой пришёл — вниз
        # своей группы, как и все остальные блоки без даты.
        freshness = date.max.toordinal() if category in CHRONOLOGICAL else 0
    else:
        freshness = ordinal if category in CHRONOLOGICAL else -ordinal
    return (
        -int(block.get("importance", 1)),
        CATEGORY_RANK.get(category, 9),
        freshness,
    )


def trim_blocks(digest: dict) -> tuple[dict, list[dict]]:
    """Отсортировать и срезать хвост, если блоков больше потолка.

    Потолок в схеме есть, а модель его не видит: structured outputs не
    принимает maxItems, и в API уходит копия схемы без него. На корпусе в
    восемнадцать статей модель написала двенадцать блоков, и выпуск упал на
    проверке схемы — то есть из-за количества, а не из-за фактов.

    Количество — не факт, и терять из-за него весь выпуск нельзя. Порядок
    блоков всё равно определяет код (инвариант 5), так что и решение, какие
    блоки лишние, принадлежит коду: после сортировки лишним оказывается
    наименее значимое. Возвращаются выпуск и отброшенные блоки.
    """
    blocks = sorted(digest.get("blocks", []), key=block_order)
    digest["blocks"], dropped = blocks[:MAX_BLOCKS], blocks[MAX_BLOCKS:]
    return digest, dropped


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

    # До проверки схемы: потолок блоков модели не виден (см. trim_blocks),
    # и перебор не должен доходить до жёсткого отказа.
    digest, dropped = trim_blocks(digest)

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
    # Турнирная часть — тоже замечания, а не отказ: см. check_tournament.
    report.warnings.extend(check_tournament(digest, corpus))
    # И утверждения о полноте: их проверяет человек по ссылке, но найти их
    # обязан код, иначе они находятся так, как 17.09.2026 — из готового выпуска.
    report.warnings.extend(check_completeness_claims(digest))
    if dropped:
        report.warnings.append(
            f"блоков было {len(digest['blocks']) + len(dropped)}, оставлено "
            f"{MAX_BLOCKS}; отброшено по значимости: "
            + "; ".join(block.get("subtitle", "(без подзаголовка)") for block in dropped))

    return sort_blocks(resolve_sources(digest, corpus)), report
