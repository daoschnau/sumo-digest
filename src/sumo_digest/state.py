"""Состояние между выпусками: дата прошлого выпуска и уже показанные статьи.

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
            seen_urls_kept_days=raw.get("seen_urls_kept_days", 30),
        )

    def save(self, path: Path = DEFAULT_PATH) -> None:
        path.write_text(
            json.dumps(
                {
                    "last_issue_date": self.last_issue_date,
                    "last_issue_slug": self.last_issue_slug,
                    "seen_urls": self.seen_urls,
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

    def forget_old(self, today: date) -> int:
        """Выбрасывает записи старше seen_urls_kept_days. Возвращает число забытых."""
        cutoff = (today - timedelta(days=self.seen_urls_kept_days)).isoformat()
        stale = [key for key, when in self.seen_urls.items() if when < cutoff]
        for key in stale:
            del self.seen_urls[key]
        return len(stale)
