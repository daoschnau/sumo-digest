"""Состояние: повторный прогон не должен пересказывать прошлый выпуск."""

import json
from datetime import date

from sumo_digest.state import State

URL = "https://hochi.news/articles/20260910-OHT1T51188.html"


def test_seen_url_survives_save_and_load(tmp_path):
    path = tmp_path / "state.json"
    state = State(last_issue_date="2026-09-10")
    state.mark_seen(URL, "2026-09-10")
    state.save(path)

    again = State.load(path)
    assert again.seen(URL)
    assert not again.seen("https://hochi.news/articles/20260910-OHT1T99999.html")


def test_query_string_does_not_hide_a_seen_url(tmp_path):
    state = State(last_issue_date="2026-09-10")
    state.mark_seen(URL, "2026-09-10")
    assert state.seen(URL + "?utm_source=x")


def test_old_entries_are_forgotten(tmp_path):
    state = State(last_issue_date="2026-09-10", seen_urls_kept_days=30)
    state.mark_seen(URL, "2026-07-01")
    state.mark_seen("https://a.jp/new.html", "2026-09-09")
    assert state.forget_old(date(2026, 9, 10)) == 1
    assert not state.seen(URL)
    assert state.seen("https://a.jp/new.html")


def test_reads_the_legacy_list_shape(tmp_path):
    path = tmp_path / "state.json"
    path.write_text(json.dumps({"last_issue_date": "2026-09-10",
                                "seen_urls": ["sha1:deadbeef"]}), encoding="utf-8")
    state = State.load(path)
    assert state.seen_urls == {"sha1:deadbeef": "2026-09-10"}
