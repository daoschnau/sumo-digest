"""Публикация: архив, состояние, накопитель имён. Без сети и без модели."""

import csv
import json
from datetime import date

import pytest

from sumo_digest.models import Article, Corpus
from sumo_digest.run import append_new_terms, publish
from sumo_digest.state import State

URL = "https://hochi.news/articles/20260910-OHT1T51188.html"


@pytest.fixture
def digest() -> dict:
    return {
        "issue_date": "2026-09-10",
        "period": {"from": "2026-09-07", "to": "2026-09-10"},
        "sources_reviewed": [{"name": "Hochi News", "status": "ok", "articles_used": 1}],
        "lead": "Главное за период: травмы лидеров перед Аки Басё.",
        "blocks": [{
            "date": "2026-09-10", "place": "Рёгоку Кокугикан",
            "subtitle": "Хошорю пропустит турнир",
            "body": "Ёкодзуна Хошорю (豊昇龍) не восстановился после операции.",
            "category": "injury", "importance": 5, "source_ids": ["a001"],
            "sources": [{"name": "Hochi News", "url": URL}],
        }],
        "missed": "Слухи.",
        "quiet_period": False,
        "new_terms": [
            {"original": "音羽山", "romaji": "Otowayama", "russian": "Отоваяма",
             "status": "требует проверки"},
            {"original": "時津風", "romaji": "Tokitsukaze", "russian": "Токицукадзе",
             "status": "требует проверки"},
        ],
    }


@pytest.fixture
def corpus() -> Corpus:
    return Corpus(period_from="2026-09-07", period_to="2026-09-10", articles=[
        Article(id="a001", source_id="hochi", source_name="Hochi News", url=URL,
                title="霧島", text="本文" * 200, published="2026-09-10"),
        Article(id="a002", source_id="sponichi", source_name="Sponichi",
                url="https://www.sponichi.co.jp/x.html", title="大の里",
                text="本文" * 200, published="2026-09-10"),
    ])


def test_publish_writes_the_issue_and_rebuilds_the_site(digest, corpus, tmp_path):
    state = State(last_issue_date="2026-09-07")
    issue_path = publish(digest, corpus, state, date(2026, 9, 10),
                         issues_dir=tmp_path / "issues", site_dir=tmp_path / "site",
                         state_path=tmp_path / "state.json")
    assert json.loads(issue_path.read_text(encoding="utf-8"))["issue_date"] == "2026-09-10"
    assert (tmp_path / "site" / "2026-09-10" / "index.html").exists()
    assert (tmp_path / "site" / "feed.xml").exists()


def test_publish_moves_the_period_forward(digest, corpus, tmp_path):
    state = State(last_issue_date="2026-09-07")
    publish(digest, corpus, state, date(2026, 9, 10), issues_dir=tmp_path / "issues",
            site_dir=tmp_path / "site", state_path=tmp_path / "state.json")
    assert state.last_issue_date == "2026-09-10"
    assert State.load(tmp_path / "state.json").last_issue_date == "2026-09-10"


def test_whole_corpus_is_marked_seen_not_only_what_was_used(digest, corpus, tmp_path):
    """Отвергнутое моделью тоже видено — платить за него второй раз незачем."""
    state = State(last_issue_date="2026-09-07")
    publish(digest, corpus, state, date(2026, 9, 10), issues_dir=tmp_path / "issues",
            site_dir=tmp_path / "site", state_path=tmp_path / "state.json")
    assert state.seen(URL)
    assert state.seen("https://www.sponichi.co.jp/x.html")


def test_new_terms_are_appended_once(digest, tmp_path):
    path = tmp_path / "new_terms.csv"
    path.write_text("original,romaji,russian,issue_date,status\n", encoding="utf-8")

    assert append_new_terms(digest, path) == 2
    assert append_new_terms(digest, path) == 0, "повторный прогон не должен дублировать"

    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert [row["original"] for row in rows] == ["音羽山", "時津風"]
    assert rows[0]["issue_date"] == "2026-09-10"
    assert rows[0]["status"] == "требует проверки"


def test_issue_without_new_terms_touches_nothing(tmp_path):
    path = tmp_path / "new_terms.csv"
    path.write_text("original,romaji,russian,issue_date,status\n", encoding="utf-8")
    before = path.read_text(encoding="utf-8")
    assert append_new_terms({"issue_date": "2026-09-10"}, path) == 0
    assert path.read_text(encoding="utf-8") == before


def test_new_terms_never_reach_the_issue_text(digest, corpus, tmp_path):
    """Инвариант 6: таблица новых имён живёт только в CSV."""
    issue_path = publish(digest, corpus, State(last_issue_date="2026-09-07"),
                         date(2026, 9, 10), issues_dir=tmp_path / "issues",
                         site_dir=tmp_path / "site", state_path=tmp_path / "state.json")
    page = (tmp_path / "site" / "2026-09-10" / "index.html").read_text(encoding="utf-8")
    assert "音羽山" not in page
    assert "Отоваяма" not in page
    # В JSON выпуска они остаются: оттуда их забирает накопитель.
    assert json.loads(issue_path.read_text(encoding="utf-8"))["new_terms"]
