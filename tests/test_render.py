"""Сайт: индекс, страницы выпусков, Atom-фид. Без сети, на выдуманных выпусках."""

import json
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


def test_custom_domain_gets_a_cname_file(tmp_path):
    render_site([issue("2026-09-10", "Главное за период.")], tmp_path,
                base_url="https://sumodigest.online/")
    assert (tmp_path / "CNAME").read_text(encoding="utf-8").strip() == "sumodigest.online"


def test_github_io_address_does_not_get_a_cname_file(tmp_path):
    """CNAME с github.io ломает Pages: домен обязан быть собственным."""
    render_site([issue("2026-09-10", "Главное за период.")], tmp_path,
                base_url="https://daoschnau.github.io/sumo-digest/")
    assert not (tmp_path / "CNAME").exists()


def test_feed_links_point_at_the_custom_domain(tmp_path):
    import xml.etree.ElementTree as ET

    render_site([issue("2026-09-10", "Главное за период.")], tmp_path,
                base_url="https://sumodigest.online/")
    entry = ET.parse(tmp_path / "feed.xml").getroot().find("a:entry", ATOM)
    assert entry.find("a:id", ATOM).text == "https://sumodigest.online/2026-09-10/"


def test_single_day_period_is_printed_once(tmp_path):
    """«10 сентября 2026–10 сентября 2026» — дата, продублированная сама с собой."""
    one_day = issue("2026-09-10", "Главное за период.")
    one_day["period"] = {"from": "2026-09-10", "to": "2026-09-10"}
    render_site([one_day], tmp_path, base_url="https://example.test/")

    period = " ".join((tmp_path / "2026-09-10" / "index.html").read_text(
        encoding="utf-8").split())
    assert "10 сентября 2026 · просмотрено" in period
    assert "10 сентября 2026–10 сентября 2026" not in period


def test_period_of_several_days_keeps_both_dates(site):
    html = " ".join((site / "2026-09-10" / "index.html").read_text(
        encoding="utf-8").split())
    assert "7 сентября 2026–10 сентября 2026" in html


def test_block_date_equal_to_the_issue_date_is_not_repeated(site):
    """Семь блоков за день выпуска — семь одинаковых строк с датой."""
    html = (site / "2026-09-10" / "index.html").read_text(encoding="utf-8")
    assert '<p class="block-date">Рёгоку Кокугикан</p>' in html
    assert "10 сентября 2026 · Рёгоку Кокугикан" not in html


def test_block_date_is_printed_when_the_event_is_older_than_the_issue(tmp_path):
    earlier = issue("2026-09-10", "Главное за период.")
    earlier["blocks"][0]["date"] = "2026-09-09"
    render_site([earlier], tmp_path, base_url="https://example.test/")

    html = (tmp_path / "2026-09-10" / "index.html").read_text(encoding="utf-8")
    assert "9 сентября 2026 · Рёгоку Кокугикан" in html


def test_block_without_date_and_place_gets_no_empty_line(tmp_path):
    bare = issue("2026-09-10", "Главное за период.")
    bare["blocks"][0].pop("date")
    bare["blocks"][0].pop("place")
    render_site([bare], tmp_path, base_url="https://example.test/")

    html = (tmp_path / "2026-09-10" / "index.html").read_text(encoding="utf-8")
    assert 'class="block-date"' not in html


def test_unverified_spelling_becomes_a_mark_instead_of_a_phrase(tmp_path):
    """«— требует проверки» посреди фразы встречается в выпуске до восьми раз."""
    noted = issue("2026-09-10", "Главное за период.")
    noted["blocks"][0]["body"] = ("Ояката Арашио (元幕内蒼国来, romaji: Sokokurai "
                                  "— требует проверки) подтвердил снятие.")
    render_site([noted], tmp_path, base_url="https://example.test/")

    html = (tmp_path / "2026-09-10" / "index.html").read_text(encoding="utf-8")
    assert "требует проверки)" not in html
    assert "元幕内蒼国来, Sokokurai" in html, "иероглифы и романизация остаются"
    assert 'class="unverified"' in html
    assert "транслитерация не сверена" in html, "внизу страницы нужна расшифровка знака"


def test_the_mark_legend_is_absent_when_everything_is_verified(site):
    html = (site / "2026-09-10" / "index.html").read_text(encoding="utf-8")
    assert "транслитерация не сверена" not in html


def test_terms_are_explained_below_the_text_not_inside_it(tmp_path):
    """Два пояснения подряд рвут абзац на куски даже приглушённые."""
    termed = issue("2026-09-10", "Главное за период.")
    termed["blocks"][0]["body"] = ("Дело ограничивается шико [упражнение с подъёмом "
                                   "ноги] и грудью в буцукари-гейко [упражнение "
                                   "на выталкивание].")
    render_site([termed], tmp_path, base_url="https://example.test/")

    html = (tmp_path / "2026-09-10" / "index.html").read_text(encoding="utf-8")
    assert "ограничивается шико и грудью в буцукари-гейко." in html
    assert "<dt>шико</dt> <dd>— упражнение с подъёмом ноги</dd>" in html
    assert "<dt>буцукари-гейко</dt>" in html


def test_a_term_repeated_in_two_blocks_gets_one_glossary_line(tmp_path):
    """Модель поясняет термин в каждом блоке — внизу он нужен один раз."""
    repeated = issue("2026-09-10", "Главное за период.")
    second = json.loads(json.dumps(repeated["blocks"][0]))
    repeated["blocks"][0]["body"] = "Жёсткость тачиай [начальный сход] была хуже."
    second["subtitle"] = "Аонишики закрыл подготовку"
    second["body"] = "На тачиай [начальный сход] он снова опоздал."
    second["importance"] = 4
    repeated["blocks"].append(second)
    render_site([repeated], tmp_path, base_url="https://example.test/")

    html = (tmp_path / "2026-09-10" / "index.html").read_text(encoding="utf-8")
    assert html.count("начальный сход") == 1
    assert html.count("тачиай") == 3, "термин в двух блоках плюс строка глоссария"


def test_an_issue_without_terms_gets_no_glossary(site):
    html = (site / "2026-09-10" / "index.html").read_text(encoding="utf-8")
    assert "Термины" not in html


def test_a_term_with_punctuation_before_the_bracket_is_read_correctly(tmp_path):
    odd = issue("2026-09-10", "Главное за период.")
    odd["blocks"][0]["body"] = "Помешал тачиай, [начальный сход] вышел рваным."
    render_site([odd], tmp_path, base_url="https://example.test/")

    html = (tmp_path / "2026-09-10" / "index.html").read_text(encoding="utf-8")
    assert "<dt>тачиай</dt>" in html, "запятая не должна попасть в термин"
    assert "Помешал тачиай, вышел рваным." in html


def test_the_feed_keeps_the_text_the_model_wrote(tmp_path):
    """Вёрстка страницы — не правка выпуска: в данных и в фиде текст исходный."""
    noted = issue("2026-09-10", "Главное за период.")
    noted["blocks"][0]["body"] = ("Маегашира Аби (阿炎, romaji: Abi — требует проверки) "
                                  "проиграл тачиай [начальный сход].")
    render_site([noted], tmp_path, base_url="https://example.test/")

    content = ET.parse(tmp_path / "feed.xml").getroot().find(
        "a:entry/a:content", ATOM).text
    assert "romaji: Abi — требует проверки" in content
    assert "[начальный сход]" in content
    assert noted["blocks"][0]["body"].startswith("Маегашира Аби (阿炎, romaji:")


def test_index_puts_the_issues_above_the_explanations(site):
    """За выпуском приходят каждый раз, преамбулу читают один."""
    html = (site / "index.html").read_text(encoding="utf-8")
    assert html.index('href="2026-09-10/"') < html.index("Выпуски готовит ИИ")


def test_japanese_spelling_is_set_apart_from_the_sentence(site):
    """Иероглиф в одном кегле с кириллицей перетягивает внимание на себя."""
    html = (site / "2026-09-10" / "index.html").read_text(encoding="utf-8")
    assert '<span class="aside">(豊昇龍)</span>' in html


def test_an_ordinary_parenthesis_stays_ordinary(tmp_path):
    plain = issue("2026-09-10", "Главное за период.")
    plain["blocks"][0]["body"] = ("Хошорю (豊昇龍) перенёс операцию на колене "
                                  "(частичный разрыв) 29 июля.")
    render_site([plain], tmp_path, base_url="https://example.test/")

    html = (tmp_path / "2026-09-10" / "index.html").read_text(encoding="utf-8")
    assert "колене (частичный разрыв) 29 июля" in html
    assert '<span class="aside">(豊昇龍)</span>' in html


def test_the_issue_link_is_the_loudest_thing_on_the_index(site):
    """Единственное действие страницы не может быть тише ссылки на фид."""
    css = (site / "style.css").read_text(encoding="utf-8")
    assert ".issues li > a" in css
    html = (site / "index.html").read_text(encoding="utf-8")
    assert "<details>" in html, "дисклеймер свёрнут, а не обведён рамкой"
    assert 'class="note"' not in html
