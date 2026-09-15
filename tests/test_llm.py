"""Сообщение модели: турнирная часть появляется только на время басё.

Сам вызов API здесь не проверяется — сети в тестах нет. Проверяется то, что
можно проверить без неё: что модель узнаёт о турнире из корпуса, а не из своих
представлений о календаре, и что между турнирами такого указания ей не приходит.
"""

from sumo_digest.llm import build_user_message
from sumo_digest.models import Article, BashoDay, BashoWindow, Corpus, SourceStatus

AKI = BashoWindow(id="2026-aki", name="Аки Басё", place="Токио, Рёгоку Кокугикан",
                  start="2026-09-13", end="2026-09-27",
                  days=[BashoDay(1, "2026-09-13", "a001"),
                        BashoDay(2, "2026-09-14", None),
                        BashoDay(3, "2026-09-15", "a002")])


def corpus(basho: BashoWindow | None = None) -> Corpus:
    return Corpus(
        period_from="2026-09-13", period_to="2026-09-15",
        articles=[Article(id="a001", source_id="sumostomp", source_name="Sumo Stomp!",
                          url="https://www.sumo-stomp.com/p/2026-aki-basho-day-1-results-and",
                          title="2026 Aki Basho: Day 1 results and analysis",
                          text="Onosato beat Hoshoryu." * 20, published="2026-09-13")],
        sources=[SourceStatus(id="sumostomp", name="Sumo Stomp!")],
        basho=basho,
    )


def test_between_tournaments_the_model_is_not_asked_for_a_chronicle():
    message = build_user_message(corpus())
    assert "basho_day" not in message
    assert "basho_bout" not in message
    assert "Басё" not in message


def test_during_the_tournament_the_days_and_the_key_bout_are_asked_for():
    message = build_user_message(corpus(AKI))
    assert "Аки Басё" in message and "2026-09-27" in message
    assert "basho_day" in message and "basho_bout" in message
    assert "день 1 (2026-09-13) — отчёт в статье a001" in message
    assert "день 3 (2026-09-15) — отчёт в статье a002" in message


def test_a_day_without_a_report_is_marked_as_nothing_to_write_about():
    """Выдумать результаты дня — самое простое, что может сделать модель."""
    message = build_user_message(corpus(AKI))
    line = next(row for row in message.splitlines() if row.startswith("  день 2"))
    assert "отчёта в корпусе нет" in line
