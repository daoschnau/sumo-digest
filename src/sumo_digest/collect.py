"""Шаг 1–2: обход листингов и сбор корпуса статей.

Единственное место в пайплайне, которое ходит в сеть. Модель работает только
с тем, что вернул этот шаг, — поэтому закрытый список источников из
спецификации здесь становится настоящим ограничением, а не пожеланием.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import httpx
import yaml

from .extract import extract_article, is_fresh
from .links import find_links
from .models import Article, ArticleRef, Corpus, SourceStatus
from .state import State

CONFIG_PATH = Path("config/sources.yml")


@dataclass
class Fetcher:
    """Загрузка страниц с кешем на время прогона.

    Спецификация запрещает повторять попытку к недоступному источнику, поэтому
    ретраев здесь нет: сбой запроса — это статус failed и переход к следующему.
    """

    timeout: float
    user_agent: str
    cache: dict[str, str | None] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        self.cache = {}

    def get(self, url: str) -> str | None:
        if url in self.cache:
            return self.cache[url]
        try:
            response = httpx.get(url, timeout=self.timeout, follow_redirects=True,
                                 headers={"User-Agent": self.user_agent})
            text = response.text if response.status_code == 200 else None
        except httpx.HTTPError:
            text = None
        self.cache[url] = text
        return text


def article_refs(source: dict, fetcher: Fetcher, limit: int) -> tuple[list[ArticleRef], str]:
    """Ссылки на статьи одного источника и его статус.

    Если у источника задан блок via, листинг берётся оттуда, а адрес статьи
    собирается канонический — на сайте самого издания (случай Hochi, E0).
    """
    via = source.get("via") or {}
    listing_url = via.get("listing_url") or source["listing_url"]
    pattern = via.get("link_pattern") or source["link_pattern"]
    canonical = via.get("canonical_url")

    html = fetcher.get(listing_url)
    if html is None:
        return [], "failed"

    links = find_links(html, listing_url, pattern, canonical)[:limit]
    return (
        [ArticleRef(source["id"], source["name"], url) for url in links],
        "ok" if links else "partial",
    )


def collect(config: dict, state: State, today: date) -> Corpus:
    """Полный обход: источники по приоритету, затем бюджет корпуса."""
    defaults = config.get("defaults", {})
    budget = config.get("budget", {})
    fetcher = Fetcher(
        timeout=float(defaults.get("timeout_seconds", 15)),
        user_agent=defaults.get("user_agent", "sumo-digest/1.0"),
    )
    max_links = int(defaults.get("max_links_per_source", 15))
    max_articles = int(budget.get("max_articles", 12))

    sources = sorted((s for s in config["sources"] if s.get("enabled", True)),
                     key=lambda s: s["priority"])

    statuses: list[SourceStatus] = []
    pending: list[ArticleRef] = []
    for source in sources:
        refs, status = article_refs(source, fetcher, max_links)
        fresh = [ref for ref in refs if not state.seen(ref.url)]
        statuses.append(SourceStatus(id=source["id"], name=source["name"], status=status,
                                     links_found=len(refs)))
        pending.extend(fresh)

    # Бюджет тратим по приоритету источника, затем по порядку на листинге —
    # это не бюджет браузинга, а контроль стоимости токенов.
    articles: list[Article] = []
    used: dict[str, int] = {}
    for number, ref in enumerate(pending, start=1):
        if len(articles) >= max_articles:
            break
        html = fetcher.get(ref.url)
        if html is None:
            continue
        article = extract_article(html, ref, f"a{number:03d}")
        if article is None or not is_fresh(article, state.last_issue_date):
            continue
        articles.append(article)
        used[ref.source_id] = used.get(ref.source_id, 0) + 1

    for status in statuses:
        status.articles_used = used.get(status.id, 0)

    return Corpus(period_from=state.last_issue_date, period_to=today.isoformat(),
                  articles=articles, sources=statuses)


def main() -> int:
    arguments = argparse.ArgumentParser(description="Сбор корпуса статей без обращения к модели")
    arguments.add_argument("--dry-run", action="store_true",
                           help="не трогать состояние, только показать корпус")
    arguments.add_argument("--out", type=Path, default=Path("build/corpus.json"),
                           help="куда положить корпус (по умолчанию build/corpus.json)")
    options = arguments.parse_args()

    config = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    state = State.load()
    corpus = collect(config, state, date.today())

    print(f"период: {corpus.period_from} — {corpus.period_to}")
    print(f"{'источник':<16} {'ссылок':>7} {'статей':>7}  статус")
    for status in corpus.sources:
        print(f"{status.id:<16} {status.links_found:>7} {status.articles_used:>7}  {status.status}")
    print(f"\nвсего статей в корпусе: {len(corpus.articles)}")
    for article in corpus.articles:
        head = article.title[:60] or "(без заголовка)"
        print(f"  {article.id} {article.published or '????-??-??'}"
              f" [{article.source_id}] {head}")

    options.out.parent.mkdir(parents=True, exist_ok=True)
    options.out.write_text(json.dumps(corpus.as_dict(), ensure_ascii=False, indent=2) + "\n",
                           encoding="utf-8")

    # Тексты статей живут только внутри прогона. Наружу — в артефакты, логи
    # и тем более в репозиторий — уходит опись: ссылки, даты, заголовки, объём.
    meta_path = options.out.with_name(options.out.stem + ".meta.json")
    meta_path.write_text(json.dumps(corpus.as_meta_dict(), ensure_ascii=False, indent=2) + "\n",
                         encoding="utf-8")
    print(f"\nкорпус записан: {options.out} (тексты, только для этого прогона)")
    print(f"опись корпуса:  {meta_path} (без текстов, её и забираем артефактом)")

    if not corpus.articles:
        # Пустой корпус — это не выпуск. Публиковать пустую страницу нельзя (ТЗ §7).
        print("Корпус пуст: ни одной подходящей статьи.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
