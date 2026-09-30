"""Словарь имён: чтение, поиск по романизации, блок для промпта."""

import json

import pytest

from sumo_digest.names import as_prompt, by_romaji, canonical_names, load_names

DICTIONARY = {
    "note": "тест",
    "names": {
        "大の里": {"ru": "Оносато", "romaji": "Onosato", "role": "rikishi", "verified": True},
        "隆の勝": {"ru": "Таканошо", "romaji": "Takanosho", "role": "rikishi",
                 "verified": False},
        "立浪": {"ru": "Тацунами", "romaji": "", "role": "oyakata", "verified": True},
    },
}


@pytest.fixture
def names(tmp_path):
    path = tmp_path / "names.json"
    path.write_text(json.dumps(DICTIONARY, ensure_ascii=False), encoding="utf-8")
    return tuple(load_names(path))


def test_entries_are_read_with_their_flags(names):
    onosato = next(name for name in names if name.kanji == "大の里")
    assert (onosato.ru, onosato.romaji, onosato.verified) == ("Оносато", "Onosato", True)


def test_missing_file_is_not_an_error(tmp_path):
    """Без словаря пайплайн работает как раньше, а не падает."""
    assert load_names(tmp_path / "нет.json") == []


def test_romaji_lookup_is_case_insensitive_and_skips_empty(names):
    known = by_romaji(names)
    assert known["takanosho"].kanji == "隆の勝"
    assert "" not in known, "имя без романизации в поиск не попадает"


def test_canonical_names_feed_the_linter(names):
    assert canonical_names(names) == ["Оносато", "Таканошо", "Тацунами"]


def test_prompt_block_lists_names_and_explains_the_gap(names):
    block = as_prompt(names)
    assert "大の里 — Оносато (Onosato)" in block
    assert "立浪 — Тацунами" in block
    assert "new_terms" in block, "модель должна знать, что делать с именем не из списка"


def test_an_empty_dictionary_adds_no_prompt_block():
    assert as_prompt(()) == ""
