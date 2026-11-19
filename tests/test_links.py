"""Разбор листингов: только адреса статей, без дублей, с канонизацией."""

from sumo_digest.links import find_links, normalize_url, url_key

DMENU = "https://sumo.sports.smt.docomo.ne.jp/news/"
HOCHI_VIA = r"topics\.smt\.docomo\.ne\.jp/article/hochi/sports/hochi-([0-9]{8}-[A-Z0-9]+)"


def test_via_pattern_returns_canonical_hochi_urls(fixture_html):
    """Механизм via: листинг-посредник, канонический адрес у издания.

    Hochi жил на нём с E0 до 13.11.2026; сам механизм остаётся в коде.
    """
    links = find_links(fixture_html("listings/dmenu.html"), DMENU, HOCHI_VIA,
                       "https://hochi.news/articles/{0}.html")
    assert links == [
        "https://hochi.news/articles/20260910-OHT1T51188.html",
        "https://hochi.news/articles/20260909-OHT1T51042.html",
    ]


def test_other_publishers_are_not_taken_as_hochi(fixture_html):
    links = find_links(fixture_html("listings/dmenu.html"), DMENU, HOCHI_VIA,
                       "https://hochi.news/articles/{0}.html")
    assert not any("sponichi" in link or "sanspo" in link for link in links)


def test_hochi_reads_its_own_tag_listing(fixture_html, sources_config):
    """С 13.11.2026 Hochi не зависит от dmenu: тот падал и тянул его за собой."""
    source = next(s for s in sources_config["sources"] if s["id"] == "hochi")
    assert "via" not in source, "листинг Hochi не должен идти через агрегатор"
    links = find_links(fixture_html("listings/hochi.html"), source["listing_url"],
                       source["link_pattern"])
    assert links == [
        "https://hochi.news/articles/20261113-OHT1T51398.html",
        "https://hochi.news/articles/20261113-OHT1T51344.html",
        "https://hochi.news/articles/20261112-OHT1T51202.html",
    ]


def test_hochi_tag_page_needs_the_sumo_filter(sources_config):
    """Боковые блоки страницы тега ведут на весь спорт — отбор по слову обязателен."""
    source = next(s for s in sources_config["sources"] if s["id"] == "hochi")
    assert "相撲" in source.get("requires_keyword", [])


def test_navigation_links_are_not_articles(fixture_html):
    pattern = r"topics\.smt\.docomo\.ne\.jp/article/[a-z]+/sports/"
    links = find_links(fixture_html("listings/dmenu.html"), DMENU, pattern)
    assert len(links) == 4  # четыре статьи, пятая ссылка — дубль первой
    assert all("/score/" not in link for link in links)


def test_normalize_drops_query_and_fragment():
    assert normalize_url("https://a.jp/x.html?utm=1#top") == "https://a.jp/x.html"
    assert url_key("https://a.jp/x.html?utm=1") == url_key("https://a.jp/x.html")


def test_substack_feed_gives_only_day_reports(fixture_html, sources_config):
    """Листингом у Sumo Stomp! служит фид: адреса в нём лежат текстом, не в <a>."""
    source = next(s for s in sources_config["sources"] if s["id"] == "sumostomp")
    links = find_links(fixture_html("listings/sumostomp.xml"),
                       source["listing_url"], source["link_pattern"])
    assert links == [
        "https://www.sumo-stomp.com/p/2026-aki-basho-day-3-results-and",
        "https://www.sumo-stomp.com/p/2026-aki-basho-day-2-results-and",
        "https://www.sumo-stomp.com/p/2026-aki-basho-day-1-results-and",
        "https://www.sumo-stomp.com/p/2026-nagoya-basho-final-day-results",
    ]


def test_comment_pages_do_not_become_day_reports(fixture_html, sources_config):
    """Проверка 15.09.2026 на живом фиде: 45 совпадений вместо пятнадцати.

    У каждого отчёта фид отдаёт ещё страницу комментариев и тот же адрес
    внутри экранированного JSON. Без закреплённого конца адреса один день
    турнира приходил бы в корпус трижды.
    """
    source = next(s for s in sources_config["sources"] if s["id"] == "sumostomp")
    links = find_links(fixture_html("listings/sumostomp.xml"),
                       source["listing_url"], source["link_pattern"])
    assert not any("/comments" in link or "quot" in link for link in links)
    assert len(links) == len(set(links))


def test_broken_address_in_page_text_is_skipped():
    """Обрывок с «[» в JSON листинга — не адрес, а не повод ронять обход (18.11.2026)."""
    html = ('<a href="https://hochi.news/articles/20261118-OHT1T51500.html">x</a>'
            '<script>{"u":"https://hochi.news]/broken[x","p":"//[::1"}</script>')
    links = find_links(html, "https://hochi.news/tag/sumo/",
                       r"hochi\.news/articles/[0-9]{8}-[A-Z0-9]+\.html")
    assert links == ["https://hochi.news/articles/20261118-OHT1T51500.html"]
