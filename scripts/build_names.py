"""Первичное наполнение data/names.json из вышедших выпусков."""
import collections
import glob
import json
import re
from pathlib import Path

CJK = r"[぀-ヿ㐀-䶿一-鿿]"
NAME = re.compile(r"([А-ЯЁ][а-яё]+(?:-[а-яё]+)?)\s*\(([^()]*)\)")
ROMAJI = re.compile(r"romaji:\s*([A-Za-z]+)")
# Закреплено в спецификации и правилах линтера — это и есть сверенные имена.
PINNED = {"Аонишики", "Асасуирю", "Асакорю", "Фуджинокава", "Танджи", "Дайейшо",
          "Вакатакакаге", "Тошинофуджи", "Точитайкай", "Кагаяки", "Котодзакура",
          "Котоэйхо", "Набатаме", "Хошорю", "Терунофуджи", "Оносато", "Такеруфуджи",
          "Хакуохо", "Атамифуджи", "Ичиямомото"}

# Канонические имена линтера — то, что уже прошло через спецификацию
# и руководство. Правые части автозамен сюда не годятся: часть из них —
# основы («Точитайка»), чтобы правило ловило падежи.
import yaml  # noqa: E402

RULES = yaml.safe_load(Path("config/translit_rules.yml").read_text(encoding="utf-8"))
PINNED_FORMS = set(RULES.get("canonical_names", []))

forms: dict[str, collections.Counter] = {}
notes: dict[str, str] = {}
issues: dict[str, set] = {}
roles: dict[str, collections.Counter] = {}
romaji: dict[str, collections.Counter] = {}

for path in sorted(glob.glob("data/issues/*.json")):
    issue = json.load(open(path, encoding="utf-8"))
    text = " ".join([issue["lead"], issue.get("missed", "")]
                    + [b["subtitle"] + " " + b["body"] for b in issue["blocks"]])
    for match in NAME.finditer(text):
        name, inside = match.group(1), match.group(2)
        # Пометка «romaji: Kotozakura» и иероглифы 琴桜 приходят в разных
        # выпусках и про одно имя: связывает их русское написание. Поэтому
        # пометка запоминается раньше проверки на иероглифы.
        note = ROMAJI.search(inside)
        if note:
            notes.setdefault(name, note.group(1))
        kanji = re.findall(rf"{CJK}+", inside)
        if not kanji:
            continue
        key = kanji[0]
        # «元小結旭豊» и «立浪親方» — не написание имени, а описание: в скобках
        # после имени им не место, и ключом словаря они быть не могут.
        if key.startswith("元") or "親方" in key:
            continue
        forms.setdefault(key, collections.Counter())[name] += 1
        issues.setdefault(key, set()).add(issue["issue_date"])
        before = text[max(0, match.start() - 30):match.start()].lower()
        roles.setdefault(key, collections.Counter())[
            "oyakata" if "ояката" in before else "rikishi"] += 1
        if note:
            romaji.setdefault(key, collections.Counter())[note.group(1)] += 1

def pinned(ru: str) -> str:
    """Закреплённая форма имени, если выпуски дали склонённую или иную.

    «Точитайкаю» из одного выпуска против «Точитайкай» из спецификации —
    права спецификация.
    """
    for form in PINNED_FORMS:
        if form == ru:
            return ru
        if len(form) >= 6 and (ru.startswith(form[:-1]) or form.startswith(ru[:-1])):
            return form
    return ru


def same_name(one: str, other: str) -> bool:
    """Одно ли это имя с точностью до падежа: «Котодзакуру» и «Котодзакура»."""
    stem = min(len(one), len(other)) - 1
    return stem >= 6 and one[:stem] == other[:stem]


def nominative(counter: collections.Counter) -> str:
    """Именительный падеж из встреченных форм.

    Склоняются только имена на -а (Киришима, Гонояма): у остальных все формы
    совпадают. Поэтому основа плюс «а», если такая форма в выпусках была.
    """
    variants = list(counter)
    if len(variants) == 1:
        return variants[0]
    stem = variants[0]
    for form in variants[1:]:
        while not form.startswith(stem):
            stem = stem[:-1]
    return stem + "а" if stem + "а" in counter else counter.most_common(1)[0][0]

names = {}
for kanji in sorted(forms, key=lambda k: (-len(issues[k]), -sum(forms[k].values()))):
    ru = pinned(nominative(forms[kanji]))
    # Романизация: из пометки при этом же ключе, иначе — из пометки при любой
    # форме этого имени в любом выпуске.
    known = (romaji[kanji].most_common(1)[0][0] if kanji in romaji else
             next((rom for form, rom in notes.items() if same_name(form, ru)), ""))
    names[kanji] = {
        "ru": ru,
        "romaji": known,
        "role": roles[kanji].most_common(1)[0][0],
        # Сверено — то, что закреплено в спецификации, и то, что совпало
        # в трёх и более выпусках подряд. Остальное ждёт глаз владельца.
        "verified": ru in PINNED or len(issues[kanji]) >= 3,
    }

Path("data/names.json").write_text(json.dumps({
    "note": ("Словарь имён: кандзи → написание. Наполнен из вышедших выпусков "
             "(scripts/build_names.py), дальше правится руками. verified: true — "
             "сверено владельцем или закреплено в спецификации; false — написание "
             "взято из выпусков и ждёт проверки, в тексте такое имя идёт со знаком «?»."),
    "names": names,
}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(f"имён: {len(names)}, сверенных: {sum(1 for v in names.values() if v['verified'])}")
