"""Разбор ссылок со страницы листинга.

Общий код для сбора корпуса и для scripts/check_sources.py — чтобы проверка
источников и боевой обход находили ровно одни и те же ссылки.
"""

from __future__ import annotations

import hashlib
import re
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit, urlunsplit

# Часть листингов отрисовывается скриптом, и в разметке нет ни одного <a> на статью:
# адреса лежат в JSON внутри страницы. Эти регулярки достают их оттуда.
# Селекторов под конкретные издания нет и не будет — только поиск URL в тексте.
ABSOLUTE_URL = re.compile(r"https?://[^\s\"'<>\\)]{8,}")
QUOTED_PATH = re.compile(r"[\"'](/[^\"'\s<>\\]{3,})[\"']")


class PageLinks(HTMLParser):
    """Собирает href всех <a> и адреса RSS/Atom из <link rel=alternate>."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.hrefs: list[str] = []
        self.feeds: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = {k: (v or "") for k, v in attrs}
        if tag == "a" and a.get("href"):
            self.hrefs.append(a["href"])
        elif tag == "link" and a.get("href"):
            if "rss" in a.get("type", "") or "atom" in a.get("type", ""):
                self.feeds.append(a["href"])


def normalize_url(url: str) -> str:
    """Убирает query и fragment: дедупликация по нормализованному адресу (ТЗ §3.1)."""
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def url_key(url: str) -> str:
    """Ключ адреса для state.seen_urls."""
    return "sha1:" + hashlib.sha1(normalize_url(url).encode("utf-8")).hexdigest()


def raw_links(html: str) -> tuple[list[str], list[str]]:
    """Все адреса страницы: из разметки и из текста. Второй список — найденные фиды."""
    parser = PageLinks()
    parser.feed(html)
    found = parser.hrefs + ABSOLUTE_URL.findall(html) + QUOTED_PATH.findall(html)
    return found, parser.feeds


def find_links(html: str, base_url: str, pattern: str,
               canonical_url: str | None = None) -> list[str]:
    """Адреса статей со страницы: подходящие под pattern, в порядке появления.

    Если задан canonical_url, он собирается из скобочных групп шаблона — так
    из перепечатки на агрегаторе получается адрес на сайте самого издания.
    """
    compiled = re.compile(pattern)
    found, _ = raw_links(html)
    links: dict[str, None] = {}
    for raw in found:
        absolute = normalize_url(urljoin(base_url, raw))
        match = compiled.search(absolute)
        if not match:
            continue
        links.setdefault(canonical_url.format(*match.groups()) if canonical_url
                         else absolute, None)
    return list(links)
