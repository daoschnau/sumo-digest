"""Первичное наполнение data/glossary.json из вышедших выпусков.

Модель поясняет термин в квадратных скобках при первом упоминании в блоке,
и до 30.09.2026 писала эти пояснения заново каждый раз: у ёрикири набралось
три определения, у уватенаге — четыре, часть в косвенном падеже («броском
через руку»), часть оборвана («катасукаши — подсечк»). Скрипт собирает, что
уже было, и выбирает лучшее; дальше файл правится руками.
"""

import collections
import glob
import json
import re
from pathlib import Path

GLOSS = re.compile(r"([^\s\[\]()]+)[  ]?\[([^\[\]]{2,80})\]")
EDGES = " ,.;:!?«»\"'—–-"
# Косвенный падеж в первом слове: «броском через руку» вместо «бросок».
OBLIQUE = ("ом", "ой", "ем", "ою", "ами", "ах", "у", "ю", "е")


def score(definition: str, times: int) -> tuple:
    """Чем определение лучше: именительный падеж, целость, частота, длина.

    Падеж первее частоты: «броском через руку» встречалось чаще всех, но это
    определение, списанное из фразы, а не словарная статья.
    """
    first = definition.split()[0] if definition.split() else ""
    nominative = not first.endswith(OBLIQUE)
    # Оборванное слово в конце («подсечк») — почти всегда обрыв по длине.
    whole = not definition.rstrip().endswith(("к", "ч", "щ")) or len(definition) > 20
    return (nominative, whole, times, len(definition))


terms: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
for path in sorted(glob.glob("data/issues/*.json")):
    issue = json.load(open(path, encoding="utf-8"))
    text = " ".join([issue["lead"], issue.get("missed", "")]
                    + [b["subtitle"] + " " + b["body"] for b in issue["blocks"]])
    for term, definition in GLOSS.findall(text):
        key = term.strip(EDGES).casefold()
        if key:
            terms[key][definition.strip()] += 1

chosen = {}
for term in sorted(terms):
    best = max(terms[term].items(), key=lambda kv: score(kv[0], kv[1]))[0]
    chosen[term] = best

Path("data/glossary.json").write_text(json.dumps({
    "note": ("Словарь терминов: термин → определение в именительном падеже. "
             "Один термин — одно определение на все выпуски. Наполнен из вышедших "
             "выпусков (scripts/build_glossary.py), дальше правится руками. "
             "Рендерер берёт определение отсюда; пояснение, которое написала "
             "модель, идёт в дело только для терминов, которых здесь нет, "
             "и такой термин попадает в отчёт прогона как кандидат в словарь."),
    "terms": chosen,
}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(f"терминов: {len(chosen)}")
for term in list(chosen)[:8]:
    print(f"   {term} — {chosen[term]}")
