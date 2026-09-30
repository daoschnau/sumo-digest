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


def test_covered_dates_remember_what_the_issue_described(tmp_path):
    """Отчёт о дне выходит вечером — выпуск с этим днём к тому времени уже вышел."""
    state = State(last_issue_date="2026-09-21")
    assert not state.covered("2026-09-21")
    state.mark_covered("2026-09-21", "2026-09-21")
    assert state.covered("2026-09-21")

    path = tmp_path / "state.json"
    state.save(path)
    assert State.load(path).covered("2026-09-21")


def test_old_covered_dates_are_forgotten_with_the_urls():
    state = State(last_issue_date="2026-09-28", seen_urls_kept_days=30)
    state.mark_covered("2026-07-26", "2026-07-26")
    state.mark_covered("2026-09-27", "2026-09-28")
    state.forget_old(date(2026, 9, 30))
    assert not state.covered("2026-07-26")
    assert state.covered("2026-09-27")


def test_a_state_file_without_covered_dates_still_loads(tmp_path):
    """Файл, написанный до появления памяти о днях, не должен ронять прогон."""
    path = tmp_path / "state.json"
    path.write_text('{"last_issue_date": "2026-09-28", "seen_urls": {}}', encoding="utf-8")
    assert State.load(path).covered_dates == {}
