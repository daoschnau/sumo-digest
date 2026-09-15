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


SUMOSTOMP_DAY = "https://www.sumo-stomp.com/p/2026-aki-basho-day-3-results-and"
SUMOSTOMP_FINAL = "https://www.sumo-stomp.com/p/2025-aki-basho-final-day-results"
SUMOSTOMP_OTHER = "https://www.sumo-stomp.com/p/2026-aki-basho-predictions"


def test_sumostomp_takes_day_reports_and_nothing_else(sources_config):
    """Из этого источника берутся только отчёты о днях турнира, а не всё издание."""
    pattern = re.compile(sources(sources_config)["sumostomp"]["link_pattern"])
    assert pattern.search(SUMOSTOMP_DAY)
    assert pattern.search(SUMOSTOMP_FINAL)
    assert not pattern.search(SUMOSTOMP_OTHER)


def test_sumostomp_is_bound_to_the_tournament(sources_config):
    """Без only_during_basho источник хроники полез бы в выпуск в межсезонье."""
    source = sources(sources_config)["sumostomp"]
    assert source["only_during_basho"] is True
    assert source["day_pattern"]
    # Квота источника — дни турнира, а не статьи: период после пропущенного
    # прогона бывает длиннее общей квоты в четыре статьи.
    assert source["max_articles_per_source"] >= 4


def test_only_tournament_sources_carry_the_flag(sources_config):
    """Флаг выключает источник в межсезонье — на обычных изданиях это ошибка."""
    flagged = {s["id"] for s in sources_config["sources"] if s.get("only_during_basho")}
    assert flagged == {"sumostomp"}


def test_day_pattern_agrees_with_link_pattern(sources_config):
    """Номер дня обязан доставаться из любого адреса, прошедшего link_pattern."""
    from sumo_digest.basho import day_from_url

    source = sources(sources_config)["sumostomp"]
    for url, day in ((SUMOSTOMP_DAY, 3), (SUMOSTOMP_FINAL, 15)):
        assert re.search(source["link_pattern"], url)
        assert day_from_url(url, source["day_pattern"]) == day
