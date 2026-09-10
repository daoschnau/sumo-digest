#!/usr/bin/env python3
"""Живая проверка листингов источников (этап E0).

Ходит по `listing_url` каждого включённого источника, вытаскивает ссылки,
отбирает подходящие под `link_pattern` и печатает, сколько нашлось и какие.
Единственный скрипт в проекте, которому разрешено ходить в сеть, — в CI
его не гонять: источники не любят регулярный автоматический обход.

    uv run python scripts/check_sources.py            # все включённые источники
    uv run python scripts/check_sources.py sponichi   # только один
    uv run python scripts/check_sources.py --show 10  # больше примеров ссылок

Код возврата: 0 — у всех источников найдено достаточно ссылок, 1 — есть
проблемные. Критерий готовности E0: не меньше MIN_LINKS ссылок на источник.
"""

from __future__ import annotations

import argparse
import re
import sys
import urllib.robotparser
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx
import yaml

CONFIG = Path(__file__).resolve().parent.parent / "config" / "sources.yml"
MIN_LINKS = 5  # критерий готовности E0 из ROADMAP.md


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


def normalize(url: str) -> str:
    """Убирает query и fragment — дедупликация по нормализованному URL (ТЗ §3.1)."""
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def robots_allows(url: str, user_agent: str, timeout: float) -> bool | None:
    """Advisory-проверка robots.txt. None — файл недоступен, судить не беремся."""
    parts = urlsplit(url)
    robots_url = urlunsplit((parts.scheme, parts.netloc, "/robots.txt", "", ""))
    try:
        response = httpx.get(robots_url, timeout=timeout, follow_redirects=True,
                             headers={"User-Agent": user_agent})
        if response.status_code != 200:
            return None
        parser = urllib.robotparser.RobotFileParser()
        parser.parse(response.text.splitlines())
        return parser.can_fetch(user_agent, url)
    except httpx.HTTPError:
        return None


def check(source: dict, defaults: dict, show: int) -> tuple[str, int]:
    """Возвращает (краткий статус, число найденных ссылок) и печатает отчёт."""
    name, url = source["name"], source["listing_url"]
    pattern = re.compile(source["link_pattern"])
    timeout = float(defaults.get("timeout_seconds", 15))
    user_agent = defaults.get("user_agent", "sumo-digest/1.0")

    print(f"\n=== {source['id']}  ({name}, приоритет {source['priority']})")
    print(f"    {url}")

    try:
        response = httpx.get(url, timeout=timeout, follow_redirects=True,
                             headers={"User-Agent": user_agent})
    except httpx.HTTPError as error:
        # Спецификация запрещает ретраить недоступный источник — здесь тоже не ретраим.
        print(f"    СБОЙ ЗАПРОСА: {type(error).__name__}: {error}")
        return "недоступен", 0

    print(f"    HTTP {response.status_code}, {len(response.content)} байт,"
          f" кодировка {response.encoding}")
    if response.status_code != 200:
        return f"HTTP {response.status_code}", 0

    parser = PageLinks()
    parser.feed(response.text)

    seen: dict[str, None] = {}
    for href in parser.hrefs:
        absolute = normalize(urljoin(str(response.url), href))
        if pattern.search(absolute):
            seen.setdefault(absolute, None)
    matched = list(seen)

    print(f"    ссылок на странице: {len(parser.hrefs)}, подошло под link_pattern: {len(matched)}")
    for link in matched[:show]:
        print(f"      {link}")
    if len(matched) > show:
        print(f"      … ещё {len(matched) - show}")

    if not matched:
        # Подбирать link_pattern вслепую невозможно — показываем, как ссылки
        # на этой странице выглядят на самом деле.
        host = urlsplit(str(response.url)).netloc
        samples: dict[str, None] = {}
        for href in parser.hrefs:
            absolute = normalize(urljoin(str(response.url), href))
            if urlsplit(absolute).netloc == host:
                samples.setdefault(absolute, None)
        print(f"    примеры ссылок этого хоста ({len(samples)} уникальных):")
        for link in list(samples)[:15]:
            print(f"      {link}")

    if parser.feeds:
        print("    RSS/Atom на странице:")
        for feed in dict.fromkeys(parser.feeds):
            print(f"      {urljoin(str(response.url), feed)}")
    else:
        print("    RSS/Atom: не объявлен")

    allowed = robots_allows(url, user_agent, timeout)
    verdict = {True: "разрешает", False: "ЗАПРЕЩАЕТ", None: "нет данных"}[allowed]
    print(f"    robots.txt: {verdict}")

    if not matched:
        return "0 ссылок — чинить link_pattern", 0
    if len(matched) < MIN_LINKS:
        return f"мало ссылок ({len(matched)})", len(matched)
    return "ок", len(matched)


def main() -> int:
    arguments = argparse.ArgumentParser(description="Живая проверка листингов источников")
    arguments.add_argument("sources", nargs="*", help="id источников; пусто — все включённые")
    arguments.add_argument("--show", type=int, default=5,
                           help="сколько ссылок печатать (по умолчанию 5)")
    arguments.add_argument("--dump", action="store_true",
                           help="печатать все совпавшие ссылки, а не первые --show")
    options = arguments.parse_args()

    config = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    defaults = config.get("defaults", {})
    selected = [s for s in config["sources"]
                if s.get("enabled", True)
                and (not options.sources or s["id"] in options.sources)]

    if not selected:
        print("Ни один источник не выбран.", file=sys.stderr)
        return 1

    results: list[tuple[str, str, int]] = []
    for source in sorted(selected, key=lambda s: s["priority"]):
        status, count = check(source, defaults, 10_000 if options.dump else options.show)
        results.append((source["id"], status, count))

    print("\n" + "=" * 60)
    print(f"{'источник':<16} {'ссылок':>7}  статус")
    for source_id, status, count in results:
        print(f"{source_id:<16} {count:>7}  {status}")

    failed = [source_id for source_id, status, _ in results if status != "ок"]
    if failed:
        print(f"\nТребуют внимания: {', '.join(failed)}")
        return 1
    print(f"\nВсе источники отдают не меньше {MIN_LINKS} ссылок — критерий E0 выполнен.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
