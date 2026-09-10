"""HTML статьи → текст, заголовок и дата публикации.

Универсальный экстрактор вместо селекторов под каждое издание: селекторы
ломаются при первом же редизайне, а изданий девять.
"""

from __future__ import annotations

import trafilatura

from .models import Article, ArticleRef

# Короче этого — заглушка, промо или страница подписки, а не статья (ТЗ §3.2).
MIN_TEXT_LENGTH = 200


def extract_article(html: str, ref: ArticleRef, article_id: str) -> Article | None:
    """Возвращает статью или None, если текста на странице не нашлось."""
    document = trafilatura.bare_extraction(html, with_metadata=True)
    if document is None or not document.text:
        return None

    text = document.text.strip()
    if len(text) < MIN_TEXT_LENGTH:
        return None

    published = document.date
    return Article(
        id=article_id,
        source_id=ref.source_id,
        source_name=ref.source_name,
        url=ref.url,
        title=(document.title or "").strip(),
        text=text,
        published=published,
        # Дату, которой нет на странице, не восстанавливаем: модель обязана
        # не указывать дату в блоке, а не догадываться о ней.
        date_confidence="high" if published else "low",
    )


def is_fresh(article: Article, since: str) -> bool:
    """Статья новее даты прошлого выпуска. Без даты — оставляем, решит модель."""
    if article.published is None:
        return True
    return article.published >= since
