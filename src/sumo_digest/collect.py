"""Шаг 1–2: обход листингов и сбор корпуса статей.

Единственное место в пайплайне, которое ходит в сеть. Модель работает только
с тем, что вернул этот шаг, — поэтому закрытый список источников из
спецификации здесь становится настоящим ограничением, а не пожеланием.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.robotparser
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from urllib.parse import urlsplit

import httpx
import yaml

from .extract import extract_article, is_fresh
from .links import find_links, robots_parser
from .models import Article, ArticleRef, Corpus, SourceStatus
from .state import State

CONFIG_PATH = Path("config/sources.yml")


@dataclass
class Fetcher:
    """Загрузка страниц с кешем на время прогона.

    Спецификация запрещает повторять попытку к недоступному источнику, поэтому
    ретраев здесь нет: сбой запроса — это статус failed и переход к следующему.

    robots.txt читается один раз на хост, и запрет попадает в лог и в отчёт
    прогона — но обход не останавливает. Это сенсор, а не ворота, и вот почему.
    Молчаливый отказ по чужому файлу — это ноль вместо выпуска в четверг утром,
    когда чинить его некому; та же логика, по которой замечание транслитерации
    публикацию не блокирует. Узнав о запрете из лога, владелец решает сам:
    сменить User-Agent, написать изданию или выключить источник в конфиге
    (`enabled: false`) — механизм для этого уже есть.

    Проверено 11.09.2026 на всех девяти: восемь разрешают, у dmenu файла нет.
    То есть сегодня проверка ничего не меняет и нужна ровно на тот день,
    когда кто-то поменяет свой robots.txt.

    От бана по IP защищает не это, а `delay`: пауза между настоящими запросами.
    Прогон и так идёт минуты, секунда на запрос ничего не стоит.
    """

    timeout: float
    user_agent: str
    delay: float = 1.0
    cache: dict[str, str | None] = field(default_factory=dict)
    robots: dict[str, urllib.robotparser.RobotFileParser | None] = field(
        default_factory=dict)
    disallowed: set[str] = field(default_factory=set)
    _last_request: float = 0.0

    def check_robots(self, url: str) -> None:
        """Запоминает хосты, чей robots.txt запрещает этот адрес. Не блокирует."""
        host = urlsplit(url).netloc
        if host not in self.robots:
            self.robots[host] = robots_parser(url, self.user_agent, self.timeout)
        parser = self.robots[host]
        if parser is not None and not parser.can_fetch(self.user_agent, url):
            self.disallowed.add(host)

    def get(self, url: str) -> str | None:
        if url in self.cache:
            return self.cache[url]
        self.check_robots(url)
        pause = self.delay - (time.monotonic() - self._last_request)
        if pause > 0:
            time.sleep(pause)
        try:
            response = httpx.get(url, timeout=self.timeout, follow_redirects=True,
                                 headers={"User-Agent": self.user_agent})
            text = response.text if response.status_code == 200 else None
        except httpx.HTTPError:
            text = None
        self._last_request = time.monotonic()
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


# Заголовок перепечатки совпадает с оригиналом слово в слово — по нему дубли
# и ловятся. Сравниваем без пробелов, регистра и пунктуации: агрегатор иногда
# меняет кавычки и добавляет пробел перед скобкой.
TITLE_NOISE = re.compile(r"[\s\u3000　【】\[\]()（）「」『』\"'“”‘’·・、,。.!！?？:：;；\-—–]+")


def title_key(title: str) -> str:
    return TITLE_NOISE.sub("", title).casefold()


def about_sumo(article: Article, keywords: list[str]) -> bool:
    """Общая лента и рубрика единоборств приносят материал не про сумо.

    Проверка нужна только источникам, у которых листинг шире темы, — у них
    в конфиге стоит requires_keyword. Остальным она не задаётся и не применяется.
    """
    if not keywords:
        return True
    haystack = f"{article.title}\n{article.text}".casefold()
    return any(word.casefold() in haystack for word in keywords)


def collect(config: dict, state: State, today: date) -> Corpus:
    """Полный обход: источники по приоритету, затем бюджет корпуса."""
    defaults = config.get("defaults", {})
    budget = config.get("budget", {})
    fetcher = Fetcher(
        timeout=float(defaults.get("timeout_seconds", 15)),
        user_agent=defaults.get("user_agent", "sumo-digest/1.0"),
        delay=float(defaults.get("delay_seconds", 1)),
    )
    max_links = int(defaults.get("max_links_per_source", 15))
    max_articles = int(budget.get("max_articles", 12))
    per_source = int(budget.get("max_articles_per_source", max_articles))

    sources = sorted((s for s in config["sources"] if s.get("enabled", True)),
                     key=lambda s: s["priority"])
    by_id = {source["id"]: source for source in sources}

    statuses: list[SourceStatus] = []
    pending: list[ArticleRef] = []
    for source in sources:
        refs, status = article_refs(source, fetcher, max_links)
        fresh = [ref for ref in refs if not state.seen(ref.url)]
        statuses.append(SourceStatus(id=source["id"], name=source["name"], status=status,
                                     links_found=len(refs)))
        pending.extend(fresh)

    articles: list[Article] = []
    used: dict[str, int] = {}
    titles: set[str] = set()
    taken: set[str] = set()
    number = 0

    def take(ref: ArticleRef, quota: int) -> bool:
        """Пробует добавить статью в корпус. False — не подошла или не влезла."""
        nonlocal number
        if ref.url in taken or used.get(ref.source_id, 0) >= quota:
            return False
        html = fetcher.get(ref.url)
        if html is None:
            return False
        number += 1
        article = extract_article(html, ref, f"a{number:03d}")
        if article is None or not is_fresh(article, state.last_issue_date):
            return False
        if not about_sumo(article, by_id[ref.source_id].get("requires_keyword") or []):
            return False
        # Агрегатор перепечатывает Hochi, Sponichi, Sanspo и Chunichi под своим
        # адресом: разные URL, один текст. Источник с высшим приоритетом идёт
        # первым, поэтому в корпусе остаётся оригинал, а не перепечатка.
        key = title_key(article.title)
        if key and key in titles:
            return False
        titles.add(key)
        taken.add(ref.url)
        articles.append(article)
        used[ref.source_id] = used.get(ref.source_id, 0) + 1
        return True

    # Два прохода. Первый — с квотой на источник: без неё Sponichi с его
    # пятнадцатью ссылками способен забрать весь бюджет, и Hochi, который
    # по инварианту 3 обходится всегда и первым, не попадёт в выпуск вовсе.
    # Второй добирает остаток, если в тихий день квоты не хватило на бюджет.
    for pass_quota in (per_source, max_articles):
        for ref in pending:
            if len(articles) >= max_articles:
                break
            take(ref, pass_quota)
        if len(articles) >= max_articles:
            break

    for status in statuses:
        status.articles_used = used.get(status.id, 0)

    # Запрет в robots.txt не снимает источник с обхода, но обязан быть виден:
    # в логе прогона и в build/run.json, откуда его читает владелец.
    for source in sources:
        host = urlsplit(source["listing_url"]).netloc
        if host in fetcher.disallowed:
            note = f"robots.txt хоста {host} запрещает обход этим User-Agent"
            for status in statuses:
                if status.id == source["id"]:
                    status.note = note
            print(f"ВНИМАНИЕ: {source['id']} — {note}", file=sys.stderr)

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
