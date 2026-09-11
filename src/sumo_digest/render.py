"""Шаг render: JSON выпусков → статический сайт.

Сайт пересобирается целиком из `data/issues/*.json` при каждом прогоне.
Это значит, что вёрстку можно менять, не перезапуская модель: правишь шаблон,
рендеришь заново — весь архив переезжает на новое оформление.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
from datetime import UTC, date, datetime
from html import escape
from pathlib import Path
from urllib.parse import urlsplit

from jinja2 import Environment, FileSystemLoader, select_autoescape
from markupsafe import Markup

from .translit import lint_digest
from .validate import sort_blocks

TEMPLATES = Path("templates")
ISSUES = Path("data/issues")
SITE = Path("site")

DEFAULT_BASE_URL = "https://sumodigest.online/"

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


# «Имя (漢字, romaji: Xxxx — требует проверки)» — конструкция из спецификации.
# В данных она остаётся как есть, в вёрстке от неё остаётся романизация и знак
# вопроса с подсказкой: в одном выпуске таких пометок бывает восемь, и «требует
# проверки» посреди предложения читатель спотыкается о каждую.
ROMAJI_NOTE = re.compile(r"romaji:\s*(?P<romaji>[^—)]+?)\s*—\s*требует проверки")

# «тачиай [начальный сход]» — пояснение термина. Модель ставит его при первом
# упоминании в каждом блоке (так задумано: блоки читают вразнобой и переставляет
# их код). На странице пояснения собираются в глоссарий внизу: даже приглушённые,
# в абзаце они рвут фразу, а в первом же абзаце их бывает два подряд.
GLOSS = re.compile(r"(?P<term>[^\s\[\]()]+)[  ]?\[(?P<gloss>[^\[\]]{2,80})\]")

# Термин перед скобкой может прийти с хвостом пунктуации: «тачиай, [начальный сход]».
TERM_EDGES = " ,.;:!?«»\"'—–-"

UNVERIFIED_MARK = ('<sup class="unverified" title="транслитерация требует '
                   'проверки">?</sup>')

# Скобка с японским написанием: «(豊昇龍)», «(元小結旭豊, Asahiyutaka?)».
# Кегль у иероглифа тот же, а площадку он занимает всю — рядом со строчной
# кириллицей самая служебная часть фразы выглядит самой заметной. Поэтому
# скобку приглушаем, но только эту: «(частичный разрыв)» — обычный текст.
CJK = r"぀-ヿ㐀-䶿一-鿿ｦ-ﾟ"
APPARATUS = re.compile(rf"\((?P<inside>[^()]*(?:[{CJK}]|{re.escape(UNVERIFIED_MARK)})"
                       r"[^()]*)\)")


def prose(text: str, glossary: dict[str, tuple[str, str]]) -> Markup:
    """Текст выпуска → готовый к вёрстке HTML.

    Данные не трогаем: и пометка о проверке, и пояснения терминов остаются
    в JSON и уезжают в фид. Здесь снимается только то, что мешает читать
    страницу подряд. `glossary` общий на весь выпуск: пояснения вынимаются
    из фраз в порядке появления и собираются под текстом.
    """
    marked = ROMAJI_NOTE.sub(lambda match: match.group("romaji") + UNVERIFIED_MARK,
                             str(escape(text)))
    marked = APPARATUS.sub(
        lambda match: f'<span class="aside">({match.group("inside")})</span>', marked)

    def collect(match: re.Match) -> str:
        term = match.group("term").strip(TERM_EDGES)
        if term:
            glossary.setdefault(term.casefold(), (term, match.group("gloss")))
        return match.group("term")

    return Markup(GLOSS.sub(collect, marked))


def page_view(issue: dict) -> dict:
    """Копия выпуска с подготовленным текстом. Оригинал нужен индексу и фиду."""
    glossary: dict[str, tuple[str, str]] = {}
    view = dict(issue)
    view["lead"] = prose(issue.get("lead", ""), glossary)
    view["blocks"] = []
    for block in issue.get("blocks", []):
        prepared = dict(block)
        prepared["subtitle"] = prose(block.get("subtitle", ""), glossary)
        prepared["body"] = prose(block.get("body", ""), glossary)
        view["blocks"].append(prepared)
    if issue.get("missed"):
        view["missed"] = prose(issue["missed"], glossary)
    view["glossary"] = list(glossary.values())
    return view


def has_unverified(view: dict) -> bool:
    """Есть ли на странице хоть один знак вопроса — от него зависит сноска внизу."""
    texts = [view["lead"], view.get("missed", ""),
             *(block[field] for block in view["blocks"]
               for field in ("subtitle", "body"))]
    return any(UNVERIFIED_MARK in str(text) for text in texts)


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
        view = page_view(issue)
        page = page_dir / "index.html"
        page.write_text(env.get_template("issue.html").render(
            issue=view, unavailable=unavailable, unverified=has_unverified(view)),
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

    # Собственный домен. Настройка живёт и в Settings → Pages, но site/
    # пересобирается каждый прогон, и пусть домен лежит в коде тоже.
    domain = urlsplit(base_url).netloc
    if domain and not domain.endswith("github.io"):
        (out_dir / "CNAME").write_text(domain + "\n", encoding="utf-8")
        written.append(out_dir / "CNAME")

    return written


def relint_archive(directory: Path = ISSUES) -> list[tuple[str, list, bool]]:
    """Прогоняет архив через текущие правила транслитерации и переписывает файлы.

    Заодно пересортировывает блоки текущим правилом: порядок — тоже правило,
    и менять его задним числом для архива нужно так же, как написание.

    Нужно каждый раз, когда в config/translit_rules.yml добавляется правило:
    новое написание должно доехать и до старых выпусков, а не только до будущих.
    """
    changed: list[tuple[str, list]] = []
    for path in sorted(directory.glob("*.json")):
        issue = json.loads(path.read_text(encoding="utf-8"))
        before = [block.get("subtitle") for block in issue.get("blocks", [])]
        fixed, report = lint_digest(issue)
        fixed = sort_blocks(fixed)
        reordered = [block.get("subtitle") for block in fixed.get("blocks", [])] != before
        if not report.fixes and not reordered:
            continue
        path.write_text(json.dumps(fixed, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8")
        changed.append((path.name, report.fixes, reordered))
    return changed


def main() -> int:
    arguments = argparse.ArgumentParser(description="Сборка сайта из архива выпусков")
    arguments.add_argument("--issues", type=Path, default=ISSUES)
    arguments.add_argument("--out", type=Path, default=SITE)
    arguments.add_argument("--base-url", default=os.getenv("SUMO_DIGEST_BASE_URL",
                                                           DEFAULT_BASE_URL))
    arguments.add_argument("--relint", action="store_true",
                           help="применить текущие правила транслитерации к архиву")
    options = arguments.parse_args()

    if options.relint:
        for name, fixes, reordered in relint_archive(options.issues):
            listed = [f"«{w}» → «{r}» ×{n}" for w, r, n in fixes]
            if reordered:
                listed.append("блоки переставлены")
            print(f"поправлен {name}: {', '.join(listed)}")

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
