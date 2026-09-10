"""Конфигурация источников: шаблоны, найденные на E0, не должны тихо разъехаться."""

import re

SUMO_ARTICLE = ("https://www.sponichi.co.jp/sports/news/2026/09/10/kiji/"
                "20260910s00005000296000c.html")
BASEBALL_ARTICLE = ("https://www.sponichi.co.jp/baseball/news/2026/09/10/kiji/"
                    "20260910s00001000123000c.html")


def sources(config):
    return {s["id"]: s for s in config["sources"]}


def test_every_pattern_compiles(sources_config):
    for source in sources_config["sources"]:
        re.compile(source["link_pattern"])
        via = source.get("via") or {}
        if via:
            re.compile(via["link_pattern"])


def test_closed_list_is_not_extended(sources_config):
    """Asahi, Nikkei и Yomiuri исключены навсегда (спецификация §8)."""
    urls = " ".join(s["listing_url"] for s in sources_config["sources"])
    for banned in ("asahi", "nikkei", "yomiuri"):
        assert banned not in urls


def test_sponichi_pattern_takes_sumo_and_skips_other_sports(sources_config):
    pattern = re.compile(sources(sources_config)["sponichi"]["link_pattern"])
    assert pattern.search(SUMO_ARTICLE)
    assert not pattern.search(BASEBALL_ARTICLE)


def test_hochi_is_reached_through_dmenu(sources_config):
    hochi = sources(sources_config)["hochi"]
    via = hochi["via"]
    match = re.search(via["link_pattern"],
                      "https://topics.smt.docomo.ne.jp/article/hochi/sports/"
                      "hochi-20260910-OHT1T51188")
    assert match
    canonical = via["canonical_url"].format(*match.groups())
    assert canonical == "https://hochi.news/articles/20260910-OHT1T51188.html"
    # Собранный адрес обязан подходить под собственный шаблон источника,
    # иначе валидатор ссылок на E2 отвергнет собственный же выпуск.
    assert re.search(hochi["link_pattern"], canonical)


def test_key_sources_stay_first_priority(sources_config):
    """Sponichi и Hochi обходятся всегда и первыми (спецификация §8)."""
    for source_id in ("sponichi", "hochi"):
        source = sources(sources_config)[source_id]
        assert source["enabled"] is True
        assert source["priority"] == 1
