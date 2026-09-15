"""Типы, которыми шаги пайплайна обмениваются между собой."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass(frozen=True)
class ArticleRef:
    """Ссылка на статью, найденная на листинге. Текста ещё нет."""

    source_id: str
    source_name: str
    url: str


@dataclass
class Article:
    """Статья с текстом — то, что уходит модели."""

    id: str
    source_id: str
    source_name: str
    url: str
    title: str
    text: str
    published: str | None
    # low — дату со страницы достать не удалось; модель обязана не указывать
    # дату в блоке, а не подставлять дату публикации (ТЗ §3.2).
    date_confidence: str = "high"

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class SourceStatus:
    """Строка периода собирается из этого: что открылось, что нет."""

    id: str
    name: str
    status: str = "ok"  # ok | partial | failed
    links_found: int = 0
    articles_used: int = 0
    note: str = ""

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class BashoDay:
    """День турнира и отчёт о нём из корпуса, если он там есть.

    `article_id` пустой — о дне известно из календаря, но отчёта в корпусе нет.
    Такой день модель описывать не должна: выдумать результаты дня проще всего.
    """

    day: int
    date: str
    article_id: str | None = None

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class BashoWindow:
    """Турнир, чьи дни попали в отчётный период. None вместо него — межсезонье."""

    id: str
    name: str
    place: str
    start: str
    end: str
    days: list[BashoDay] = field(default_factory=list)

    def as_dict(self) -> dict:
        return asdict(self)

    @property
    def reported_days(self) -> list[BashoDay]:
        """Дни, о которых в корпусе есть отчёт, — только они попадают в выпуск."""
        return [day for day in self.days if day.article_id]


@dataclass
class Corpus:
    """Результат шага collect — единственное, что видит модель."""

    period_from: str
    period_to: str
    articles: list[Article] = field(default_factory=list)
    sources: list[SourceStatus] = field(default_factory=list)
    # Турнир, если он идёт в этом периоде. От него зависит, есть ли в выпуске
    # хроника дней и блок о главной схватке, — см. llm.tournament_brief.
    basho: BashoWindow | None = None

    def as_dict(self) -> dict:
        return {
            "period": {"from": self.period_from, "to": self.period_to},
            "articles": [a.as_dict() for a in self.articles],
            "sources": [s.as_dict() for s in self.sources],
            "basho": self.basho.as_dict() if self.basho else None,
        }

    def as_meta_dict(self) -> dict:
        """То же самое без текстов статей — для логов и артефактов.

        Полные тексты чужих новостных материалов не должны покидать прогон:
        цитировать факт со ссылкой на первоисточник — одно, раздавать копию
        статьи — другое. Для разбора неудачного выпуска хватает того, что
        попало на вход: издание, адрес, дата, заголовок, объём.
        """
        return {
            "period": {"from": self.period_from, "to": self.period_to},
            "articles": [
                {
                    "id": a.id,
                    "source_id": a.source_id,
                    "source_name": a.source_name,
                    "url": a.url,
                    "published": a.published,
                    "date_confidence": a.date_confidence,
                    "title": a.title,
                    "text_length": len(a.text),
                }
                for a in self.articles
            ],
            "sources": [s.as_dict() for s in self.sources],
            "basho": self.basho.as_dict() if self.basho else None,
        }


def corpus_from_dict(raw: dict) -> Corpus:
    """Обратная сборка корпуса из build/corpus.json."""
    return Corpus(
        period_from=raw["period"]["from"],
        period_to=raw["period"]["to"],
        articles=[Article(**item) for item in raw["articles"]],
        sources=[SourceStatus(**item) for item in raw["sources"]],
        basho=basho_from_dict(raw.get("basho")),
    )


def basho_from_dict(raw: dict | None) -> BashoWindow | None:
    """Обратная сборка турнира из build/corpus.json. None — межсезонье."""
    if not raw:
        return None
    fields = {key: value for key, value in raw.items() if key != "days"}
    return BashoWindow(**fields, days=[BashoDay(**day) for day in raw.get("days", [])])
