"""Сбор корпуса: бюджет, дубли, тема, robots. Сеть заменена фиктивным Fetcher."""

from datetime import date

import pytest

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


def test_robots_is_read_once_per_host_and_obeyed(monkeypatch):
    """Боевой обход обязан уважать robots.txt, а не только ручная проверка."""
    import urllib.robotparser

    from sumo_digest import collect as collect_module

    forbidding = urllib.robotparser.RobotFileParser()
    forbidding.parse(["User-agent: *", "Disallow: /news/"])
    calls: list[str] = []

    def fake_parser(url, user_agent, timeout):
        calls.append(url)
        return forbidding

    monkeypatch.setattr(collect_module, "robots_parser", fake_parser)
    fetcher = Fetcher(timeout=1, user_agent="test", delay=0)

    assert fetcher.get("https://example.test/news/a01") is None
    assert fetcher.get("https://example.test/news/a02") is None
    assert len(calls) == 1, "robots.txt читается один раз на хост"
    assert "example.test" in fetcher.blocked


def test_a_missing_robots_file_does_not_stop_the_walk(monkeypatch):
    """Нет файла — не судим: иначе первый же сбой отменит выпуск."""
    from sumo_digest import collect as collect_module

    monkeypatch.setattr(collect_module, "robots_parser",
                        lambda url, user_agent, timeout: None)
    fetcher = Fetcher(timeout=1, user_agent="test", delay=0)
    assert fetcher.allowed("https://example.test/news/a01")
    assert not fetcher.blocked


def test_a_blocked_listing_is_reported_as_blocked_not_failed(state, monkeypatch):
    """«Запрещено» и «не открылось» — разные вещи, и в выпуске это видно."""
    import urllib.robotparser

    from sumo_digest import collect as collect_module

    forbidding = urllib.robotparser.RobotFileParser()
    forbidding.parse(["User-agent: *", "Disallow: /"])
    monkeypatch.setattr(collect_module, "robots_parser",
                        lambda url, user_agent, timeout: forbidding)

    config = {"defaults": {"delay_seconds": 0}, "budget": {"max_articles": 12},
              "sources": [source("sponichi", 1, 0)]}
    corpus = collect(config, state, TODAY)
    assert [s.status for s in corpus.sources] == ["blocked"]
