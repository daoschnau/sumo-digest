"""Календарь турниров: идёт ли басё, какие дни в периоде, где взять номер дня."""

from datetime import date
from pathlib import Path

import pytest

from sumo_digest.basho import (
    Basho,
    basho_window,
    calendar_warning,
    current_basho,
    day_from_url,
    load_calendar,
)

AKI = Basho(id="2026-aki", name="Аки Басё", place="Токио, Рёгоку Кокугикан",
            start="2026-09-13", end="2026-09-27")
DAY_PATTERN = r"basho-(?:day-(?P<day>\d{1,2})|(?P<final>final-day))-results"


@pytest.fixture(scope="module")
def calendar() -> list[Basho]:
    return load_calendar(Path(__file__).parent.parent / "config" / "basho.yml")


def test_calendar_is_loaded_in_order_with_iso_dates(calendar):
    assert [basho.start for basho in calendar] == sorted(b.start for b in calendar)
    for basho in calendar:
        assert isinstance(basho.start, str) and isinstance(basho.end, str)
        # Хонбасё — пятнадцать дней; описка в конфиге ломает нумерацию дней.
        assert basho.day_number(basho.end) == 15


def test_tournaments_do_not_overlap(calendar):
    for earlier, later in zip(calendar, calendar[1:], strict=False):
        assert earlier.end < later.start


def test_period_inside_the_tournament(calendar):
    assert current_basho(calendar, "2026-09-14", "2026-09-17").id == "2026-aki"


def test_period_that_only_touches_the_first_day(calendar):
    """Первый день турнира, прошедший в воскресенье, — новость вторничного выпуска."""
    assert current_basho(calendar, "2026-09-10", "2026-09-13").id == "2026-aki"


def test_off_season_period_has_no_tournament(calendar):
    assert current_basho(calendar, "2026-08-01", "2026-08-05") is None
    assert current_basho(calendar, "2026-09-09", "2026-09-12") is None
    assert current_basho(calendar, "2026-09-28", "2026-10-01") is None


def test_day_number_is_none_outside_the_tournament():
    assert AKI.day_number("2026-09-13") == 1
    assert AKI.day_number("2026-09-15") == 3
    assert AKI.day_number("2026-09-12") is None
    assert AKI.day_number("2026-09-28") is None


def test_day_comes_from_the_url_not_from_the_text():
    url = "https://www.sumo-stomp.com/p/2026-aki-basho-day-3-results-and"
    assert day_from_url(url, DAY_PATTERN) == 3
    assert day_from_url("https://www.sumo-stomp.com/p/2026-nagoya-basho-day-10-results",
                        DAY_PATTERN) == 10
    # Пятнадцатый день в адресах называется не числом.
    assert day_from_url("https://www.sumo-stomp.com/p/2025-aki-basho-final-day-results",
                        DAY_PATTERN) == 15
    assert day_from_url("https://www.sumo-stomp.com/p/2026-aki-basho-predictions",
                        DAY_PATTERN) is None


def test_impossible_day_number_is_rejected():
    """Шестнадцатого дня у хонбасё не бывает: это не отчёт о дне."""
    assert day_from_url("https://x/p/2026-aki-basho-day-31-results", DAY_PATTERN) is None


def test_window_pairs_days_with_reports():
    window = basho_window(AKI, "2026-09-15", "2026-09-17", {3: "a004", 4: "a005"})
    assert [(day.day, day.date, day.article_id) for day in window.days] == [
        (3, "2026-09-15", "a004"),
        (4, "2026-09-16", "a005"),
        (5, "2026-09-17", None),
    ]
    assert [day.day for day in window.reported_days] == [3, 4]


def test_window_keeps_a_report_older_than_the_period():
    """Отчёт о дне выходит вечером и попадает в следующий выпуск."""
    window = basho_window(AKI, "2026-09-15", "2026-09-16", {2: "a001"})
    assert [day.day for day in window.days] == [2, 3, 4]
    assert window.days[0].article_id == "a001"


def test_window_of_a_tournament_that_has_not_started_yet():
    """Период кончается за день до басё: дней турнира в нём нет ни одного."""
    window = basho_window(AKI, "2026-09-09", "2026-09-12", {})
    assert window.days == []


def test_warning_appears_before_the_calendar_runs_out(calendar):
    assert calendar_warning(calendar, date(2026, 9, 15)) is None
    assert "2026-11-22" in calendar_warning(calendar, date(2026, 11, 1))
    assert "пуст" in calendar_warning([], date(2026, 9, 15))
