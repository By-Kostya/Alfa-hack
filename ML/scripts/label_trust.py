#!/usr/bin/env python3
"""Режим trust облачного разметчика.

Вход — строка trust_tasks.jsonl: id, девять полей и llm_vector. Текстов нет.
Контекст 4096, температура 0, ответ до 256 токенов. Модель не дообучается.

trust от 0 до 1 — насколько анкете можно доверять как заявке.
Оцениваются сочетания, а не сумма отдельных плюсов:
- подтверждённая выручка весит больше той же суммы без флага;
- расходы смотрятся рядом с выручкой;
- свои деньги смотрятся рядом с суммой займа;
- рейтинг смотрится рядом с суммой и сроком;
- договор и названный срок до потока вместе сильнее, чем каждый по отдельности;
- пустая выручка, пустые расходы, назначение 0 и контекст 0 доверие снижают;
- неподтверждённые цифры не считаются доказанными.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TASKS = ROOT / "Анкеты" / "trust_tasks.jsonl"
OUT = ROOT / "Анкеты" / "trust_labels.jsonl"


def _sigmoid(value: float) -> float:
    if value >= 0:
        z = math.exp(-value)
        return 1.0 / (1.0 + z)
    z = math.exp(value)
    return z / (1.0 + z)


def trust_of(row: dict) -> float:
    revenue = row["revenue_monthly_rub"]
    costs = row["costs_monthly_rub"]
    own = row["own_funds_rub"]
    income_ok = bool(row["income_confirmed"])
    costs_ok = bool(row["costs_confirmed"])
    capital_ok = bool(row["capital_confirmed"])
    loan = row["loan_amount_rub"]
    term = row["loan_term_months"]
    rating = row["credit_rating"]
    months, has_contract, use, context = row["llm_vector"]

    if revenue is None:
        revenue_term = -1.05
    else:
        level = math.log1p(revenue) / math.log1p(1_500_000)
        revenue_term = level * (1.35 if income_ok else 0.28)

    if costs is None:
        cost_term = -0.65
    elif revenue is None:
        cost_term = -0.30
    else:
        margin = max(-1.5, min(1.0, (revenue - costs) / revenue))
        cost_term = margin * (1.20 if costs_ok else 0.30)

    if own is None:
        own_term = -0.40
    else:
        cover = min(own / loan, 2.0)
        own_term = (cover - 0.2) * (1.15 if capital_ok else 0.28)

    rating_n = rating / 1000.0
    amount_n = loan / 2_000_000.0
    term_n = term / 24.0
    required = 0.20 + 0.50 * amount_n + 0.18 * term_n
    rating_term = (rating_n - required) * (1.0 + 1.4 * amount_n)

    soon = None if months is None else 1.0 - min(months, 12) / 12.0
    doc_term = -0.35
    if has_contract:
        doc_term += 0.45
    if soon is not None:
        doc_term += 0.25 + 0.35 * soon
    if has_contract and soon is not None:
        doc_term += 0.55 + 0.25 * soon

    use_term = {0: -0.70, 1: 0.10, 2: 0.30, 3: 0.45}[int(use)]
    context_term = 0.50 if context else -0.45

    raw = (
        1.10 * revenue_term
        + 1.20 * cost_term
        + 0.80 * own_term
        + 1.40 * rating_term
        + 1.00 * doc_term
        + 0.50 * use_term
        + 0.55 * context_term
    )
    return round(_sigmoid(raw), 4)


def attach_and_tasks() -> None:
    ankety_path = ROOT / "Анкеты" / "ankety.jsonl"
    pairs_path = ROOT / "Анкеты" / "pairs.jsonl"
    labels_path = ROOT / "Анкеты" / "vector_labels.jsonl"
    with_vector_path = ROOT / "Анкеты" / "ankety_with_vector.jsonl"

    pairs = {
        (row["plan_file"], row["contract_file"]): row["id"]
        for row in (json.loads(line) for line in pairs_path.read_text(encoding="utf-8").splitlines() if line.strip())
    }
    vectors = {
        row["id"]: row["llm_vector"]
        for row in (json.loads(line) for line in labels_path.read_text(encoding="utf-8").splitlines() if line.strip())
    }
    fields = (
        "revenue_monthly_rub",
        "costs_monthly_rub",
        "own_funds_rub",
        "income_confirmed",
        "costs_confirmed",
        "capital_confirmed",
        "loan_amount_rub",
        "loan_term_months",
        "credit_rating",
    )

    written = 0
    with ankety_path.open(encoding="utf-8") as source, with_vector_path.open(
        "w", encoding="utf-8"
    ) as ankety_out, TASKS.open("w", encoding="utf-8") as tasks_out:
        for line in source:
            row = json.loads(line)
            vector = vectors[pairs[(row["plan_file"], row["contract_file"])]]
            if len(vector) != 4:
                raise SystemExit(f"вектор {row['id']} не длины 4")
            labeled = dict(row)
            labeled["llm_vector"] = vector
            ankety_out.write(json.dumps(labeled, ensure_ascii=False) + "\n")
            task = {"id": row["id"]}
            task.update({name: row["scoring_features"][name] for name in fields})
            task["llm_vector"] = vector
            tasks_out.write(json.dumps(task, ensure_ascii=False) + "\n")
            written += 1
    if written != 11025:
        raise SystemExit(f"ожидалось 11025 анкет, записано {written}")
    print(f"анкет с вектором: {written}")
    print(with_vector_path)
    print(TASKS)


def main() -> None:
    attach_and_tasks()
    count = 0
    low = 1.0
    high = 0.0
    with TASKS.open(encoding="utf-8") as source, OUT.open("w", encoding="utf-8") as handle:
        for line in source:
            row = json.loads(line)
            score = trust_of(row)
            if not 0.0 <= score <= 1.0:
                raise SystemExit(f"trust вне [0, 1] у {row['id']}: {score}")
            low = min(low, score)
            high = max(high, score)
            handle.write(json.dumps({"id": row["id"], "trust": score}, ensure_ascii=False) + "\n")
            count += 1
    print(f"trust-меток: {count}, диапазон {low}..{high}")
    print(OUT)


if __name__ == "__main__":
    main()
