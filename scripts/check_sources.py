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
from pathlib import Path
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx
import yaml

from sumo_digest.links import ABSOLUTE_URL, QUOTED_PATH, PageLinks, normalize_url

CONFIG = Path(__file__).resolve().parent.parent / "config" / "sources.yml"
MIN_LINKS = 5  # критерий готовности E0 из ROADMAP.md

FEEDISH = re.compile(r"(rss|atom|feed|\.xml)", re.IGNORECASE)
API_LIKE = re.compile(r"(/api/|\.json|graphql|wp-json|/feed|rss)", re.IGNORECASE)


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

    def candidates(raw_links) -> dict[str, None]:
        found: dict[str, None] = {}
        for raw in raw_links:
            absolute = normalize_url(urljoin(str(response.url), raw))
            if pattern.search(absolute):
                found.setdefault(absolute, None)
        return found

    from_anchors = candidates(parser.hrefs)
    embedded = candidates(ABSOLUTE_URL.findall(response.text)
                          + QUOTED_PATH.findall(response.text))
    seen = dict(from_anchors)
    for link in embedded:
        seen.setdefault(link, None)
    matched = list(seen)
    only_embedded = len(matched) - len(from_anchors)

    note = f" (из них {only_embedded} только в тексте, не в <a>)" if only_embedded else ""
    print(f"    ссылок на странице: {len(parser.hrefs)},"
          f" подошло под link_pattern: {len(matched)}{note}")
    for link in matched[:show]:
        print(f"      {link}")
    if len(matched) > show:
        print(f"      … ещё {len(matched) - show}")

    if not matched:
        # Подбирать link_pattern вслепую невозможно — показываем, какие адреса
        # на странице есть на самом деле, сгруппированные по началу пути.
        host = urlsplit(str(response.url)).netloc
        everywhere: dict[str, None] = {}
        raw_links = (parser.hrefs
                     + ABSOLUTE_URL.findall(response.text)
                     + QUOTED_PATH.findall(response.text))
        for raw in raw_links:
            absolute = normalize_url(urljoin(str(response.url), raw))
            # Хост не фильтруем: часть изданий держит статьи на соседнем домене
            # (dmenu — на topics.smt.docomo.ne.jp), и именно он нам и нужен.
            if urlsplit(absolute).netloc:
                everywhere.setdefault(absolute, None)

        groups: dict[str, list[str]] = {}
        for link in everywhere:
            parts = urlsplit(link)
            segments = [x for x in parts.path.split("/") if x][:2]
            key = f"{parts.netloc}/{'/'.join(segments)}"
            groups.setdefault(key, []).append(link)

        print(f"    адресов на странице: {len(everywhere)};"
              f" группы по началу пути (сколько — пример):")
        for key, links in sorted(groups.items(), key=lambda kv: -len(kv[1]))[:14]:
            print(f"      {len(links):>4}  {key}")
            print(f"            {links[0]}")

        # Если список статей подгружается со стороннего хоста, он виден только здесь.
        external: dict[str, int] = {}
        api_like: dict[str, None] = {}
        for raw in raw_links:
            absolute = urljoin(str(response.url), raw)
            netloc = urlsplit(absolute).netloc
            if netloc and not netloc.endswith(host.split(".", 1)[-1]):
                external[netloc] = external.get(netloc, 0) + 1
            if API_LIKE.search(absolute):
                api_like.setdefault(normalize_url(absolute), None)

        if external:
            top = sorted(external.items(), key=lambda kv: -kv[1])[:8]
            print("    внешние хосты: " + ", ".join(f"{h} ({n})" for h, n in top))
        if api_like:
            print("    адреса, похожие на API или фид:")
            for link in list(api_like)[:8]:
                print(f"      {link}")

    if parser.feeds:
        print("    RSS/Atom на странице:")
        for feed in dict.fromkeys(parser.feeds):
            print(f"      {urljoin(str(response.url), feed)}")
    else:
        print("    RSS/Atom: не объявлен")

    feed_links = {normalize_url(urljoin(str(response.url), href)) for href in parser.hrefs
                  if FEEDISH.search(href)}
    if feed_links:
        print("    похожие на фид ссылки со страницы:")
        for link in sorted(feed_links)[:5]:
            print(f"      {link}")

    allowed = robots_allows(url, user_agent, timeout)
    verdict = {True: "разрешает", False: "ЗАПРЕЩАЕТ", None: "нет данных"}[allowed]
    print(f"    robots.txt: {verdict}")

    if not matched:
        return "0 ссылок — чинить link_pattern", 0
    if len(matched) < MIN_LINKS:
        return f"мало ссылок ({len(matched)})", len(matched)
    return "ок", len(matched)


def probe(url: str, defaults: dict) -> None:
    """Разведка одиночного адреса: жив ли он и что за ссылки на нём есть."""
    timeout = float(defaults.get("timeout_seconds", 15))
    user_agent = defaults.get("user_agent", "sumo-digest/1.0")
    print(f"\n=== разведка {url}")
    try:
        response = httpx.get(url, timeout=timeout, follow_redirects=True,
                             headers={"User-Agent": user_agent})
    except httpx.HTTPError as error:
        print(f"    СБОЙ ЗАПРОСА: {type(error).__name__}: {error}")
        return

    print(f"    HTTP {response.status_code}, {len(response.content)} байт,"
          f" итоговый адрес {response.url}")
    if response.status_code != 200:
        return

    parser = PageLinks()
    parser.feed(response.text)
    raw_links = (parser.hrefs
                 + ABSOLUTE_URL.findall(response.text)
                 + QUOTED_PATH.findall(response.text))
    groups: dict[str, list[str]] = {}
    for raw in raw_links:
        absolute = normalize_url(urljoin(str(response.url), raw))
        parts = urlsplit(absolute)
        if not parts.netloc:
            continue
        segments = [x for x in parts.path.split("/") if x][:2]
        groups.setdefault(f"{parts.netloc}/{'/'.join(segments)}", []).append(absolute)
    for key, links in sorted(groups.items(), key=lambda kv: -len(kv[1]))[:12]:
        print(f"      {len(links):>4}  {key}")
        print(f"            {links[0]}")


def main() -> int:
    arguments = argparse.ArgumentParser(description="Живая проверка листингов источников")
    arguments.add_argument("sources", nargs="*", help="id источников; пусто — все включённые")
    arguments.add_argument("--show", type=int, default=5,
                           help="сколько ссылок печатать (по умолчанию 5)")
    arguments.add_argument("--dump", action="store_true",
                           help="печатать все совпавшие ссылки, а не первые --show")
    arguments.add_argument("--probe", action="append", default=[], metavar="URL",
                           help="разведать произвольный адрес (можно несколько раз)")
    options = arguments.parse_args()

    config = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    defaults = config.get("defaults", {})

    if options.probe:
        for url in options.probe:
            probe(url, defaults)
        return 0
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
