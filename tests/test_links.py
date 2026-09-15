"""Разбор листингов: только адреса статей, без дублей, с канонизацией."""

from sumo_digest.links import find_links, normalize_url, url_key

DMENU = "https://sumo.sports.smt.docomo.ne.jp/news/"
HOCHI_VIA = r"topics\.smt\.docomo\.ne\.jp/article/hochi/sports/hochi-([0-9]{8}-[A-Z0-9]+)"


def test_via_pattern_returns_canonical_hochi_urls(fixture_html):
    """Hochi собирается из перепечаток dmenu — это решение этапа E0."""
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
