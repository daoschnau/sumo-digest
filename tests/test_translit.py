"""Линтер транслитерации. Таблица «на входе — на выходе» из §3.4 спецификации."""

import pytest

from sumo_digest.models import Article, Corpus
from sumo_digest.translit import (
    distance,
    lint_digest,
    lint_text,
    load_rules,
    read_field,
    write_field,
)
from sumo_digest.validate import validate


@pytest.fixture(scope="module")
def rules() -> dict:
    return load_rules()


@pytest.mark.parametrize("wrong, right", [
    ("одзэки", "озеки"),
    ("Одзэки", "Озеки"),
    ("хэя", "бейя"),
    ("сэкивакэ", "секиваке"),
    ("маэгасира", "маегашира"),
    ("банзукэ", "бандзуке"),
    ("сисё", "ояката"),
    ("макусита", "макушита"),
    ("Хосёрю", "Хошорю"),
    ("Терунофудзи", "Терунофуджи"),
    ("Аонисики", "Аонишики"),
    ("Тандзи", "Танджи"),
    ("хариматэ", "харитэ"),
    ("Даиешо", "Дайейшо"),
    ("Дайэйшо", "Дайейшо"),
    ("Вакатакаге", "Вакатакакаге"),
    ("аматорское сумо", "любительское сумо"),
])
def test_known_errors_are_fixed(wrong, right, rules):
    fixed, report = lint_text(f"В тексте {wrong} встречается.", rules)
    assert right in fixed
    assert wrong not in fixed
    assert (wrong, right, 1) in report.fixes


def test_beya_suffix_keeps_its_own_form(rules):
    """«хэя» отдельно — «бейя», в составе имени — «-бея» (§3.3)."""
    fixed, _ = lint_text("Тацунами-хэя и просто хэя.", rules)
    assert "Тацунами-бея" in fixed
    assert "просто бейя" in fixed


def test_retired_wrestler_name_is_corrected_to_the_active_one(rules):
    """Asasekiryu ушёл в 2017-м; модель так романизирует действующего Асакорю."""
    fixed, _ = lint_text("Асасекирю выиграл схватку.", rules)
    assert fixed == "Асакорю выиграл схватку."


def test_every_fix_is_logged(rules):
    text = "Одзэки в Тацунами-хэя: банзукэ, сисё, Хосёрю."
    _, report = lint_text(text, rules)
    assert len(report.fixes) == 5
    assert all(count >= 1 for _, _, count in report.fixes)


def test_latin_inside_a_cyrillic_name_is_rejected(rules):
    _, report = lint_text("Борец Хошорюsan вышел на дохё.", rules)
    assert any(problem.rule == "latin_inside_cyrillic" for problem in report.problems)


def test_latin_beyond_ascii_inside_a_cyrillic_name_is_rejected(rules):
    """«Спониči» в выпуске 10.09.2026 прошёл мимо правила: «č» — не [A-Za-z]."""
    _, report = lint_text("По данным Хоči, схватка состоялась.", rules)
    assert any(problem.rule == "latin_inside_cyrillic" for problem in report.problems)


def test_the_publication_name_is_fixed_before_it_reaches_the_reader(rules):
    fixed, report = lint_text("По данным Спониči, 19 побед.", rules)
    assert fixed == "По данным Споничи, 19 побед."
    assert not report.problems


def test_the_romaji_note_from_the_spec_is_allowed(rules):
    _, report = lint_text("Имя (romaji: Kotonofuji — требует проверки) уточняется.", rules)
    assert not report.problems


def test_macron_and_stress_marks_are_rejected(rules):
    assert lint_text("Ōnosato вышел", rules)[1].problems
    assert lint_text("Хана́да провёл", rules)[1].problems


def test_hepburn_left_in_latin_is_rejected(rules):
    _, report = lint_text("Титул yokozuna остался за ним.", rules)
    assert any(problem.rule == "stable_hepburn_leak" for problem in report.problems)


def test_near_canonical_name_only_warns(rules):
    _, report = lint_text("Борец Хошору вышел на дохё.", rules)
    assert any("похоже на опечатку" in note for note in report.warnings)
    assert not report.problems  # предупреждение публикацию не блокирует


def test_correct_text_produces_nothing(rules):
    text = ("Озеки Киришима из Тацунами-бея готовится к Аки Басё; "
            "ояката оценил состояние подопечного, бандзуке уже вышло.")
    fixed, report = lint_text(text, rules)
    assert fixed == text
    assert not report.fixes and not report.problems and not report.warnings


def test_digest_is_fixed_field_by_field(rules):
    digest = {
        "lead": "Одзэки Киришима готов.",
        "missed": "Слухи про хэя.",
        "blocks": [{"subtitle": "Хосёрю кюдзё", "body": "Банзукэ вышло.", "place": "Осака"}],
    }
    fixed, report = lint_digest(digest, rules)
    assert fixed["lead"].startswith("Озеки")
    assert "бейя" in fixed["missed"]
    assert fixed["blocks"][0]["subtitle"].startswith("Хошорю")
    assert len(report.fixes) >= 3


def test_transliteration_problem_does_not_kill_the_issue():
    """Написание — не факты. Выпуск без дайджеста хуже дайджеста с огрехом."""
    corpus = Corpus(period_from="2026-09-07", period_to="2026-09-10", articles=[
        Article(id="a001", source_id="hochi", source_name="Hochi News",
                url="https://hochi.news/articles/20260910-OHT1T51188.html",
                title="t", text="x" * 300, published="2026-09-10")])
    digest = {
        "issue_date": "2026-09-10",
        "period": {"from": "2026-09-07", "to": "2026-09-10"},
        "sources_reviewed": [{"name": "Hochi News", "status": "ok"}],
        "lead": "Ёкодзуна yokozuna остался за скобками этого выпуска целиком.",
        "blocks": [{"subtitle": "Заголовок блока", "body": "Текст блока. " * 10,
                    "category": "other", "importance": 1, "source_ids": ["a001"]}],
        "missed": "",
        "quiet_period": True,
    }
    checked, report = validate(digest, corpus)
    assert checked["blocks"], "выпуск обязан дойти до публикации"
    assert any(problem.rule == "stable_hepburn_leak" for problem in report.problems)
    assert not report.clean, "замечание обязано остаться видимым в отчёте"


def test_distance_is_a_real_edit_distance():
    assert distance("Хошорю", "Хошорю") == 0
    assert distance("Хошору", "Хошорю") == 1
    assert distance("", "Охо") == 3


def test_problem_points_at_the_field_it_came_from(rules):
    digest = {"lead": "Всё в порядке.",
              "blocks": [{"subtitle": "Заголовок", "body": "Титул yokozuna остался."}]}
    _, report = lint_digest(digest, rules)
    assert [p.where for p in report.problems] == ["blocks[0].body"]
    assert list(report.by_field()) == ["blocks[0].body"]


def test_field_path_round_trips(rules):
    digest = {"lead": "текст", "blocks": [{"body": "было"}, {"body": "тоже было"}]}
    assert read_field(digest, "blocks[1].body") == "тоже было"
    write_field(digest, "blocks[1].body", "стало")
    assert digest["blocks"][1]["body"] == "стало"
    write_field(digest, "lead", "новое")
    assert read_field(digest, "lead") == "новое"


def test_correct_name_is_not_broken_by_the_rule_that_fixes_it(rules):
    """«Вакатакаге» → «Вакатакакаге» не должно превращать верное в «Вакатакакакаге»."""
    fixed, report = lint_text("Вакатакакаге снялся с турнира.", rules)
    assert fixed == "Вакатакакаге снялся с турнира."
    assert not report.fixes


@pytest.mark.parametrize("text", [
    "Макуутский Вакатакакаге снялся с турнира.",
    "Схватка с макуутским Чиёшомой прошла ровно.",
    "Дзюрёвский дебютант выиграл.",
    "Бандзукское решение объявили в понедельник.",
])
def test_terms_turned_into_adjectives_are_flagged(text, rules):
    """«Макуутский Икс» — это не по-русски и не по спецификации."""
    _, report = lint_text(text, rules)
    assert any(problem.rule == "term_as_adjective" for problem in report.problems)


@pytest.mark.parametrize("text", [
    "Вакатакакаге из макуути снялся с турнира.",
    "Схватка с маегаширой Хирадоуми прошла ровно.",
    "Киришима готовится к заявке на ёкодзунское звание.",
    "Озеки Оносато провёл тренировку в Сакаигава-бея.",
])
def test_correct_noun_forms_pass(text, rules):
    """Единственное устоявшееся исключение — «ёкодзунское звание»."""
    _, report = lint_text(text, rules)
    assert not report.problems


def test_adjective_is_not_autofixed_but_handed_to_the_repair_pass(rules):
    """Порядок слов заменой не чинится — правит модель, выпуск при этом выходит."""
    fixed, report = lint_text("Макуутский Вакатакакаге снялся.", rules)
    assert fixed == "Макуутский Вакатакакаге снялся."
    assert not report.fixes
    assert report.problems
