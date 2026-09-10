"""Полный прогон: от обхода источников до готового сайта.

Семь шагов подряд, читаемых сверху вниз. Никаких плагинов и оркестраторов:
если поведение нужно изменить, оно меняется в том шаге, где живёт.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from datetime import date
from pathlib import Path

import yaml

from .collect import CONFIG_PATH, collect
from .llm import DEFAULT_MODEL, repair_transliteration, write_digest
from .models import Corpus
from .render import ISSUES, SITE, load_issues, render_site
from .state import State
from .validate import ValidationFailed, validate

BUILD = Path("build")
NEW_TERMS = Path("data/new_terms.csv")
NEW_TERMS_HEADER = ("original", "romaji", "russian", "issue_date", "status")


def save_corpus(corpus: Corpus) -> None:
    """Полный корпус — для шага write, опись — для артефактов и логов."""
    BUILD.mkdir(parents=True, exist_ok=True)
    (BUILD / "corpus.json").write_text(
        json.dumps(corpus.as_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (BUILD / "corpus.meta.json").write_text(
        json.dumps(corpus.as_meta_dict(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")


def append_new_terms(digest: dict, path: Path = NEW_TERMS) -> int:
    """Дописывает новые имена в накопитель, не повторяя уже записанные.

    В текст выпуска эта таблица не попадает — только сюда, для ручной проверки
    и переноса в руководство (§5 спецификации).
    """
    terms = digest.get("new_terms") or []
    if not terms:
        return 0

    known: set[str] = set()
    if path.exists():
        with path.open(encoding="utf-8", newline="") as handle:
            known = {row["original"] for row in csv.DictReader(handle)}

    added = 0
    with path.open("a", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=NEW_TERMS_HEADER)
        for term in terms:
            if term["original"] in known:
                continue
            writer.writerow({
                "original": term["original"],
                "romaji": term.get("romaji", ""),
                "russian": term.get("russian", ""),
                "issue_date": digest["issue_date"],
                "status": term.get("status", "требует проверки"),
            })
            known.add(term["original"])
            added += 1
    return added


def publish(digest: dict, corpus: Corpus, state: State, today: date,
            issues_dir: Path = ISSUES, site_dir: Path = SITE,
            state_path: Path | None = None) -> Path:
    """Кладёт выпуск в архив, двигает состояние и пересобирает сайт."""
    issues_dir.mkdir(parents=True, exist_ok=True)
    issue_path = issues_dir / f"{digest['issue_date']}.json"
    issue_path.write_text(json.dumps(digest, ensure_ascii=False, indent=2) + "\n",
                          encoding="utf-8")

    # Помечаем весь корпус, а не только вошедшее в выпуск: остальное модель
    # уже видела и отвергла, платить за него повторно незачем.
    for article in corpus.articles:
        state.mark_seen(article.url, digest["issue_date"])
    state.forget_old(today)
    state.last_issue_date = digest["issue_date"]
    state.last_issue_slug = digest["issue_date"]
    state.save(state_path) if state_path else state.save()

    render_site(load_issues(issues_dir), site_dir)
    return issue_path


def main() -> int:
    arguments = argparse.ArgumentParser(description="Полный прогон «Сумо-дайджеста»")
    arguments.add_argument("--dry-run", action="store_true",
                           help="не публиковать: сайт собирается в build/site")
    arguments.add_argument("--period-from", help="начало периода, YYYY-MM-DD")
    arguments.add_argument("--force", action="store_true",
                           help="собрать выпуск, даже если за сегодня он уже есть")
    arguments.add_argument("--model", default=os.getenv("SUMO_DIGEST_MODEL", DEFAULT_MODEL))
    options = arguments.parse_args()

    dry_run = options.dry_run or os.getenv("SUMO_DIGEST_DRY_RUN") == "1"
    today = date.today()
    state = State.load()
    if options.period_from:
        state.last_issue_date = options.period_from

    # Догоняющий запуск: если выпуск за сегодня уже собран, второй не нужен.
    if state.last_issue_date == today.isoformat() and not options.force and not dry_run:
        print(f"Выпуск за {today} уже есть — делать нечего.")
        return 0

    print(f"1. collect · период с {state.last_issue_date}")
    config = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    corpus = collect(config, state, today)
    save_corpus(corpus)
    for status in corpus.sources:
        print(f"   {status.id:<14} {status.links_found:>4} ссылок  {status.status}")
    if not corpus.articles:
        print("Корпус пуст: писать не из чего.", file=sys.stderr)
        return 1
    print(f"   статей в корпусе: {len(corpus.articles)}")

    print(f"2. write · {options.model}")
    digest, usage = write_digest(corpus, options.model)
    (BUILD / "digest.raw.json").write_text(
        json.dumps(digest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"   токенов: вход {usage['input_tokens']}, выход {usage['output_tokens']}")

    print("3. validate")
    try:
        digest, lint = validate(digest, corpus)
    except ValidationFailed as failure:
        print("   выпуск не прошёл валидацию:", file=sys.stderr)
        for problem in failure.problems:
            print(f"     - {problem}", file=sys.stderr)
        return 1

    if lint.problems:
        print("   транслитерация требует правки, отправляю фрагменты модели")
        digest, lint = repair_transliteration(digest, lint, options.model)
    for wrong, right, count in lint.fixes:
        print(f"   заменено: «{wrong}» → «{right}» ×{count}")
    for problem in lint.problems:
        print(f"   осталось (публикуем всё равно): {problem}")
    for note in lint.warnings:
        print(f"   предупреждение: {note}")
    print(f"   блоков: {len(digest['blocks'])}")

    if dry_run:
        render_site([digest], BUILD / "site")
        print(f"\nDRY RUN: ничего не опубликовано, сайт собран в {BUILD / 'site'}")
        return 0

    print("4. publish")
    added = append_new_terms(digest)
    issue_path = publish(digest, corpus, state, today)
    print(f"   выпуск: {issue_path}")
    print(f"   новых имён в накопителе: {added}")
    print(f"   сайт: {SITE} ({len(load_issues())} выпусков)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
