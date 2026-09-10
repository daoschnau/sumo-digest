"""Шаг write: корпус статей → выпуск в JSON.

Единственное обращение к модели во всём пайплайне. Никаких инструментов ей
не даётся: ни web_search, ни web_fetch, ни MCP. Всё, что она видит, собрал
Python на шаге collect — только так закрытый список источников остаётся
ограничением системы, а не пожеланием в промпте.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import anthropic

from .models import Corpus, corpus_from_dict
from .schema import api_schema, load_schema
from .translit import LintReport, lint_digest, read_field, write_field
from .validate import ValidationFailed, validate

WRITE_PROMPT = Path("prompts/write.md")
TRANSLIT_GUIDE = Path("prompts/translit_guide.md")

DEFAULT_MODEL = "claude-opus-5"
MAX_TOKENS = 16000


def build_system() -> list[dict]:
    """Системный промпт двумя блоками: инструкция и руководство.

    Кеширования здесь намеренно нет. Руководство большое и стабильное, но
    выпуски выходят дважды в неделю, а кеш живёт минуты: попадания не будет
    ни разу, а запись в кеш стоит дороже обычного ввода. Замерено на E2:
    ~11 тысяч токенов руководства, чтение из кеша — ноль.
    """
    return [
        {"type": "text", "text": WRITE_PROMPT.read_text(encoding="utf-8")},
        {"type": "text", "text": TRANSLIT_GUIDE.read_text(encoding="utf-8")},
    ]


def build_user_message(corpus: Corpus) -> str:
    sources = ", ".join(f"{s.name} — {s.status}" for s in corpus.sources)
    articles = [
        {
            "id": a.id,
            "source_name": a.source_name,
            "url": a.url,
            "published": a.published,
            "date_confidence": a.date_confidence,
            "title": a.title,
            "text": a.text,
        }
        for a in corpus.articles
    ]
    return (
        f"Период выпуска: с {corpus.period_from} по {corpus.period_to}.\n"
        f"Дата выпуска: {corpus.period_to}.\n"
        f"Источники и их доступность: {sources}.\n\n"
        f"Статьи ({len(articles)}):\n"
        f"{json.dumps(articles, ensure_ascii=False, indent=1)}"
    )


def write_digest(corpus: Corpus, model: str = DEFAULT_MODEL) -> tuple[dict, dict]:
    """Возвращает выпуск и статистику расхода токенов."""
    # Клиент читает ANTHROPIC_API_KEY сам и по умолчанию делает два повтора
    # с экспоненциальной паузой на 429 и 5xx — отдельный цикл ретраев не нужен.
    client = anthropic.Anthropic()

    response = client.beta.messages.create(
        model=model,
        max_tokens=MAX_TOKENS,
        system=build_system(),
        messages=[{"role": "user", "content": build_user_message(corpus)}],
        thinking={"type": "adaptive"},
        output_config={
            "effort": "high",
            "format": {"type": "json_schema", "schema": api_schema(load_schema())},
        },
        # Если классификатор безопасности откажет, запрос уходит на запасную
        # модель вместо того, чтобы уронить выпуск.
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
    )

    if response.stop_reason == "refusal":
        raise RuntimeError(f"модель отказалась отвечать: {response.stop_details}")
    if response.stop_reason == "max_tokens":
        raise RuntimeError("ответ обрезан по max_tokens — выпуск неполный")

    text = next(block.text for block in response.content if block.type == "text")
    usage = {
        "input_tokens": response.usage.input_tokens,
        "output_tokens": response.usage.output_tokens,
        "cache_read_input_tokens": getattr(response.usage, "cache_read_input_tokens", 0),
        "cache_creation_input_tokens": getattr(response.usage, "cache_creation_input_tokens", 0),
    }
    return json.loads(text), usage


REPAIR_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["corrected"],
    "properties": {"corrected": {"type": "string"}},
}


def repair_field(text: str, complaints: list[str], model: str) -> str:
    """Одна попытка исправить написание в конкретном фрагменте выпуска.

    Находит проблему по-прежнему код: модель получает готовый список нарушений
    и правит только написание. Факты, порядок и длина остаются её же.
    """
    client = anthropic.Anthropic()
    listed = "\n".join(f"- {complaint}" for complaint in complaints)
    response = client.messages.create(
        model=model,
        max_tokens=4000,
        system=[
            {"type": "text",
             "text": ("Ты правишь готовый фрагмент «Сумо-дайджеста» по списку "
                      "нарушений. Исправляй только их: написание, латиницу, "
                      "диакритику, а если термин превращён в прилагательное — "
                      "переформулируй это место («макуутский Икс» → «Икс "
                      "из макуути»). Факты, цифры, имена и объём не трогай. "
                      "Верни исправленный фрагмент целиком.")},
            {"type": "text", "text": TRANSLIT_GUIDE.read_text(encoding="utf-8")},
        ],
        messages=[{"role": "user",
                   "content": f"Фрагмент:\n{text}\n\nНарушения:\n{listed}"}],
        output_config={"format": {"type": "json_schema", "schema": REPAIR_SCHEMA}},
    )
    answer = next(block.text for block in response.content if block.type == "text")
    return json.loads(answer)["corrected"]


def repair_transliteration(digest: dict, report: LintReport,
                           model: str) -> tuple[dict, LintReport]:
    """Чинит поля с замечаниями и перепроверяет их линтером."""
    for where, problems in report.by_field().items():
        original = read_field(digest, where)
        try:
            fixed = repair_field(original, [str(p) for p in problems], model)
        except anthropic.APIError as error:
            print(f"  правка {where} не удалась: {error}", file=sys.stderr)
            continue
        if fixed.strip():
            write_field(digest, where, fixed.strip())

    return lint_digest(digest)


def main() -> int:
    arguments = argparse.ArgumentParser(description="Выпуск из корпуса статей")
    arguments.add_argument("--corpus", type=Path, default=Path("build/corpus.json"))
    arguments.add_argument("--out", type=Path, default=Path("build/digest.json"))
    arguments.add_argument("--model", default=os.getenv("SUMO_DIGEST_MODEL", DEFAULT_MODEL))
    options = arguments.parse_args()

    corpus = corpus_from_dict(json.loads(options.corpus.read_text(encoding="utf-8")))
    print(f"корпус: {len(corpus.articles)} статей, период "
          f"{corpus.period_from} — {corpus.period_to}")
    print(f"модель: {options.model}")

    digest, usage = write_digest(corpus, options.model)
    options.out.parent.mkdir(parents=True, exist_ok=True)
    raw_path = options.out.with_suffix(".raw.json")
    raw_path.write_text(json.dumps(digest, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8")

    print(f"токенов: вход {usage['input_tokens']}, выход {usage['output_tokens']}, "
          f"из кеша {usage['cache_read_input_tokens']}, "
          f"записано в кеш {usage['cache_creation_input_tokens']}")
    print(f"сырой ответ: {raw_path}")

    try:
        digest, lint = validate(digest, corpus)
    except ValidationFailed as failure:
        print("\nВЫПУСК НЕ ПРОШЁЛ ВАЛИДАЦИЮ:", file=sys.stderr)
        for problem in failure.problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1

    options.out.write_text(json.dumps(digest, ensure_ascii=False, indent=2) + "\n",
                           encoding="utf-8")

    if lint.problems:
        print("\nтранслитерация, требует правки:")
        for problem in lint.problems:
            print(f"  {problem}")
        digest, lint = repair_transliteration(digest, lint, options.model)
        if lint.problems:
            # Выпуск всё равно выходит: это написание, а не факты. Оставшееся
            # видно в логе прогона и чинится правилом в config/translit_rules.yml.
            print("\nпосле правки осталось (выпуск публикуется):")
            for problem in lint.problems:
                print(f"  {problem}")
        else:
            print("  после правки замечаний нет")

    # Сработавшие правила линтера — важнейшая часть лога: по ним видно,
    # на каких именах модель дрейфует от выпуска к выпуску.
    if lint.fixes:
        print("\nтранслитерация исправлена:")
        for wrong, right, count in lint.fixes:
            print(f"  «{wrong}» → «{right}» ×{count}")
    if lint.warnings:
        print("\nтранслитерация, предупреждения:")
        for note in lint.warnings:
            print(f"  {note}")

    print(f"\nвыпуск прошёл валидацию, блоков: {len(digest['blocks'])}")
    print(f"главное: {digest['lead'][:120]}")
    for block in digest["blocks"]:
        print(f"  [{block['category']}/{block['importance']}]"
              f" {block.get('date', '—')} {block['subtitle'][:70]}")
    print(f"\nвыпуск записан: {options.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
