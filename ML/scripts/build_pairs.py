#!/usr/bin/env python3
"""96 уникальных пар план+договор. Тексты берутся один раз, не все 11025 анкет."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ANKETY = ROOT / "Анкеты" / "ankety.jsonl"
OUT = ROOT / "Анкеты" / "pairs.jsonl"


def main() -> None:
    texts: dict[tuple[str, str], tuple[str, str]] = {}
    with ANKETY.open(encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            key = (row["plan_file"], row["contract_file"])
            pair_texts = (row["plan_text"], row["contract_text"])
            if key in texts and texts[key] != pair_texts:
                raise SystemExit(f"тексты пары {key} разошлись между анкетами")
            texts.setdefault(key, pair_texts)

    if len(texts) != 96:
        raise SystemExit(f"ожидалось 96 пар, получилось {len(texts)}")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8") as handle:
        for index, key in enumerate(sorted(texts), start=1):
            plan_file, contract_file = key
            plan_text, contract_text = texts[key]
            handle.write(
                json.dumps(
                    {
                        "id": f"pair-{index:03d}",
                        "plan_file": plan_file,
                        "contract_file": contract_file,
                        "plan_text": plan_text,
                        "contract_text": contract_text,
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
    print(f"пар: {len(texts)}")
    print(OUT)


if __name__ == "__main__":
    main()
