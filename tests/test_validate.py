"""Валидация выпуска: ссылка не из корпуса не должна пройти никогда."""

import copy

import pytest

from sumo_digest.models import Article, Corpus, SourceStatus
from sumo_digest.schema import api_schema, load_schema
from sumo_digest.validate import ValidationFailed, check_facts, sort_blocks, validate

URL_A = "https://hochi.news/articles/20260910-OHT1T51188.html"
URL_B = "https://www.sponichi.co.jp/sports/news/2026/09/10/kiji/20260910s00005000296000c.html"


def article(article_id: str, url: str, name: str, confidence: str = "high") -> Article:
    return Article(id=article_id, source_id=name.lower(), source_name=name, url=url,
                   title="見出し", text="本文" * 200, published="2026-09-10",
                   date_confidence=confidence)


@pytest.fixture
def corpus() -> Corpus:
    return Corpus(
        period_from="2026-09-07", period_to="2026-09-10",
        articles=[article("a001", URL_A, "Hochi News"), article("a002", URL_B, "Sponichi")],
        sources=[SourceStatus(id="hochi", name="Hochi News")],
    )


@pytest.fixture
def digest() -> dict:
    block = {
        "date": "2026-09-10",
        "place": "Рёгоку Кокугикан",
        "subtitle": "Хошорю пропустит Аки Басё",
        "body": "Ёкодзуна Хошорю (豊昇龍) не восстановился после операции на колене. " * 2,
        "category": "injury",
        "importance": 5,
        "source_ids": ["a001"],
    }
    return {
        "issue_date": "2026-09-10",
        "period": {"from": "2026-09-07", "to": "2026-09-10"},
        "sources_reviewed": [{"name": "Hochi News", "status": "ok", "articles_used": 1}],
        "lead": "Главное за период: травмы лидеров и подготовка к Аки Басё в Рёгоку.",
        "blocks": [copy.deepcopy(block) for _ in range(5)],
        "missed": "Слухи о смене бейи.",
        "quiet_period": False,
    }


def test_valid_digest_passes(digest, corpus):
    checked, report = validate(digest, corpus)
    assert checked["blocks"]
    assert report.clean


def test_unknown_article_id_is_rejected(digest, corpus):
    digest["blocks"][0]["source_ids"] = ["a999"]
    with pytest.raises(ValidationFailed, match="нет во входном корпусе"):
        validate(digest, corpus)


def test_url_is_written_by_code_not_by_the_model(digest, corpus):
    """Ссылку в выпуск ставит код по идентификатору — выдумать её нельзя."""
    checked, _ = validate(digest, corpus)
    assert checked["blocks"][0]["sources"] == [{"name": "Hochi News", "url": URL_A}]


def test_event_date_may_precede_the_period_but_not_by_a_season(digest, corpus):
    # Статья вышла сегодня, а тренировка была вчера — это нормально.
    digest["blocks"][0]["date"] = "2026-09-05"
    assert not check_facts(digest, corpus)
    digest["blocks"][0]["date"] = "2026-06-01"
    assert any("вне окна" in p for p in check_facts(digest, corpus))


def test_future_date_is_rejected(digest, corpus):
    digest["blocks"][0]["date"] = "2026-12-31"
    assert any("вне окна" in p for p in check_facts(digest, corpus))


def test_date_invented_for_a_low_confidence_source_is_rejected(digest):
    corpus = Corpus(period_from="2026-09-07", period_to="2026-09-10",
                    articles=[article("a001", URL_A, "Hochi News", confidence="low")])
    assert any("date_confidence=low" in p for p in check_facts(digest, corpus))


def test_too_few_blocks_needs_quiet_period(digest, corpus):
    digest["blocks"] = digest["blocks"][:2]
    assert any("quiet_period" in p for p in check_facts(digest, corpus))
    digest["quiet_period"] = True
    assert not check_facts(digest, corpus)


def test_schema_violation_is_caught(digest, corpus):
    digest["blocks"][0]["category"] = "весёлые картинки"
    with pytest.raises(ValidationFailed, match="схема"):
        validate(digest, corpus)


def test_significance_beats_category():
    """Находка приёмки: дебют в дзюрё не должен стоять выше снятия ёкодзуны."""
    digest = {"blocks": [
        {"category": "banzuke", "importance": 2, "date": "2026-09-10"},
        {"category": "injury", "importance": 5, "date": "2026-09-10"},
        {"category": "training", "importance": 5, "date": "2026-09-09"},
        {"category": "makuuchi_juryo", "importance": 3, "date": "2026-09-10"},
    ]}
    order = [(b["category"], b["importance"]) for b in sort_blocks(digest)["blocks"]]
    assert order == [("injury", 5), ("training", 5),
                     ("makuuchi_juryo", 3), ("banzuke", 2)]


def test_category_breaks_a_tie_in_significance():
    digest = {"blocks": [
        {"category": "training", "importance": 4, "date": "2026-09-10"},
        {"category": "makuuchi_juryo", "importance": 4, "date": "2026-09-10"},
        {"category": "injury", "importance": 4, "date": "2026-09-10"},
    ]}
    order = [b["category"] for b in sort_blocks(digest)["blocks"]]
    assert order == ["makuuchi_juryo", "injury", "training"]


def test_fresher_first_and_undated_last_within_a_group():
    digest = {"blocks": [
        {"category": "injury", "importance": 4},
        {"category": "injury", "importance": 4, "date": "2026-09-08"},
        {"category": "injury", "importance": 4, "date": "2026-09-10"},
    ]}
    order = [b.get("date") for b in sort_blocks(digest)["blocks"]]
    assert order == ["2026-09-10", "2026-09-08", None]


def test_api_schema_drops_what_structured_outputs_rejects():
    stripped = api_schema(load_schema())
    text = str(stripped)
    for key in ("minLength", "maxLength", "minItems", "maxItems", "minimum", "default"):
        assert key not in text
    # Ограничения остаются в полной схеме — иначе валидация станет фикцией.
    assert "minLength" in str(load_schema())
    assert stripped["additionalProperties"] is False


def test_corpus_manifest_carries_no_article_text(corpus):
    """Тексты чужих статей не покидают прогон: в артефакт уходит только опись."""
    meta = corpus.as_meta_dict()
    dumped = str(meta)
    assert "本文" not in dumped
    assert all("text" not in article for article in meta["articles"])
    assert meta["articles"][0]["text_length"] > 0
    assert meta["articles"][0]["url"].startswith("https://")
    # Полный корпус тексты по-прежнему несёт: он нужен модели внутри прогона.
    assert corpus.as_dict()["articles"][0]["text"]
