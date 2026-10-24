#!/usr/bin/env python3
"""Сверяет llm_vector меток с gold.jsonl по файлам плана и договора.

gold и manifest в запрос разметчика не входят: скрипт только сравнивает уже снятые метки.
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIR = ROOT / "Анкеты"


def load_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def main() -> None:
    pairs = {row["id"]: row for row in load_jsonl(DIR / "pairs.jsonl")}
    labels = {row["id"]: row["llm_vector"] for row in load_jsonl(DIR / "vector_labels.jsonl")}
    ankety = load_jsonl(DIR / "ankety.jsonl")
    gold = {row["id"]: row["llm_vector"] for row in load_jsonl(DIR / "gold.jsonl")}

    expected: dict[tuple[str, str], list] = {}
    for row in ankety:
        vector = gold.get(row["id"])
        if vector is None:
            raise SystemExit(f"нет gold для {row['id']}")
        key = (row["plan_file"], row["contract_file"])
        if key in expected and expected[key] != vector:
            raise SystemExit(f"gold расходится внутри пары {key}")
        expected[key] = vector

    bad: list[str] = []
    for pair_id, pair in pairs.items():
        key = (pair["plan_file"], pair["contract_file"])
        got = labels.get(pair_id)
        want = expected[key]
        if got != want:
            bad.append(f"{pair_id} {key[0]} + {key[1]}: метка {got} gold {want}")

    print(f"пар сверено: {len(pairs)}")
    print(f"расхождений: {len(bad)}")
    for line in bad:
        print(line)
    if bad:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
