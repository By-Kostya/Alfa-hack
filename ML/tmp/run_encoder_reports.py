#!/usr/bin/env python3
"""Прогон энкодера по длинным планам. Покрытие и платёж из ответа отбрасываются."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tmp" / "docx-venv" / "lib" / "python3.13" / "site-packages"))

from docx import Document  # noqa: E402

LONG = ROOT / "plans" / "long"
BASE = ROOT / "models" / "extractor" / "base"
ADAPTER = ROOT / "models" / "extractor" / "adapters"
OUT = ROOT / "Анкеты" / "encoder_reports.jsonl"

PLANS = (
    "01_кафе.docx",
    "02_it_разработка.docx",
    "03_автомойка.docx",
    "04_доставка.docx",
    "05_найди_собаку.docx",
    "06_барахолка.docx",
    "07_одежда_китай.docx",
)

# Сумма в промпте нужна только потому, что так учился энкодер.
# Платёж и coverage из ответа не сохраняются: на 800000 он подставляет платёж от 2000000.
PROMPT_AMOUNT = 800_000
PROMPT_TERM = 12

PROMPT = """Ты оцениваешь бизнес-план для банка. Верни одну JSON-строку без пояснений. Поток не обязан быть написан фразой «выручка в месяц». Предположи его из покупателя, чека, частоты и затрат. Если прямой цифры нет и картины бизнеса тоже нет, поток null. Добротный стиль сам по себе поток не увеличивает. Сумма и срок даны отдельно. Платёж — аннуитет при ставке 0.20. coverage: yes, если поток не меньше платежа; no, если меньше; unknown, если потока нет. quote — точная подстрока plan_text. Риски выбирай только из: thin_margin, rent, slow_ramp, client_concentration, lumpy_revenue, seasonality, fixed_costs, location, negative_unit_economics, subsidies, competition, rare_payment, unclear_payer, small_market, cold_start, fraud, late_monetization, inventory, customs, returns, fx. Лимит не ставь.
Верни {"inferred_monthly_flow_rub": null, "flow_basis": "explicit|inferred|unknown", "quote": "", "risks": [], "monthly_payment_rub": 0, "coverage": "yes|no|unknown"}."""


def plan_text_of(path: Path) -> str:
    document = Document(path)
    return "\n".join(paragraph.text for paragraph in document.paragraphs if paragraph.text)


def coverage_prompt(text: str) -> str:
    return (
        PROMPT
        + "\n\nplan_text:\n"
        + text
        + f"\n\nloan_amount_rub: {PROMPT_AMOUNT}\nloan_term_months: {PROMPT_TERM}\n"
    )


def parse_coverage(text: str) -> dict | None:
    raw = text.strip()
    raw = re.sub(r"^```(?:json)?", "", raw).strip()
    raw = re.sub(r"```$", "", raw).strip()
    start = raw.find("{")
    end = raw.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        obj = json.loads(raw[start : end + 1])
    except json.JSONDecodeError:
        return None
    if not isinstance(obj, dict):
        return None
    return obj


def main() -> None:
    from mlx_lm import generate, load

    model, tokenizer = load(str(BASE), adapter_path=str(ADAPTER))
    kept = []
    for name in PLANS:
        path = LONG / name
        text = plan_text_of(path)
        user = coverage_prompt(text)
        raw = generate(
            model,
            tokenizer,
            prompt=tokenizer.apply_chat_template(
                [{"role": "user", "content": user}],
                add_generation_prompt=True,
                tokenize=False,
            ),
            max_tokens=1024,
            verbose=False,
        )
        parsed = parse_coverage(raw)
        quote = "" if not parsed else str(parsed.get("quote") or "")
        in_plan = bool(quote) and quote in text
        print("=" * 20, name, "quote_in_plan", in_plan)
        print(raw)
        if not parsed or not in_plan:
            print("строка выброшена")
            continue
        kept.append(
            {
                "plan_file": f"plans/long/{name}",
                "inferred_monthly_flow_rub": parsed.get("inferred_monthly_flow_rub"),
                "flow_basis": parsed.get("flow_basis"),
                "risks": parsed.get("risks"),
                "quote": quote,
            }
        )
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8") as handle:
        for row in kept:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"сохранено {len(kept)} → {OUT}")


if __name__ == "__main__":
    main()
