"""Суммы в иенах → примерный эквивалент в долларах, для читателя.

«Ассоциация перечислит префектуре Кумамото 4 784 848 иен» ничего не говорит
тому, кто не держит в голове курс. Пересчёт делает рендерер, а не модель:
у модели нет сети и курса, а арифметику в этом проекте не доверяют тексту.
Данные не меняются — доллары появляются только в вёрстке и в фиде, поэтому
архив получает их при пересборке, и правка курса не трогает JSON выпусков.

Курс берётся на дату выпуска из `config/fx.yml` (см. комментарий там).
"""

from __future__ import annotations

import re
from datetime import date
from functools import lru_cache
from pathlib import Path

import yaml

FX_PATH = Path("config/fx.yml")

SPACE = "[  ]"
MULTIPLIERS = {None: 1, "тыс.": 1_000, "млн": 1_000_000, "млрд": 1_000_000_000}

# «4 784 848 иен», «10 млн иен», «3,3 млн иен», «1,5 млрд йен», «500 тыс. иен».
# Сумма должна стоять отдельным числом (не хвост другого числа) и не иметь уже
# долларового пояснения в скобках сразу за собой — модель иногда пишет его сама.
# Во фразе «с 10 до 20 млн иен» пересчитывается только 20 млн: у 10 нет слова
# «иен», а угадывать, к чему относится число, — не дело регулярки.
YEN = re.compile(
    rf"(?<![\d,])(?P<number>\d{{1,3}}(?:{SPACE}\d{{3}})+|\d+(?:,\d+)?)"
    rf"(?:{SPACE}?(?P<scale>тыс\.|млн|млрд))?"
    rf"{SPACE}(?P<word>[ий]ен)\b"
    rf"(?!{SPACE}*\([^()]*(?:\$|доллар))")


def load_rates(path: Path = FX_PATH) -> list[tuple[str, float]]:
    """(с какой даты, иен за доллар), по возрастанию даты. Нет файла — пусто."""
    if not path.exists():
        return []
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    rates = [(item["since"].isoformat() if isinstance(item["since"], date)
              else str(item["since"]), float(item["yen_per_usd"]))
             for item in raw.get("rates") or []]
    return sorted(rates)


@lru_cache(maxsize=1)
def rates() -> list[tuple[str, float]]:
    """Курсы, прочитанные один раз за прогон."""
    return load_rates()


def rate_on(issue_date: str, table: list[tuple[str, float]] | None = None) -> float | None:
    """Курс на дату выпуска. None — выпуск раньше первой строки таблицы."""
    found = None
    for since, value in table if table is not None else rates():
        if since <= issue_date:
            found = value
    return found


def dollars(amount: float) -> str:
    """30 093.4 → «$30 000»: две значащие цифры, тысячи через неразрывный пробел.

    Точность до доллара при «≈» была бы ложной: курс в таблице округлён
    и обновляется раз в месяцы.
    """
    if amount < 1:
        return "$1"
    rounded = int(float(f"{amount:.2g}"))
    return "$" + f"{rounded:,}".replace(",", " ")


def with_dollars(text: str, yen_per_usd: float | None) -> str:
    """Дописывает «(≈ $N)» после каждой суммы в иенах. Без курса — текст как есть."""
    if not yen_per_usd or not text:
        return text

    def annotate(match: re.Match) -> str:
        number = re.sub(SPACE, "", match.group("number")).replace(",", ".")
        yen = float(number) * MULTIPLIERS[match.group("scale")]
        return f"{match.group(0)} (≈ {dollars(yen / yen_per_usd)})"

    return YEN.sub(annotate, text)
