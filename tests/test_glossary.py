"""Словарь терминов: одно определение на все выпуски."""

import json

import pytest

from sumo_digest.glossary import definition, load_glossary


@pytest.fixture
def terms(tmp_path):
    path = tmp_path / "glossary.json"
    path.write_text(json.dumps({"note": "тест", "terms": {
        "ёрикири": "выталкивание в захвате",
        "Тачиай": "начальный сход",
    }}, ensure_ascii=False), encoding="utf-8")
    return load_glossary(path)


def test_terms_are_read_in_lower_case(terms):
    assert terms["тачиай"] == "начальный сход"


def test_missing_file_is_not_an_error(tmp_path):
    assert load_glossary(tmp_path / "нет.json") == {}


def test_lookup_ignores_case(terms):
    assert definition("Ёрикири", terms) == "выталкивание в захвате"
    assert definition("хенка", terms) is None
