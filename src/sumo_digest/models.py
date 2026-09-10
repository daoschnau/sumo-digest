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
