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
class Corpus:
    """Результат шага collect — единственное, что видит модель."""

    period_from: str
    period_to: str
    articles: list[Article] = field(default_factory=list)
    sources: list[SourceStatus] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "period": {"from": self.period_from, "to": self.period_to},
            "articles": [a.as_dict() for a in self.articles],
            "sources": [s.as_dict() for s in self.sources],
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
        }


def corpus_from_dict(raw: dict) -> Corpus:
    """Обратная сборка корпуса из build/corpus.json."""
    return Corpus(
        period_from=raw["period"]["from"],
        period_to=raw["period"]["to"],
        articles=[Article(**item) for item in raw["articles"]],
        sources=[SourceStatus(**item) for item in raw["sources"]],
    )
