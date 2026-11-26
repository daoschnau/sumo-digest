"""Пересчёт иен в доллары: суммы в тексте выпуска, курс на дату выпуска."""

import pytest

from sumo_digest.money import dollars, load_rates, rate_on, with_dollars

RATE = 159.0


@pytest.mark.parametrize(("text", "expected"), [
    ("перечислит 4 784 848 иен", "перечислит 4 784 848 иен (≈ $30 000)"),
    ("перечислит 4 784 848 иен", "перечислит 4 784 848 иен (≈ $30 000)"),
    ("призовые 10 млн иен.", "призовые 10 млн иен (≈ $63 000)."),
    ("собрано 3,3 млн иен,", "собрано 3,3 млн иен (≈ $21 000),"),
    ("бюджет 1,5 млрд йен", "бюджет 1,5 млрд йен (≈ $9 400 000)"),
    ("по 500 тыс. иен", "по 500 тыс. иен (≈ $3 100)"),
    ("остаток 224 848 иен", "остаток 224 848 иен (≈ $1 400)"),
    ("билет 3000 иен", "билет 3000 иен (≈ $19)"),
])
def test_every_written_form_of_a_yen_amount_gets_dollars(text, expected):
    assert with_dollars(text, RATE) == expected


def test_only_the_number_with_the_word_yen_is_converted():
    """«с 10 до 20 млн иен»: к чему относится 10, регулярка не угадывает."""
    assert (with_dollars("вдвое — с 10 до 20 млн иен", RATE)
            == "вдвое — с 10 до 20 млн иен (≈ $130 000)")


def test_dollars_already_written_by_the_model_are_not_doubled():
    text = "пожертвование 10 млн иен (около $63 000)"
    assert with_dollars(text, RATE) == text


def test_text_without_yen_is_left_alone():
    text = "Оносато (大の里) выиграл 12 схваток из 15, 2 иероглифа."
    assert with_dollars(text, RATE) == text


def test_without_a_rate_nothing_is_converted():
    assert with_dollars("10 млн иен", None) == "10 млн иен"


def test_dollars_keep_two_significant_digits():
    assert dollars(30_093.4) == "$30 000"
    assert dollars(62_893) == "$63 000"
    assert dollars(18.9) == "$19"


def test_issue_uses_the_rate_in_force_on_its_date():
    """Новая строка курса не должна менять доллары в старых выпусках."""
    table = [("2026-01-01", 155.0), ("2026-11-01", 159.0)]
    assert rate_on("2026-09-14", table) == 155.0
    assert rate_on("2026-11-01", table) == 159.0
    assert rate_on("2026-11-26", table) == 159.0
    assert rate_on("2025-12-31", table) is None


def test_rates_are_read_from_yaml_in_date_order(tmp_path):
    path = tmp_path / "fx.yml"
    path.write_text("rates:\n"
                    "  - since: 2026-11-01\n    yen_per_usd: 159\n"
                    "  - since: 2026-01-01\n    yen_per_usd: 155\n", encoding="utf-8")
    assert load_rates(path) == [("2026-01-01", 155.0), ("2026-11-01", 159.0)]


def test_missing_rate_file_means_no_conversion(tmp_path):
    assert load_rates(tmp_path / "absent.yml") == []


def test_project_rate_table_is_readable():
    assert load_rates(), "config/fx.yml пуст — суммы в выпусках пойдут без долларов"
