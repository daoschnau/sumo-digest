"""Сайт: индекс, страницы выпусков, Atom-фид. Без сети, на выдуманных выпусках."""

import xml.etree.ElementTree as ET

import pytest

from sumo_digest.render import day, load_issues, render_site, stamp

ATOM = {"a": "http://www.w3.org/2005/Atom"}


def issue(issue_date: str, lead: str, failed: str | None = None) -> dict:
    sources_reviewed = [{"name": "Hochi News", "status": "ok", "articles_used": 2}]
    if failed:
        sources_reviewed.append({"name": failed, "status": "failed", "articles_used": 0})
    return {
        "issue_date": issue_date,
        "period": {"from": "2026-09-07", "to": issue_date},
        "sources_reviewed": sources_reviewed,
        "lead": lead,
        "blocks": [{
            "date": issue_date,
            "place": "Рёгоку Кокугикан",
            "subtitle": "Хошорю пропустит Аки Басё",
            "body": "Ёкодзуна Хошорю (豊昇龍) не восстановился после операции на колене.",
            "category": "injury",
            "importance": 5,
            "source_ids": ["a001"],
            "sources": [{"name": "Hochi News",
                         "url": "https://hochi.news/articles/20260910-OHT1T51188.html"}],
        }],
        "missed": "Слухи о смене оякаты.",
        "quiet_period": False,
    }


@pytest.fixture
def site(tmp_path):
    issues = [issue("2026-09-10", "Главное за период — травмы лидеров.", failed="NHK"),
              issue("2026-09-07", "Опубликовано бандзуке на Аки Басё."),
              issue("2026-09-03", "Спокойный период без турниров.")]
    render_site(issues, tmp_path, base_url="https://example.test/")
    return tmp_path


def test_every_issue_gets_its_own_page(site):
    for issue_date in ("2026-09-10", "2026-09-07", "2026-09-03"):
        assert (site / issue_date / "index.html").exists()


def test_index_lists_issues_newest_first(site):
    html = (site / "index.html").read_text(encoding="utf-8")
    positions = [html.index(f'href="{d}/"') for d in ("2026-09-10", "2026-09-07", "2026-09-03")]
    assert positions == sorted(positions)


def test_index_carries_the_ai_disclaimer(site):
    """Требование §6.1 спецификации: читатель должен знать, что выпуск готовит ИИ."""
    # Переносы строк в шаблоне не должны ломать проверку текста.
    html = " ".join((site / "index.html").read_text(encoding="utf-8").split())
    assert "Выпуски готовит ИИ" in html
    assert "важные факты лучше сверять с оригиналом" in html
    assert "без ручной редактуры" in html


def test_issue_page_keeps_kanji_and_links_to_the_source(site):
    html = (site / "2026-09-10" / "index.html").read_text(encoding="utf-8")
    assert "豊昇龍" in html
    assert 'href="https://hochi.news/articles/20260910-OHT1T51188.html"' in html
    assert "Мимо кассы" in html


def test_unavailable_source_is_named_in_the_period_line(site):
    """Спецификация требует показывать, какие источники не открылись."""
    html = (site / "2026-09-10" / "index.html").read_text(encoding="utf-8")
    assert "не открылись: NHK" in html


def test_feed_is_well_formed_atom(site):
    root = ET.parse(site / "feed.xml").getroot()
    assert root.tag == "{http://www.w3.org/2005/Atom}feed"
    for tag in ("title", "id", "updated"):
        assert root.find(f"a:{tag}", ATOM) is not None
    assert root.find("a:link[@rel='self']", ATOM) is not None

    entries = root.findall("a:entry", ATOM)
    assert len(entries) == 3
    for entry in entries:
        for tag in ("title", "id", "updated", "content"):
            assert entry.find(f"a:{tag}", ATOM) is not None
        assert entry.find("a:link", ATOM).get("href").startswith("https://example.test/")


def test_feed_content_carries_the_whole_issue(site):
    entry = ET.parse(site / "feed.xml").getroot().find("a:entry", ATOM)
    content = entry.find("a:content", ATOM).text
    assert "Хошорю пропустит Аки Басё" in content
    assert "hochi.news" in content
    assert "Мимо кассы" in content


def test_pages_are_not_run_through_jekyll(site):
    assert (site / ".nojekyll").exists()


def test_style_is_copied_next_to_the_pages(site):
    assert (site / "style.css").exists()
    assert "Noto Sans JP" in (site / "style.css").read_text(encoding="utf-8")


def test_dates_are_written_the_way_a_reader_reads_them():
    assert day("2026-09-10") == "10 сентября 2026"
    assert stamp("2026-09-10") == "2026-09-10T00:00:00Z"


def test_empty_archive_renders_nothing(tmp_path):
    assert load_issues(tmp_path / "нет-такой-папки") == []


def test_relint_carries_a_new_rule_into_the_published_archive(tmp_path):
    """Правило, добавленное сегодня, должно доехать и до вчерашних выпусков."""
    import json

    from sumo_digest.render import relint_archive

    archive = tmp_path / "issues"
    archive.mkdir()
    stale = issue("2026-09-10", "Одзэки Даиешо провёл схватку.")
    stale["blocks"][0]["body"] = "Маегашира Вакатакаге снялся с турнира."
    (archive / "2026-09-10.json").write_text(json.dumps(stale, ensure_ascii=False),
                                             encoding="utf-8")

    changed = relint_archive(archive)
    assert changed and changed[0][0] == "2026-09-10.json"
    assert changed[0][1], "замены обязаны попасть в отчёт"

    fixed = json.loads((archive / "2026-09-10.json").read_text(encoding="utf-8"))
    assert "Дайейшо" in fixed["lead"] and "Даиешо" not in fixed["lead"]
    assert "Вакатакакаге" in fixed["blocks"][0]["body"]


def test_relint_leaves_a_clean_archive_alone(tmp_path):
    import json

    from sumo_digest.render import relint_archive

    archive = tmp_path / "issues"
    archive.mkdir()
    (archive / "2026-09-07.json").write_text(
        json.dumps(issue("2026-09-07", "Озеки Киришима готов к Аки Басё."),
                   ensure_ascii=False), encoding="utf-8")
    assert relint_archive(archive) == []


def test_relint_reorders_an_archive_written_under_the_old_rule(tmp_path):
    """Порядок блоков — тоже правило: архив переезжает на него вместе с текстом."""
    import json

    from sumo_digest.render import relint_archive

    archive = tmp_path / "issues"
    archive.mkdir()
    stale = issue("2026-09-10", "Главное за период — травмы лидеров.")
    minor = json.loads(json.dumps(stale["blocks"][0]))
    minor.update(subtitle="Дебют в дзюрё", category="banzuke", importance=2)
    stale["blocks"] = [minor, stale["blocks"][0]]
    (archive / "2026-09-10.json").write_text(json.dumps(stale, ensure_ascii=False),
                                             encoding="utf-8")

    name, fixes, reordered = relint_archive(archive)[0]
    assert reordered and not fixes

    fixed = json.loads((archive / "2026-09-10.json").read_text(encoding="utf-8"))
    assert fixed["blocks"][0]["importance"] == 5
