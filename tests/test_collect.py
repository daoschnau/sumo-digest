"""Сбор корпуса: бюджет, дубли, тема, robots. Сеть заменена фиктивным Fetcher."""

from datetime import date

import pytest

from sumo_digest.basho import Basho
from sumo_digest.collect import Fetcher, collect, title_key
from sumo_digest.state import State

TODAY = date(2026, 9, 10)


def page(title: str, body: str = "本文" * 200) -> str:
    return (f'<html><head><title>{title}</title>'
            f'<meta property="article:published_time" content="2026-09-10T09:00:00+09:00">'
            f'</head><body><article><p>{body}</p></article></body></html>')


class FakeFetcher(Fetcher):
    """Ходит не в сеть, а в словарь. robots.txt считается разрешающим."""

    def __init__(self, pages: dict[str, str]) -> None:
        super().__init__(timeout=1, user_agent="test", delay=0)
        self.pages = pages
        self.visited: list[str] = []

    def get(self, url: str) -> str | None:
        self.visited.append(url)
        return self.pages.get(url)


def source(source_id: str, priority: int, links: int, **extra) -> dict:
    return {"id": source_id, "name": source_id.title(), "priority": priority,
            "enabled": True,
            "listing_url": f"https://{source_id}.test/list",
            "link_pattern": rf"https://{source_id}\.test/a\d+",
            "_links": links, **extra}


def build(sources: list[dict], pages: dict[str, str], budget: dict) -> tuple:
    listing = {}
    for src in sources:
        hrefs = "".join(f'<a href="https://{src["id"]}.test/a{n:02d}">x</a>'
                        for n in range(src.pop("_links")))
        listing[src["listing_url"]] = f"<html><body>{hrefs}</body></html>"
    fetcher = FakeFetcher({**listing, **pages})
    config = {"defaults": {"max_links_per_source": 15, "delay_seconds": 0},
              "budget": budget, "sources": sources}
    return config, fetcher


@pytest.fixture
def state() -> State:
    return State(last_issue_date="2026-09-07")


def run(config, fetcher, state, monkeypatch):
    monkeypatch.setattr("sumo_digest.collect.Fetcher", lambda **_kwargs: fetcher)
    return collect(config, state, TODAY)


def test_one_source_cannot_eat_the_whole_budget(state, monkeypatch):
    """Инвариант 3: Sponichi и Hochi обходятся всегда, а не только первый из них."""
    pages = {f"https://sponichi.test/a{n:02d}": page(f"спониси {n}") for n in range(15)}
    pages |= {f"https://hochi.test/a{n:02d}": page(f"хоти {n}") for n in range(15)}
    config, fetcher = build([source("sponichi", 1, 15), source("hochi", 2, 15)],
                            pages, {"max_articles": 8, "max_articles_per_source": 4})

    corpus = run(config, fetcher, state, monkeypatch)
    used = {s.id: s.articles_used for s in corpus.sources}
    assert used == {"sponichi": 4, "hochi": 4}


def test_a_quiet_day_still_fills_the_budget_from_one_source(state, monkeypatch):
    """Квота не должна обрезать корпус, когда брать больше неоткуда."""
    pages = {f"https://sponichi.test/a{n:02d}": page(f"спониси {n}") for n in range(15)}
    config, fetcher = build([source("sponichi", 1, 15)], pages,
                            {"max_articles": 6, "max_articles_per_source": 4})

    corpus = run(config, fetcher, state, monkeypatch)
    assert len(corpus.articles) == 6


def test_a_reprint_from_the_aggregator_does_not_become_a_second_article(state, monkeypatch):
    """dmenu перепечатывает Hochi под своим адресом: разные URL, один текст."""
    headline = "豊昇龍、秋場所を休場へ"
    pages = {"https://hochi.test/a00": page(headline),
             "https://dmenu.test/a00": page(f"【{headline}】")}
    config, fetcher = build([source("hochi", 1, 1), source("dmenu", 7, 1)],
                            pages, {"max_articles": 12, "max_articles_per_source": 4})

    corpus = run(config, fetcher, state, monkeypatch)
    assert len(corpus.articles) == 1
    assert corpus.articles[0].source_id == "hochi", "остаётся оригинал, а не перепечатка"


def test_a_source_wider_than_the_topic_is_filtered_by_keyword(state, monkeypatch):
    """Kyodo — общая лента Японии, Sankei — единоборства целиком."""
    pages = {"https://kyodo.test/a00": page("Sumo grand champion withdraws",
                                            "The yokozuna will sit out" * 40),
             "https://kyodo.test/a01": page("Cabinet approves budget",
                                            "The government said" * 40)}
    config, fetcher = build([source("kyodo", 9, 2, requires_keyword=["sumo", "相撲"])],
                            pages, {"max_articles": 12, "max_articles_per_source": 4})

    corpus = run(config, fetcher, state, monkeypatch)
    assert [a.title for a in corpus.articles] == ["Sumo grand champion withdraws"]


def test_a_source_without_the_keyword_rule_is_not_filtered(state, monkeypatch):
    pages = {"https://hochi.test/a00": page("土俵の話")}
    config, fetcher = build([source("hochi", 1, 1)], pages,
                            {"max_articles": 12, "max_articles_per_source": 4})

    corpus = run(config, fetcher, state, monkeypatch)
    assert len(corpus.articles) == 1


def test_titles_differing_only_in_punctuation_are_the_same_headline():
    assert title_key("【速報】豊昇龍、休場") == title_key("速報 豊昇龍 休場")
    assert title_key("霧島、綱取りへ") != title_key("豊昇龍、休場へ")


def forbidding_parser():
    import urllib.robotparser

    parser = urllib.robotparser.RobotFileParser()
    parser.parse(["User-agent: *", "Disallow: /"])
    return parser


def test_robots_is_read_once_per_host(monkeypatch):
    from sumo_digest import collect as collect_module

    calls: list[str] = []

    def fake_parser(url, user_agent, timeout):
        calls.append(url)
        return forbidding_parser()

    monkeypatch.setattr(collect_module, "robots_parser", fake_parser)
    fetcher = Fetcher(timeout=1, user_agent="test", delay=0)
    fetcher.check_robots("https://example.test/list")
    fetcher.check_robots("https://example.test/a01")

    assert len(calls) == 1
    assert "example.test" in fetcher.disallowed


def test_a_missing_robots_file_leaves_no_complaint(monkeypatch):
    """Нет файла — не судим: иначе первый же сбой загрузки поднимет тревогу."""
    from sumo_digest import collect as collect_module

    monkeypatch.setattr(collect_module, "robots_parser",
                        lambda url, user_agent, timeout: None)
    fetcher = Fetcher(timeout=1, user_agent="test", delay=0)
    fetcher.check_robots("https://example.test/a01")
    assert not fetcher.disallowed


def test_a_robots_ban_is_reported_but_does_not_cancel_the_issue(state, monkeypatch):
    """Молчаливый отказ по чужому файлу — это ноль вместо выпуска в четверг.

    Запрет обязан быть виден в отчёте прогона, а решение — за владельцем:
    сменить User-Agent, написать изданию или выключить источник в конфиге.
    """
    from sumo_digest import collect as collect_module

    monkeypatch.setattr(collect_module, "robots_parser",
                        lambda url, user_agent, timeout: forbidding_parser())

    pages = {"https://sponichi.test/a00": page("豊昇龍、秋場所を休場へ")}
    config, fetcher = build([source("sponichi", 1, 1)], pages,
                            {"max_articles": 12, "max_articles_per_source": 4})
    # Настоящий Fetcher, чтобы проверка robots действительно отработала.
    monkeypatch.setattr(collect_module, "Fetcher",
                        lambda **_kwargs: RealCheckFetcher(fetcher.pages))

    corpus = collect(config, state, TODAY)
    assert len(corpus.articles) == 1, "выпуск обязан собраться вопреки запрету"
    assert corpus.sources[0].status == "ok"
    assert "robots.txt" in corpus.sources[0].note


class RealCheckFetcher(Fetcher):
    """Проверку robots выполняет по-настоящему, страницы берёт из словаря."""

    def __init__(self, pages: dict[str, str]) -> None:
        super().__init__(timeout=1, user_agent="test", delay=0)
        self.pages = pages

    def get(self, url: str) -> str | None:
        self.check_robots(url)
        return self.pages.get(url)


def test_reserved_slot_lets_every_source_into_the_corpus(monkeypatch):
    """Выпуск 14.09.2026 собрался из трёх изданий: приоритетные съели бюджет."""
    from sumo_digest import collect as collect_module

    pages = {}
    sources = []
    for number in range(1, 6):
        source_id = f"s{number}"
        listing = f"https://{source_id}.test/list"
        links = [f"https://{source_id}.test/a{i}.html" for i in range(6)]
        pages[listing] = "".join(f'<a href="{url}">x</a>' for url in links)
        for index, url in enumerate(links):
            pages[url] = (f"<html><head><title>{source_id} материал {index}</title>"
                          '<meta property="article:published_time" '
                          'content="2026-09-14T10:00:00+09:00"></head><body><article>'
                          f"<h1>{source_id} материал {index}</h1><p>"
                          + ("大相撲の取組は続いている。" * 40)
                          + "</p></article></body></html>")
        sources.append({"id": source_id, "name": source_id.upper(), "priority": number,
                        "lang": "ja", "enabled": True, "listing_url": listing,
                        "link_pattern": r"/a\d\.html"})

    monkeypatch.setattr(collect_module.Fetcher, "get",
                        lambda self, url: pages.get(url))
    monkeypatch.setattr(collect_module.Fetcher, "check_robots", lambda self, url: None)

    config = {"defaults": {"max_links_per_source": 10},
              "budget": {"max_articles": 10, "max_articles_per_source": 4,
                         "min_articles_per_source": 1},
              "sources": sources}
    corpus = collect_module.collect(config, State(last_issue_date="2026-09-10"),
                                    date(2026, 9, 14))

    used = {status.id: status.articles_used for status in corpus.sources}
    assert all(count >= 1 for count in used.values()), f"источник без места: {used}"
    # Бюджета 10 на пять источников хватает на резерв каждому (5) и на добор
    # приоритетными: первый берёт полную квоту, второй — сколько осталось.
    assert used["s1"] == 4, "первый по приоритету обязан добрать свою квоту"
    assert used["s2"] > 1, "второй по приоритету должен весить больше резерва"
    assert used["s5"] == 1, "последнему остаётся ровно зарезервированное место"
    assert len(corpus.articles) == 10


def test_without_a_reserve_the_priority_sources_take_everything(monkeypatch):
    """Поведение до правки — оставлено тестом, чтобы регресс был виден."""
    from sumo_digest import collect as collect_module

    pages = {}
    sources = []
    for number in range(1, 6):
        source_id = f"s{number}"
        listing = f"https://{source_id}.test/list"
        links = [f"https://{source_id}.test/a{i}.html" for i in range(6)]
        pages[listing] = "".join(f'<a href="{url}">x</a>' for url in links)
        for index, url in enumerate(links):
            pages[url] = (f"<html><head><title>{source_id} материал {index}</title>"
                          '<meta property="article:published_time" '
                          'content="2026-09-14T10:00:00+09:00"></head><body><article>'
                          f"<h1>{source_id} материал {index}</h1><p>"
                          + ("大相撲の取組は続いている。" * 40)
                          + "</p></article></body></html>")
        sources.append({"id": source_id, "name": source_id.upper(), "priority": number,
                        "lang": "ja", "enabled": True, "listing_url": listing,
                        "link_pattern": r"/a\d\.html"})

    monkeypatch.setattr(collect_module.Fetcher, "get", lambda self, url: pages.get(url))
    monkeypatch.setattr(collect_module.Fetcher, "check_robots", lambda self, url: None)

    config = {"defaults": {"max_links_per_source": 10},
              "budget": {"max_articles": 8, "max_articles_per_source": 4,
                         "min_articles_per_source": 0},
              "sources": sources}
    corpus = collect_module.collect(config, State(last_issue_date="2026-09-10"),
                                    date(2026, 9, 14))
    used = {status.id: status.articles_used for status in corpus.sources}
    assert used["s3"] == 0, "без резерва третий источник не должен попасть"


# --- источник только на время турнира ---------------------------------------

# Турнир взят прошедший (Нагоя Басё 2026), и это не случайность: trafilatura
# не принимает дату публикации из будущего и подменяет её своей, поэтому
# фикстуры с датами «завтра» разваливаются в зависимости от дня прогона.
NAGOYA = [Basho(id="2026-nagoya", name="Нагоя Басё", place="Нагоя, IG Arena",
                start="2026-07-12", end="2026-07-26")]
STOMP_DAY_PATTERN = r"basho-(?:day-(?P<day>\d{1,2})|(?P<final>final-day))-results"


def report_page(day: int) -> str:
    """Страница отчёта о дне: дата публикации — вечер того же дня турнира."""
    published = date(2026, 7, 11 + day).isoformat()
    return (f'<html><head><title>2026 Nagoya Basho: Day {day} results and analysis</title>'
            f'<meta property="article:published_time" content="{published}T22:00:00+09:00">'
            f'</head><body><article><p>'
            # Текст у каждого дня свой: одинаковые абзацы trafilatura считает
            # шаблоном страницы и выбрасывает.
            + (f"On day {day} Onosato beat Hoshoryu by oshidashi. " * 40)
            + '</p></article></body></html>')


def stomp_pages(days: range) -> tuple[dict, dict]:
    """Фид издания и страницы отчётов по дням — по форме адресов настоящих."""
    urls = [f"https://stomp.test/p/2026-nagoya-basho-day-{day}-results-and" for day in days]
    # Фид отдаёт адреса текстом, а не в <a>, и от новых к старым: разбор ссылок
    # у нас общий и ищет адреса в тексте страницы.
    listing = "".join(f"<link>{url}</link>" for url in reversed(urls))
    pages = {"https://stomp.test/feed": f"<rss><channel>{listing}</channel></rss>"}
    for day, url in zip(days, urls, strict=True):
        pages[url] = report_page(day)
    return pages, {
        "id": "stomp", "name": "Sumo Stomp!", "priority": 2, "enabled": True,
        "only_during_basho": True,
        "listing_url": "https://stomp.test/feed",
        "link_pattern": r"stomp\.test/p/\d{4}-[a-z]+-basho-(?:day-\d{1,2}|final-day)-results",
        "day_pattern": STOMP_DAY_PATTERN,
    }


def tournament_config(stomp: dict, pages: dict, budget: dict) -> tuple:
    """Обычный источник плюс источник хроники: так и выглядит боевой конфиг."""
    hochi = source("hochi", 1, 2)
    listing = "".join(f'<a href="https://hochi.test/a{n:02d}">x</a>'
                      for n in range(hochi.pop("_links")))
    hochi_pages = {f"https://hochi.test/a{n:02d}": page(f"ほうち {n}").replace(
        "2026-09-10T09:00:00+09:00", "2026-07-13T09:00:00+09:00") for n in range(2)}
    fetcher = FakeFetcher({hochi["listing_url"]: f"<html><body>{listing}</body></html>",
                           **hochi_pages, **pages})
    config = {"defaults": {"max_links_per_source": 15, "delay_seconds": 0},
              "budget": budget, "sources": [hochi, stomp]}
    return config, fetcher


def tournament_run(stomp: dict, pages: dict, budget: dict, monkeypatch,
                   since: str, today: date, calendar: list[Basho] | None = None):
    config, fetcher = tournament_config(stomp, pages, budget)
    monkeypatch.setattr("sumo_digest.collect.Fetcher", lambda **_kwargs: fetcher)
    corpus = collect(config, State(last_issue_date=since), today,
                     NAGOYA if calendar is None else calendar)
    return corpus, fetcher


BUDGET = {"max_articles": 12, "max_articles_per_source": 4, "min_articles_per_source": 1}


def test_the_tournament_source_is_skipped_between_tournaments(monkeypatch):
    """В межсезонье оттуда брать нечего: единица материала — день басё."""
    pages, stomp = stomp_pages(range(1, 4))
    corpus, fetcher = tournament_run(stomp, pages, BUDGET, monkeypatch,
                                     "2026-08-03", date(2026, 8, 7))

    assert corpus.basho is None
    assert not any(article.source_id == "stomp" for article in corpus.articles)
    # Источник, к которому не ходили, не попадает и в строку периода: «просмотрено
    # N источников» — проверяемое утверждение о прогоне, а не округление.
    assert [status.id for status in corpus.sources] == ["hochi"]
    assert "https://stomp.test/feed" not in fetcher.visited


def test_during_the_tournament_days_come_with_their_reports(monkeypatch):
    pages, stomp = stomp_pages(range(1, 4))
    corpus, _ = tournament_run(stomp, pages, BUDGET, monkeypatch,
                               "2026-07-12", date(2026, 7, 14))

    assert corpus.basho is not None
    assert corpus.basho.name == "Нагоя Басё"
    # Номер дня — из адреса статьи, а не из текста и не от модели.
    reported = {day.day: day.article_id for day in corpus.basho.reported_days}
    urls = {article.id: article.url for article in corpus.articles}
    assert set(reported) == {1, 2, 3}
    assert "day-3-results" in urls[reported[3]]


def test_a_day_without_a_report_stays_visible_and_empty(monkeypatch):
    """Отчёт о дне выходит вечером: день периода без отчёта — нормальное дело."""
    pages, stomp = stomp_pages(range(1, 3))
    corpus, _ = tournament_run(stomp, pages, BUDGET, monkeypatch,
                               "2026-07-12", date(2026, 7, 14))

    days = {day.day: day.article_id for day in corpus.basho.days}
    assert set(days) == {1, 2, 3}
    assert days[1] and days[2], "о первых двух днях отчёты есть"
    assert days[3] is None, "третий день в списке есть, отчёта о нём нет"


def test_the_chronicle_is_not_cut_by_the_common_per_source_quota(monkeypatch):
    """Шесть дней турнира — шесть отчётов, а общая квота на источник — четыре."""
    pages, stomp = stomp_pages(range(1, 7))
    stomp["max_articles_per_source"] = 6
    corpus, _ = tournament_run(stomp, pages, BUDGET, monkeypatch,
                               "2026-07-12", date(2026, 7, 17))

    used = {status.id: status.articles_used for status in corpus.sources}
    assert used["stomp"] == 6
    assert used["hochi"] == 2, "своя квота источника не отбирает место у остальных"


def test_a_source_without_its_own_quota_keeps_the_common_one(state, monkeypatch):
    """Правка квоты не должна тихо снять потолок с обычных источников."""
    pages = {f"https://sponichi.test/a{n:02d}": page(f"спониси {n}") for n in range(15)}
    pages |= {f"https://hochi.test/a{n:02d}": page(f"хоти {n}") for n in range(15)}
    config, fetcher = build([source("sponichi", 1, 15), source("hochi", 2, 15)],
                            pages, {"max_articles": 8, "max_articles_per_source": 4})

    corpus = run(config, fetcher, state, monkeypatch)
    assert {s.id: s.articles_used for s in corpus.sources} == {"sponichi": 4, "hochi": 4}


def test_the_chronicle_survives_a_full_field_of_sources(monkeypatch):
    """Боевой конфиг: девять японских изданий плюс хроника, бюджет 18 статей.

    Без своей квоты с первого прохода хроника получала одно место из бюджета:
    приоритетные источники добирали свою квоту вторым проходом и выбирали
    остаток раньше, чем очередь доходила до второго дня турнира.
    """
    pages, stomp = stomp_pages(range(1, 5))
    stomp["max_articles_per_source"] = 6
    sources = [stomp]
    for number in range(1, 10):
        source_id = f"jp{number}"
        listing = f"https://{source_id}.test/list"
        urls = [f"https://{source_id}.test/a{i}.html" for i in range(6)]
        pages[listing] = "".join(f'<a href="{url}">x</a>' for url in urls)
        for index, url in enumerate(urls):
            pages[url] = (f'<html><head><title>{source_id} материал {index}</title>'
                          '<meta property="article:published_time" '
                          'content="2026-07-14T10:00:00+09:00"></head><body><article><p>'
                          + (f"{source_id} の取組 {index} は続いている。" * 40)
                          + '</p></article></body></html>')
        sources.append({"id": source_id, "name": source_id.upper(),
                        "priority": 1 if number < 3 else 3, "enabled": True,
                        "listing_url": listing, "link_pattern": r"/a\d\.html"})

    fetcher = FakeFetcher(pages)
    monkeypatch.setattr("sumo_digest.collect.Fetcher", lambda **_kwargs: fetcher)
    config = {"defaults": {"max_links_per_source": 15, "delay_seconds": 0},
              "budget": {"max_articles": 18, "max_articles_per_source": 4,
                         "min_articles_per_source": 1},
              "sources": sources}

    corpus = collect(config, State(last_issue_date="2026-07-12"), date(2026, 7, 15),
                     NAGOYA)

    used = {status.id: status.articles_used for status in corpus.sources}
    assert used["stomp"] == 4, f"хроника обрезана: {used}"
    assert [day.day for day in corpus.basho.reported_days] == [1, 2, 3, 4]
    # Ключевые источники по инварианту 3 всё равно весят больше остальных.
    assert used["jp1"] >= 3 and used["jp2"] >= 3, used
    assert all(count >= 1 for count in used.values()), f"источник без места: {used}"
