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
