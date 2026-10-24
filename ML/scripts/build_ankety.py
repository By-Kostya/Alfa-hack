#!/usr/bin/env python3
"""Собирает анкеты: атом скоринга + случайный план + случайный договор.

Пишет три файла:
  ankety.jsonl       — анкета целиком для обучения скоринга после разметки
  label_tasks.jsonl  — только id и тексты, это вход облачного разметчика
  gold.jsonl         — вектор по manifest.json, разметчику не отдавать
"""

from __future__ import annotations

import argparse
import json
import random
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
ROOT = Path(__file__).resolve().parents[1]

USE_CODE = {
    "запуск": 1,
    "оборудование": 2,
    "оборотные средства": 3,
}


def docx_text(path: Path) -> str:
    with zipfile.ZipFile(path) as archive:
        root = ET.fromstring(archive.read("word/document.xml"))
    paragraphs: list[str] = []
    for paragraph in root.iter(W + "p"):
        line = "".join(node.text or "" for node in paragraph.iter(W + "t")).strip()
        if line:
            paragraphs.append(line)
    return "\n".join(paragraphs).strip()


def load_jsonl(path: Path) -> list[dict]:
    rows: list[dict] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def docx_files(directory: Path) -> list[Path]:
    files = sorted(directory.glob("*.docx"))
    if not files:
        raise SystemExit(f"В {directory} нет .docx")
    return files


def balanced_shuffle(items: list[Path], count: int, rng: random.Random) -> list[Path]:
    sequence = [items[index % len(items)] for index in range(count)]
    rng.shuffle(sequence)
    return sequence


def gold_vector(plan: dict, contract: dict) -> list:
    months = plan.get("months_to_first_cashflow")
    use = USE_CODE.get(plan.get("use_of_funds") or "", 0)
    context = 1 if plan.get("context_specific") is True else 0
    has_contract = 1 if contract.get("has_contract") is True else 0
    return [months, has_contract, use, context]


def index_manifest(path: Path) -> dict[str, dict]:
    rows = json.loads(path.read_text(encoding="utf-8"))
    return {row["file"]: row for row in rows}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Собрать анкеты из атомов, планов и договоров")
    parser.add_argument("--atoms", type=Path, default=ROOT / "Анкеты" / "atoms.jsonl")
    parser.add_argument("--plans", type=Path, default=ROOT / "plans")
    parser.add_argument("--contracts", type=Path, default=ROOT / "contracts")
    parser.add_argument("--manifest", type=Path, default=ROOT / "manifest.json")
    parser.add_argument("--out-dir", type=Path, default=ROOT / "Анкеты")
    parser.add_argument("--seed", type=int, default=23)
    parser.add_argument("--limit", type=int, default=0, help="Сколько атомов взять, 0 — все")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    atoms = load_jsonl(args.atoms)
    if args.limit > 0:
        atoms = atoms[: args.limit]
    plans = docx_files(args.plans)
    contracts = docx_files(args.contracts)
    manifest = index_manifest(args.manifest) if args.manifest.exists() else {}

    plan_text = {path: docx_text(path) for path in plans}
    contract_text = {path: docx_text(path) for path in contracts}

    rng = random.Random(args.seed)
    assigned_plans = balanced_shuffle(plans, len(atoms), rng)
    assigned_contracts = balanced_shuffle(contracts, len(atoms), rng)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    ankety_path = args.out_dir / "ankety.jsonl"
    tasks_path = args.out_dir / "label_tasks.jsonl"
    gold_path = args.out_dir / "gold.jsonl"

    with ankety_path.open("w", encoding="utf-8") as ankety, tasks_path.open(
        "w", encoding="utf-8"
    ) as tasks, gold_path.open("w", encoding="utf-8") as gold:
        for index, atom in enumerate(atoms, start=1):
            plan = assigned_plans[index - 1]
            contract = assigned_contracts[index - 1]
            item_id = f"anketa-{index:06d}"
            plan_rel = plan.relative_to(ROOT).as_posix()
            contract_rel = contract.relative_to(ROOT).as_posix()
            record = {
                "id": item_id,
                "scoring_features": atom,
                "plan_file": plan_rel,
                "contract_file": contract_rel,
                "plan_text": plan_text[plan],
                "contract_text": contract_text[contract],
            }
            ankety.write(json.dumps(record, ensure_ascii=False) + "\n")
            tasks.write(
                json.dumps(
                    {
                        "id": item_id,
                        "plan_text": plan_text[plan],
                        "contract_text": contract_text[contract],
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
            plan_meta = manifest.get(plan_rel)
            contract_meta = manifest.get(contract_rel)
            if plan_meta and contract_meta:
                gold.write(
                    json.dumps(
                        {
                            "id": item_id,
                            "llm_vector": gold_vector(plan_meta, contract_meta),
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )

    print(f"анкет: {len(atoms)}")
    print(f"планов: {len(plans)}, договоров: {len(contracts)}")
    print(ankety_path)
    print(tasks_path)
    print(gold_path)


if __name__ == "__main__":
    main()
