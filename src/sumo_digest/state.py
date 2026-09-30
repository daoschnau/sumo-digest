"""Состояние между выпусками: дата прошлого выпуска, показанные статьи, описанные дни.

Без этого каждый выпуск пересказывал бы статьи предыдущего.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

from .links import url_key

DEFAULT_PATH = Path("data/state.json")


@dataclass
class State:
    last_issue_date: str
    last_issue_slug: str | None = None
    # ключ адреса -> дата, когда он попал в выпуск. Дата нужна, чтобы
    # чистить список по seen_urls_kept_days.
    seen_urls: dict[str, str] = field(default_factory=dict)
    # дата события -> дата выпуска, который её описал. Нужна турнирной хронике:
    # отчёт издания о дне выходит вечером, а японская пресса пишет о том же дне
    # сразу, и выпуск с этим днём уже вышел. Без памяти хроника систематически
    # пересказывала последний день прошлого выпуска (находка разбора 30.09.2026).
    covered_dates: dict[str, str] = field(default_factory=dict)
    seen_urls_kept_days: int = 30

    @classmethod
    def load(cls, path: Path = DEFAULT_PATH) -> State:
        raw = json.loads(path.read_text(encoding="utf-8"))
        seen = raw.get("seen_urls", {})
        # Ранние версии файла хранили просто список ключей, без дат.
        if isinstance(seen, list):
            seen = {key: raw["last_issue_date"] for key in seen}
        return cls(
            last_issue_date=raw["last_issue_date"],
            last_issue_slug=raw.get("last_issue_slug"),
            seen_urls=seen,
            covered_dates=raw.get("covered_dates", {}),
            seen_urls_kept_days=raw.get("seen_urls_kept_days", 30),
        )

    def save(self, path: Path = DEFAULT_PATH) -> None:
        path.write_text(
            json.dumps(
                {
                    "last_issue_date": self.last_issue_date,
                    "last_issue_slug": self.last_issue_slug,
                    "seen_urls": self.seen_urls,
                    "covered_dates": self.covered_dates,
                    "seen_urls_kept_days": self.seen_urls_kept_days,
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

    def seen(self, url: str) -> bool:
        return url_key(url) in self.seen_urls

    def mark_seen(self, url: str, when: str) -> None:
        self.seen_urls[url_key(url)] = when

    def covered(self, when: str) -> bool:
        """Описан ли уже день этой даты в вышедшем выпуске."""
        return when in self.covered_dates

    def mark_covered(self, when: str, issue_date: str) -> None:
        """Запоминает, что события этой даты выпуск уже описал.

        Дата события, а не публикации: выпуск от 21.09 описал девятый день
        турнира, и отчёт о девятом дне, вышедший вечером того же дня, во второй
        раз пересказывать нечего.
        """
        self.covered_dates.setdefault(when, issue_date)

    def forget_old(self, today: date) -> int:
        """Выбрасывает записи старше seen_urls_kept_days. Возвращает число забытых."""
        cutoff = (today - timedelta(days=self.seen_urls_kept_days)).isoformat()
        stale = [key for key, when in self.seen_urls.items() if when < cutoff]
        for key in stale:
            del self.seen_urls[key]
        for when in [day for day, issued in self.covered_dates.items() if issued < cutoff]:
            del self.covered_dates[when]
        return len(stale)
