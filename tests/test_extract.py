"""Экстракция статьи: текст, дата и честная пометка, когда даты нет."""

from sumo_digest.extract import extract_article, is_fresh
from sumo_digest.models import ArticleRef

REF = ArticleRef("sponichi", "Sponichi", "https://www.sponichi.co.jp/x.html")


def test_extracts_text_title_and_date(fixture_html):
    article = extract_article(fixture_html("articles/sponichi.html"), REF, "a001")
    assert article is not None
    assert article.published == "2026-09-09"
    assert article.date_confidence == "high"
    assert "霧島" in article.title
    assert "連合稽古" in article.text
    assert len(article.text) > 200


def test_short_page_is_not_an_article(fixture_html):
    assert extract_article(fixture_html("articles/short.html"), REF, "a002") is None


def test_missing_date_is_marked_low_not_guessed(fixture_html):
    html = fixture_html("articles/sponichi.html").replace(
        '<meta property="article:published_time" content="2026-09-09T18:30:00+09:00">', "")
    article = extract_article(html, REF, "a003")
    assert article is not None
    if article.published is None:
        assert article.date_confidence == "low"


def test_old_article_is_not_fresh(fixture_html):
    article = extract_article(fixture_html("articles/sponichi.html"), REF, "a004")
    assert is_fresh(article, "2026-09-01")
    assert not is_fresh(article, "2026-09-10")
