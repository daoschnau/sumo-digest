"""Приёмка §7.3: каждый машинный пункт обязан уметь провалиться."""

import copy

import pytest

from sumo_digest.acceptance import allowed_hosts, check_issue

GOOD_URL = "https://hochi.news/articles/20260910-OHT1T51188.html"


def result(issue: dict, item_prefix: str):
    for check in check_issue(issue):
        if check.item.startswith(item_prefix):
            return check
    raise AssertionError(f"пункта «{item_prefix}» нет в чек-листе")


@pytest.fixture
def issue() -> dict:
    block = {
        "date": "2026-09-10", "place": "Рёгоку Кокугикан",
        "subtitle": "Хошорю пропустит Аки Басё",
        "body": "Ёкодзуна Хошорю (豊昇龍) не восстановился после операции на колене.",
        "category": "injury", "importance": 5, "source_ids": ["a001"],
        "sources": [{"name": "Hochi News", "url": GOOD_URL}],
    }
    blocks = []
    for number in range(5):
        one = copy.deepcopy(block)
        one["source_ids"] = [f"a00{number}"]
        blocks.append(one)
    return {
        "issue_date": "2026-09-10",
        "period": {"from": "2026-09-07", "to": "2026-09-10"},
        "sources_reviewed": [{"name": "Hochi News", "status": "ok", "articles_used": 5}],
        "lead": "Главное за период. Травмы лидеров перед Аки Басё. Киришима готов.",
        "blocks": blocks,
        "missed": "Слухи о смене оякаты.",
        "quiet_period": False,
        "new_terms": [],
    }


def test_a_good_issue_passes_every_machine_check(issue):
    assert all(check.passed is not False for check in check_issue(issue))


def test_link_outside_the_closed_list_fails(issue):
    issue["blocks"][0]["sources"] = [{"name": "Asahi", "url": "https://www.asahi.com/x.html"}]
    check = result(issue, "Все ссылки")
    assert check.passed is False
    assert "asahi" in check.detail


def test_blocks_out_of_order_fail(issue):
    issue["blocks"][0]["category"] = "lower_divisions"
    assert result(issue, "Блоки отсортированы").passed is False


def test_one_article_in_two_blocks_fails(issue):
    issue["blocks"][1]["source_ids"] = issue["blocks"][0]["source_ids"]
    assert result(issue, "Нет дублей").passed is False


def test_missing_missed_section_fails(issue):
    issue["missed"] = ""
    assert result(issue, "Раздел «Мимо кассы»").passed is False


def test_exclamation_marks_fail(issue):
    issue["blocks"][0]["body"] += " Вот это схватка!"
    assert result(issue, "Без восклицательных").passed is False


def test_call_to_subscribe_fails(issue):
    issue["missed"] = "Подпишитесь на рассылку."
    assert result(issue, "Без хэштегов").passed is False


def test_bad_transliteration_fails(issue):
    issue["blocks"][0]["body"] = "Одзэки Хосёрю провёл схватку."
    assert result(issue, "Транслитерация").passed is False


def test_term_as_adjective_fails(issue):
    issue["blocks"][0]["body"] = "Макуутский Вакатакакаге снялся с турнира."
    assert result(issue, "Транслитерация").passed is False


def test_lead_of_one_sentence_fails(issue):
    issue["lead"] = "Одна строчка."
    assert result(issue, "«Главное»").passed is False


def test_too_few_blocks_pass_only_as_quiet_period(issue):
    issue["blocks"] = issue["blocks"][:2]
    assert result(issue, "5–10 блоков").passed is False
    issue["quiet_period"] = True
    assert result(issue, "5–10 блоков").passed is True


def test_issue_without_kanji_fails(issue):
    for block in issue["blocks"]:
        block["body"] = "Ёкодзуна не восстановился после операции."
    assert result(issue, "Имена сопровождаются").passed is False


def test_human_items_are_never_marked_passed(issue):
    human = [check for check in check_issue(issue) if check.passed is None]
    assert len(human) == 4
    assert all(check.detail == "глазами" for check in human)


def test_closed_list_hosts_come_from_the_config():
    hosts = allowed_hosts()
    assert "hochi.news" in hosts, "канонический хост Hochi обязан быть разрешён"
    assert "www.sponichi.co.jp" in hosts
    assert not any("asahi" in host or "nikkei" in host for host in hosts)
