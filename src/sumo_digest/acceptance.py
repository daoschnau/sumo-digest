"""Приёмочный чек-лист §7.3 спецификации, исполняемый кодом.

Часть пунктов проверяется механически — их незачем каждый раз перечитывать
глазами. Остальные требуют человека и честно помечены как ручные: код не может
судить, есть ли в тексте патетика и не разошлись ли два источника в фактах.

    uv run python -m sumo_digest.acceptance data/issues/2026-09-10.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

import yaml

from .render import ISSUES
from .translit import lint_digest
from .validate import MAX_BLOCKS, MIN_BLOCKS, block_order

SOURCES = Path("config/sources.yml")
KANJI = re.compile(r"[㐀-鿿]")
# Хвосты рекламных концовок, которых в личной сводке быть не должно.
PROMO = re.compile(r"(подпиш[иы]|подписывайтесь|#\w|ставьте лайк|читайте нас)", re.IGNORECASE)


@dataclass
class Check:
    item: str
    passed: bool | None  # None — пункт для человека
    detail: str = ""

    def __str__(self) -> str:
        mark = {True: "[x]", False: "[!]", None: "[ ]"}[self.passed]
        tail = f" — {self.detail}" if self.detail else ""
        return f"{mark} {self.item}{tail}"


def allowed_hosts(path: Path = SOURCES) -> set[str]:
    """Хосты закрытого списка: и листингов, и канонических адресов статей."""
    config = yaml.safe_load(path.read_text(encoding="utf-8"))
    hosts: set[str] = set()
    for source in config["sources"]:
        hosts.add(urlsplit(source["listing_url"]).netloc)
        via = source.get("via") or {}
        if via.get("canonical_url"):
            hosts.add(urlsplit(via["canonical_url"]).netloc)
    return hosts


def sentences(text: str) -> int:
    return len([part for part in re.split(r"[.!?]+", text) if part.strip()])


def check_issue(issue: dict) -> list[Check]:
    checks: list[Check] = []
    blocks = issue.get("blocks", [])

    checks.append(Check("Строка периода с числом источников и пометками о недоступных",
                        bool(issue.get("sources_reviewed")),
                        f"{len(issue.get('sources_reviewed', []))} источников"))

    lead_sentences = sentences(issue.get("lead", ""))
    checks.append(Check("«Главное» — 2–3 строки",
                        2 <= lead_sentences <= 4, f"предложений: {lead_sentences}"))

    count = len(blocks)
    checks.append(Check(f"{MIN_BLOCKS}–{MAX_BLOCKS} блоков либо quiet_period",
                        MIN_BLOCKS <= count <= MAX_BLOCKS or issue.get("quiet_period"),
                        f"блоков: {count}"))

    order = [block_order(block) for block in blocks]
    checks.append(Check("Блоки отсортированы по значимости", order == sorted(order)))

    used: dict[str, int] = {}
    for block in blocks:
        for article_id in block.get("source_ids", []):
            used[article_id] = used.get(article_id, 0) + 1
    repeated = [article_id for article_id, times in used.items() if times > 1]
    checks.append(Check("Нет дублей: одна статья не растащена по разным блокам",
                        not repeated, ", ".join(repeated) if repeated else ""))

    hosts = allowed_hosts()
    outside = {urlsplit(source["url"]).netloc
               for block in blocks for source in block.get("sources", [])} - hosts
    checks.append(Check("Все ссылки ведут на издания из закрытого списка",
                        not outside, ", ".join(sorted(outside)) if outside else ""))

    with_kanji = sum(1 for block in blocks if KANJI.search(block.get("body", "")))
    checks.append(Check("Имена сопровождаются японским написанием",
                        with_kanji > 0, f"блоков с иероглифами: {with_kanji} из {count}"))

    _, report = lint_digest(json.loads(json.dumps(issue)))
    checks.append(Check("Транслитерация прошла контрольный список",
                        not report.fixes and not report.problems,
                        "; ".join([f"«{w}»→«{r}»" for w, r, _ in report.fixes]
                                  + [str(p) for p in report.problems])))

    text = " ".join([issue.get("lead", ""), issue.get("missed", "")]
                    + [b.get("body", "") + b.get("subtitle", "") for b in blocks])
    checks.append(Check("Таблицы новых имён в тексте выпуска нет",
                        "|" not in text and bool(issue.get("new_terms") is not None),
                        f"новых имён в записи выпуска: {len(issue.get('new_terms') or [])}"))
    checks.append(Check("Раздел «Мимо кассы» присутствует", bool(issue.get("missed"))))

    promo = PROMO.search(text)
    checks.append(Check("Без хэштегов и призывов подписаться",
                        not promo, promo.group(0) if promo else ""))
    exclamations = text.count("!")
    checks.append(Check("Без восклицательных знаков",
                        exclamations == 0, f"найдено: {exclamations}"))

    # Дальше — то, что код судить не может.
    checks.append(Check("Стиль: без патетики и высокопарных метафор", None, "глазами"))
    checks.append(Check("Оценки реалистичны: низшие дивизионы не равны макуути", None,
                        "глазами"))
    checks.append(Check("Противоречия источников приведены обоими вариантами", None,
                        "глазами"))
    checks.append(Check("Одна новость — один блок по смыслу, а не по ссылкам", None,
                        "глазами"))
    return checks


def main() -> int:
    arguments = argparse.ArgumentParser(description="Приёмка выпуска по чек-листу §7.3")
    arguments.add_argument("issues", nargs="*", type=Path, help="файлы data/issues/*.json")
    arguments.add_argument("--latest", action="store_true",
                           help="взять последний выпуск из архива")
    options = arguments.parse_args()

    if options.latest or not options.issues:
        archive = sorted(ISSUES.glob("*.json"))
        if not archive:
            print(f"В {ISSUES} нет выпусков.", file=sys.stderr)
            return 1
        options.issues = [archive[-1]]

    failed = 0
    for path in options.issues:
        issue = json.loads(path.read_text(encoding="utf-8"))
        print(f"\n=== {path.name} · {issue.get('issue_date')}")
        for check in check_issue(issue):
            print(f"  {check}")
            failed += check.passed is False

    print(f"\nпровалено автоматических пунктов: {failed}")
    print("пункты со скобками [ ] проверяются глазами — см. tests/acceptance.md")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
