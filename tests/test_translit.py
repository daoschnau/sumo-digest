"""Линтер транслитерации. Таблица «на входе — на выходе» из §3.4 спецификации."""

import pytest

from sumo_digest.models import Article, Corpus
from sumo_digest.translit import distance, lint_digest, lint_text, load_rules
from sumo_digest.validate import ValidationFailed, validate


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
    assert any("latin_inside_cyrillic" in problem for problem in report.rejects)


def test_the_romaji_note_from_the_spec_is_allowed(rules):
    _, report = lint_text("Имя (romaji: Kotonofuji — требует проверки) уточняется.", rules)
    assert not report.rejects


def test_macron_and_stress_marks_are_rejected(rules):
    assert lint_text("Ōnosato вышел", rules)[1].rejects
    assert lint_text("Хана́да провёл", rules)[1].rejects


def test_hepburn_left_in_latin_is_rejected(rules):
    _, report = lint_text("Титул yokozuna остался за ним.", rules)
    assert any("stable_hepburn_leak" in problem for problem in report.rejects)


def test_near_canonical_name_only_warns(rules):
    _, report = lint_text("Борец Хошору вышел на дохё.", rules)
    assert any("похоже на опечатку" in note for note in report.warnings)
    assert not report.rejects  # предупреждение публикацию не блокирует


def test_correct_text_produces_nothing(rules):
    text = ("Озеки Киришима из Тацунами-бея готовится к Аки Басё; "
            "ояката оценил состояние подопечного, бандзуке уже вышло.")
    fixed, report = lint_text(text, rules)
    assert fixed == text
    assert not report.fixes and not report.rejects and not report.warnings


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


def test_rejection_stops_the_whole_issue():
    """Уровень 3 обязан ронять выпуск целиком, а не помечать блок."""
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
    with pytest.raises(ValidationFailed, match="stable_hepburn_leak"):
        validate(digest, corpus)


def test_distance_is_a_real_edit_distance():
    assert distance("Хошорю", "Хошорю") == 0
    assert distance("Хошору", "Хошорю") == 1
    assert distance("", "Охо") == 3
