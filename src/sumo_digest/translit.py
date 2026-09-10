"""Детерминированная проверка транслитерации — уровень 3 валидации.

По разделу 8 спецификации транслитерация — главный источник ошибок в выпусках.
Руководство в промпте снижает их частоту, но не убирает: модель дрейфует
на редких именах. Поэтому проверка здесь не просит модель себя перепроверить,
а механически чинит однозначное и отказывает на неоднозначном.

Правила живут в config/translit_rules.yml и соответствуют пунктам раздела 3.4
спецификации: autofix — чинится заменой, reject — публикацию блокирует,
warn — попадает в лог.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

RULES_PATH = Path("config/translit_rules.yml")

# «Имя (romaji: Xxxx — требует проверки)» — легальная конструкция из спецификации,
# латиница внутри неё нарушением не считается.
ROMAJI_NOTE = re.compile(r"\(\s*romaji:[^)]*\)")

# Слова короче этого с каноническими именами не сверяем: на трёх-четырёх буквах
# расстояние в единицу имеют десятки обычных слов.
MIN_NAME_LENGTH = 6


@dataclass
class LintReport:
    fixes: list[tuple[str, str, int]] = field(default_factory=list)
    rejects: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def merge(self, other: LintReport) -> None:
        self.fixes.extend(other.fixes)
        self.rejects.extend(other.rejects)
        self.warnings.extend(other.warnings)

    @property
    def clean(self) -> bool:
        return not self.rejects


def load_rules(path: Path = RULES_PATH) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def distance(first: str, second: str) -> int:
    """Расстояние Левенштейна. Нужно только для предупреждений об опечатках."""
    previous = list(range(len(second) + 1))
    for i, left in enumerate(first, start=1):
        current = [i]
        for j, right in enumerate(second, start=1):
            current.append(min(previous[j] + 1, current[j - 1] + 1,
                               previous[j - 1] + (left != right)))
        previous = current
    return previous[-1]


def autofix(text: str, rules: dict) -> tuple[str, list[tuple[str, str, int]]]:
    """Механические ошибки с однозначным исправлением. Каждая замена — в лог."""
    applied: list[tuple[str, str, int]] = []
    for rule in rules.get("autofix", []):
        wrong, right = rule["wrong"], rule["right"]
        count = text.count(wrong)
        if count:
            text = text.replace(wrong, right)
            applied.append((wrong, right, count))
    return text, applied


def rejections(text: str, rules: dict) -> list[str]:
    """Ошибки, которые нельзя чинить автоматически: выпуск не публикуется."""
    problems: list[str] = []
    for rule in rules.get("reject", []):
        checked = ROMAJI_NOTE.sub("", text) if rule.get("allow_if_in_parens") else text
        found = re.findall(rule["pattern"], checked)
        if found:
            sample = found[0] if isinstance(found[0], str) else found[0][0]
            problems.append(f"{rule['id']}: {rule['message']} Найдено: «{sample}»")
    return problems


def warnings(text: str, rules: dict) -> list[str]:
    """Подозрения: публикацию не блокируют, но должны быть видны в логе."""
    notes: list[str] = []
    for rule in rules.get("warn", []):
        if "pattern" not in rule:
            continue
        found = re.findall(rule["pattern"], text)
        if found:
            notes.append(f"{rule['id']}: {rule['message']}")

    canonical = rules.get("canonical_names", [])
    known = set(canonical)
    for word in set(re.findall(r"[А-ЯЁ][а-яё]+", text)):
        if word in known or len(word) < MIN_NAME_LENGTH:
            continue
        # На коротких словах допускаем только одну букву разницы, на длинных — две.
        limit = 1 if len(word) < 8 else 2
        near = [name for name in canonical if 0 < distance(word, name) <= limit]
        if near:
            notes.append(f"похоже на опечатку: «{word}» против «{near[0]}»")
    return notes


def lint_text(text: str, rules: dict) -> tuple[str, LintReport]:
    fixed, applied = autofix(text, rules)
    return fixed, LintReport(fixes=applied,
                             rejects=rejections(fixed, rules),
                             warnings=warnings(fixed, rules))


# Поля выпуска, которые читает человек. Всё остальное — служебное.
TEXT_FIELDS = ("lead", "missed")
BLOCK_FIELDS = ("subtitle", "body", "place")


def lint_digest(digest: dict, rules: dict | None = None) -> tuple[dict, LintReport]:
    """Чинит и проверяет весь текст выпуска. Возвращает выпуск и отчёт."""
    rules = rules if rules is not None else load_rules()
    report = LintReport()

    for field_name in TEXT_FIELDS:
        if isinstance(digest.get(field_name), str):
            digest[field_name], one = lint_text(digest[field_name], rules)
            report.merge(one)

    for number, block in enumerate(digest.get("blocks", []), start=1):
        for field_name in BLOCK_FIELDS:
            if not isinstance(block.get(field_name), str):
                continue
            block[field_name], one = lint_text(block[field_name], rules)
            one.rejects = [f"блок {number}, {field_name}: {r}" for r in one.rejects]
            one.warnings = [f"блок {number}, {field_name}: {w}" for w in one.warnings]
            report.merge(one)

    return digest, report
