"""Календарь хонбасё: идёт ли турнир и какие его дни попали в отчётный период.

Нужен из-за одного источника. Sumo Stomp! даёт отчёты по дням турнира и разбор
схваток — материал, который существует только пока идёт басё; между турнирами
брать из него нечего. Значит, системе нужен ответ на вопрос «идёт ли сейчас
турнир», и ответ этот обязан быть детерминированным: спросить модель — то же
самое, что попросить её проверить саму себя вместо валидации.

Расписание Ассоциация объявляет за год вперёд, поэтому календарь лежит
в `config/basho.yml` и правится руками, а не выясняется в прогоне: единственный
шаг, который ходит в сеть, собирает новости, а не расписание.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import yaml

from .models import BashoDay, BashoWindow

CONFIG_PATH = Path("config/basho.yml")

# Хонбасё всегда пятнадцать дней, с воскресенья по воскресенье. Отсюда же
# и номер последнего дня: в адресах отчётов он называется не числом,
# а «final-day».
LENGTH_DAYS = 15

# За сколько дней до конца календаря начинать предупреждать. Календарь, который
# кончился, ничего не ломает громко: источники «только на турнире» просто
# перестают обходиться, и выпуск в дни басё выходит без хроники дней.
# Полтора месяца — запас, которого хватает заметить предупреждение в логе
# и дописать следующий год.
WARN_AHEAD_DAYS = 45


@dataclass(frozen=True)
class Basho:
    """Запись календаря. Даты включительные: start — первый день, end — пятнадцатый."""

    id: str
    name: str
    place: str
    start: str
    end: str

    def day_number(self, when: str) -> int | None:
        """Номер дня турнира для даты. None — дата вне турнира."""
        if not self.start <= when <= self.end:
            return None
        return (date.fromisoformat(when) - date.fromisoformat(self.start)).days + 1

    def day_date(self, day: int) -> str:
        """Дата дня турнира по его номеру."""
        return (date.fromisoformat(self.start) + timedelta(days=day - 1)).isoformat()


def _iso(value: object) -> str:
    """YAML сам разбирает 2026-09-13 в date; внутри системы даты — строки ISO."""
    return value.isoformat() if isinstance(value, date) else str(value)


def load_calendar(path: Path = CONFIG_PATH) -> list[Basho]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    calendar = [
        Basho(id=str(item["id"]), name=item["name"], place=item.get("place", ""),
              start=_iso(item["start"]), end=_iso(item["end"]))
        for item in raw.get("calendar") or []
    ]
    return sorted(calendar, key=lambda basho: basho.start)


def current_basho(calendar: list[Basho], period_from: str, period_to: str) -> Basho | None:
    """Турнир, чьи дни попали в отчётный период. None — межсезонье.

    Пересечение с периодом, а не «идёт ли сегодня»: выпуск выходит дважды
    в неделю и описывает период, а не момент. Первый день турнира, прошедший
    в воскресенье, — новость вторничного выпуска, даже если турнир к тому
    моменту идёт уже третий день.
    """
    for basho in calendar:
        if basho.start <= period_to and period_from <= basho.end:
            return basho
    return None


def day_from_url(url: str, pattern: str) -> int | None:
    """Номер дня турнира из адреса отчёта. None — адрес не про день турнира.

    День берётся из адреса, а не у модели: в слаге издания он есть
    («…-day-3-results…», «…-final-day-results»), и это проверяемый факт.
    Шаблон живёт рядом с источником — `day_pattern` в config/sources.yml.
    """
    match = re.search(pattern, url)
    if match is None:
        return None
    groups = match.groupdict()
    if groups.get("final"):
        return LENGTH_DAYS
    if not groups.get("day"):
        return None
    day = int(groups["day"])
    return day if 1 <= day <= LENGTH_DAYS else None


def basho_window(basho: Basho, period_from: str, period_to: str,
                 reports: dict[int, str]) -> BashoWindow:
    """Дни турнира этого периода и отчёты о них из корпуса.

    Дни календаря и дни с отчётами объединяются, а не пересекаются. Отчёт
    о дне выходит вечером того же дня и в выпуск попадает следующим: день
    четырнадцатого сентября законно приезжает с отчётом, который появился
    пятнадцатого. Обратный случай тоже бывает — день периода, о котором отчёта
    ещё нет; он остаётся в списке с пустым `article_id`, чтобы модель видела,
    что о нём писать нечего.
    """
    days = set(reports)
    first, last = max(basho.start, period_from), min(basho.end, period_to)
    if first <= last:
        days.update(range(basho.day_number(first), basho.day_number(last) + 1))
    return BashoWindow(
        id=basho.id, name=basho.name, place=basho.place,
        start=basho.start, end=basho.end,
        days=[BashoDay(day=day, date=basho.day_date(day), article_id=reports.get(day))
              for day in sorted(days)],
    )


def calendar_warning(calendar: list[Basho], today: date) -> str | None:
    """Предупреждение о том, что календарь кончается. None — запаса хватает."""
    if not calendar:
        return ("config/basho.yml пуст: источники только для турнира не будут "
                "обходиться никогда")
    horizon = (today + timedelta(days=WARN_AHEAD_DAYS)).isoformat()
    if calendar[-1].end < horizon:
        return (f"календарь басё кончается {calendar[-1].end}: допиши расписание "
                f"в config/basho.yml, иначе источники только для турнира "
                f"тихо выпадут из обхода")
    return None
