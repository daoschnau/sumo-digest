"""Шаг render: JSON выпусков → статический сайт.

Сайт пересобирается целиком из `data/issues/*.json` при каждом прогоне.
Это значит, что вёрстку можно менять, не перезапуская модель: правишь шаблон,
рендеришь заново — весь архив переезжает на новое оформление.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
from datetime import UTC, date, datetime
from html import escape
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

TEMPLATES = Path("templates")
ISSUES = Path("data/issues")
SITE = Path("site")

DEFAULT_BASE_URL = "https://daoschnau.github.io/sumo-digest/"

MONTHS = ("января", "февраля", "марта", "апреля", "мая", "июня",
          "июля", "августа", "сентября", "октября", "ноября", "декабря")


def day(value: str) -> str:
    """2026-09-10 → «10 сентября 2026»."""
    parsed = date.fromisoformat(value)
    return f"{parsed.day} {MONTHS[parsed.month - 1]} {parsed.year}"


def stamp(value: str) -> str:
    """Дата выпуска → метка времени для Atom (RFC 3339)."""
    parsed = date.fromisoformat(value)
    return datetime(parsed.year, parsed.month, parsed.day,
                    tzinfo=UTC).isoformat().replace("+00:00", "Z")


def content(issue: dict) -> str:
    """Текст выпуска для <content> в фиде: полный, а не тизер."""
    parts = [f"<p>{escape(issue['lead'])}</p>"]
    for block in issue.get("blocks", []):
        parts.append(f"<h3>{escape(block['subtitle'])}</h3>")
        parts.append(f"<p>{escape(block['body'])}</p>")
        links = ", ".join(
            f'<a href="{escape(source["url"])}">{escape(source["name"])}</a>'
            for source in block.get("sources", []))
        if links:
            parts.append(f"<p>Источники: {links}</p>")
    if issue.get("missed"):
        parts.append(f"<p>Мимо кассы: {escape(issue['missed'])}</p>")
    return "".join(parts)


def environment() -> Environment:
    env = Environment(loader=FileSystemLoader(TEMPLATES),
                      autoescape=select_autoescape(["html", "xml"]),
                      trim_blocks=True, lstrip_blocks=True)
    env.filters["day"] = day
    env.filters["stamp"] = stamp
    env.filters["content"] = content
    return env


def load_issues(directory: Path = ISSUES) -> list[dict]:
    """Все выпуски архива, от новых к старым."""
    if not directory.exists():
        return []
    issues = [json.loads(path.read_text(encoding="utf-8"))
              for path in sorted(directory.glob("*.json"))]
    return sorted(issues, key=lambda issue: issue["issue_date"], reverse=True)


def render_site(issues: list[dict], out_dir: Path = SITE,
                base_url: str = DEFAULT_BASE_URL) -> list[Path]:
    """Собирает индекс, страницы выпусков и фид. Возвращает записанные файлы."""
    env = environment()
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    for issue in issues:
        page_dir = out_dir / issue["issue_date"]
        page_dir.mkdir(parents=True, exist_ok=True)
        unavailable = [source["name"] for source in issue.get("sources_reviewed", [])
                       if source.get("status") == "failed"]
        page = page_dir / "index.html"
        page.write_text(env.get_template("issue.html").render(issue=issue,
                                                              unavailable=unavailable),
                        encoding="utf-8")
        written.append(page)

    updated = issues[0]["issue_date"] if issues else date.today().isoformat()

    index = out_dir / "index.html"
    index.write_text(env.get_template("index.html").render(issues=issues, updated=updated),
                     encoding="utf-8")
    written.append(index)

    feed = out_dir / "feed.xml"
    feed.write_text(env.get_template("atom.xml").render(
        issues=issues, base_url=base_url, updated=stamp(updated)), encoding="utf-8")
    written.append(feed)

    style = out_dir / "style.css"
    shutil.copyfile(TEMPLATES / "style.css", style)
    written.append(style)

    # Иначе GitHub Pages прогонит сайт через Jekyll и выбросит всё,
    # что начинается с подчёркивания.
    (out_dir / ".nojekyll").write_text("", encoding="utf-8")

    return written


def main() -> int:
    arguments = argparse.ArgumentParser(description="Сборка сайта из архива выпусков")
    arguments.add_argument("--issues", type=Path, default=ISSUES)
    arguments.add_argument("--out", type=Path, default=SITE)
    arguments.add_argument("--base-url", default=os.getenv("SUMO_DIGEST_BASE_URL",
                                                           DEFAULT_BASE_URL))
    options = arguments.parse_args()

    issues = load_issues(options.issues)
    if not issues:
        print(f"В {options.issues} нет ни одного выпуска — рендерить нечего.")
        return 1

    written = render_site(issues, options.out, options.base_url)
    print(f"выпусков в архиве: {len(issues)}")
    for path in written:
        print(f"  {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
