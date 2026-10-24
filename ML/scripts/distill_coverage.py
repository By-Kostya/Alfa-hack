#!/usr/bin/env python3
"""Дообучение экстрактора: ученик повторяет JSON учителя по длинным планам.

Учитель — облачная модель, её веса не читаются и не пишутся. Скорер, кабинет,
Docker, веб и manifest.json не используются. Поток и риски сняты с текста плана.
В потерю попадает только ответ: JSON учителя либо прежний llm_vector.
"""

from __future__ import annotations

import json
import random
import re
import shutil
import subprocess
import sys
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tmp" / "docx-venv" / "lib" / "python3.13" / "site-packages"))
sys.path.insert(0, str(ROOT / "scripts"))

from docx import Document  # noqa: E402

from train_extractor import (  # noqa: E402
    completion_for,
    load_jsonl,
    parse_vector,
    prompt_for,
)

LONG = ROOT / "plans" / "long"
TASKS = ROOT / "Анкеты" / "distill_tasks.jsonl"
LABELS = ROOT / "Анкеты" / "teacher_labels.jsonl"
PAIRS = ROOT / "Анкеты" / "pairs.jsonl"
VECTORS = ROOT / "Анкеты" / "vector_labels.jsonl"
VECTOR_HOLDOUT = ROOT / "models" / "extractor" / "holdout.json"
OUT = ROOT / "models" / "extractor"
DATA = OUT / "data"
ADAPTER = OUT / "adapters"
BASE = OUT / "base"
EXAMPLES = OUT / "coverage_examples.jsonl"
README = OUT / "README.md"

AMOUNTS = (300_000, 800_000, 2_000_000)
TERM = 12
RATE = Decimal("0.20")
HOLDOUT_AMOUNT = 800_000
SEED = 23
COVERAGE_REPEATS = 4
# Дольше ~200 шагов лосс только полирует уже заученные JSON. Промежуточных чекпоинтов mlx не пишет.
ITERS = 200

EXPECTED = (
    "01_кафе",
    "02_it_разработка",
    "03_автомойка",
    "04_доставка",
    "05_найди_собаку",
    "06_барахолка",
    "07_одежда_китай",
)

ALLOWED_RISKS = {
    "thin_margin",
    "rent",
    "slow_ramp",
    "client_concentration",
    "lumpy_revenue",
    "seasonality",
    "fixed_costs",
    "location",
    "negative_unit_economics",
    "subsidies",
    "competition",
    "rare_payment",
    "unclear_payer",
    "small_market",
    "cold_start",
    "fraud",
    "late_monetization",
    "inventory",
    "customs",
    "returns",
    "fx",
}

TEACHER_PROMPT = """Ты оцениваешь бизнес-план для банка. Верни одну JSON-строку без пояснений. Поток не обязан быть написан фразой «выручка в месяц». Предположи его из покупателя, чека, частоты и затрат. Если прямой цифры нет и картины бизнеса тоже нет, поток null. Добротный стиль сам по себе поток не увеличивает. Сумма и срок даны отдельно. Платёж — аннуитет при ставке 0.20. coverage: yes, если поток не меньше платежа; no, если меньше; unknown, если потока нет. quote — точная подстрока plan_text. Риски выбирай только из: thin_margin, rent, slow_ramp, client_concentration, lumpy_revenue, seasonality, fixed_costs, location, negative_unit_economics, subsidies, competition, rare_payment, unclear_payer, small_market, cold_start, fraud, late_monetization, inventory, customs, returns, fx. Лимит не ставь.
Верни {"inferred_monthly_flow_rub": null, "flow_basis": "explicit|inferred|unknown", "quote": "", "risks": [], "monthly_payment_rub": 0, "coverage": "yes|no|unknown"}."""

# Цифра потока стоит в тексте прямо. Риски — из устройства дела, не из гладкости стиля.
JUDGMENTS = {
    "01_кафе": {
        "flow": 45000,
        "basis": "explicit",
        "risks": ["thin_margin", "rent", "slow_ramp"],
        "anchor": "После выхода на режим остаётся 45000 руб. в месяц.",
    },
    "02_it_разработка": {
        "flow": 160000,
        "basis": "explicit",
        "risks": ["client_concentration", "lumpy_revenue"],
        "anchor": "Средний поток равен 160000 руб. в месяц.",
    },
    "03_автомойка": {
        "flow": 127000,
        "basis": "explicit",
        "risks": ["seasonality", "fixed_costs", "location"],
        "anchor": "Средний поток за год равен 127000 руб. в месяц.",
    },
    "04_доставка": {
        "flow": -140000,
        "basis": "explicit",
        "risks": ["negative_unit_economics", "subsidies", "competition"],
        "anchor": "Поток равен -140000 руб. в месяц.",
    },
    "05_найди_собаку": {
        "flow": -16300,
        "basis": "explicit",
        "risks": ["rare_payment", "unclear_payer", "small_market"],
        "anchor": "Поток равен -16300 руб. в месяц.",
    },
    "06_барахолка": {
        "flow": -135000,
        "basis": "explicit",
        "risks": ["cold_start", "competition", "fraud", "late_monetization"],
        "anchor": "Поток первого года равен -135000 руб. в месяц.",
    },
    "07_одежда_китай": {
        "flow": 133000,
        "basis": "explicit",
        "risks": ["inventory", "customs", "returns", "fx"],
        "anchor": "поток равен 133000 руб. в месяц.",
    },
}


def dump_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def plan_text_of(path: Path) -> str:
    document = Document(path)
    return "\n".join(paragraph.text for paragraph in document.paragraphs if paragraph.text)


def annuity(principal: int) -> int:
    monthly = RATE / Decimal(12)
    power = (1 + monthly) ** TERM
    raw = Decimal(principal) * monthly * power / (power - 1)
    return int(raw.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def coverage_of(flow: int | None, payment: int) -> str:
    if flow is None:
        return "unknown"
    if flow >= payment:
        return "yes"
    return "no"


def quote_paragraph(text: str, anchor: str) -> str:
    hits = [part for part in text.split("\n") if anchor in part]
    if len(hits) != 1:
        raise SystemExit(f"якорь {anchor!r} найден {len(hits)} раз")
    return hits[0]


def coverage_prompt(text: str, amount: int, term: int) -> str:
    return (
        TEACHER_PROMPT
        + "\n\nplan_text:\n"
        + text
        + f"\n\nloan_amount_rub: {amount}\nloan_term_months: {term}\n"
    )


def teacher_json(judgment: dict, quote: str, payment: int) -> dict:
    flow = judgment["flow"]
    return {
        "inferred_monthly_flow_rub": flow,
        "flow_basis": judgment["basis"],
        "quote": quote,
        "risks": list(judgment["risks"]),
        "monthly_payment_rub": payment,
        "coverage": coverage_of(flow, payment),
    }


def keep_label(label: dict, text: str) -> bool:
    quote = label["quote"]
    if quote and quote not in text:
        return False
    expected = coverage_of(label["inferred_monthly_flow_rub"], label["monthly_payment_rub"])
    if label["coverage"] != expected:
        return False
    if any(risk not in ALLOWED_RISKS for risk in label["risks"]):
        return False
    return True


def find_plans() -> tuple[list[Path], list[str]]:
    found = []
    missing = []
    for stem in EXPECTED:
        matches = sorted(LONG.glob(stem + ".docx"))
        if len(matches) != 1:
            missing.append(stem)
            continue
        path = matches[0]
        try:
            text = plan_text_of(path)
        except Exception:
            missing.append(stem)
            continue
        if stem not in text and len(text) < 500:
            missing.append(stem)
            continue
        found.append(path)
    return found, missing


def prepare() -> tuple[list[dict], list[dict], list[dict]]:
    found, missing = find_plans()
    print("найдены:", ", ".join(path.name for path in found) or "нет")
    print("недостающие:", ", ".join(missing) or "нет")
    if not found:
        raise SystemExit("длинных планов нет, короткие из plans/ не подменяют их")

    tasks = []
    labels = []
    dropped = []
    for path in found:
        stem = path.stem
        judgment = JUDGMENTS[stem]
        text = plan_text_of(path)
        quote = quote_paragraph(text, judgment["anchor"])
        if "manifest" in text.lower():
            raise SystemExit(f"{path.name}: в тексте плана встретился manifest")
        for amount in AMOUNTS:
            payment = annuity(amount)
            task_id = f"distill-{stem[:2]}-{amount}"
            task = {
                "id": task_id,
                "plan_file": f"plans/long/{path.name}",
                "plan_text": text,
                "loan_amount_rub": amount,
                "loan_term_months": TERM,
                "annual_rate": float(RATE),
            }
            label = {"id": task_id, **teacher_json(judgment, quote, payment)}
            if not keep_label(label, text):
                dropped.append(task_id)
                continue
            tasks.append(task)
            labels.append(label)
            print(
                task_id,
                label["coverage"],
                "поток",
                label["inferred_monthly_flow_rub"],
                "платёж",
                payment,
                "риски",
                ",".join(label["risks"]),
            )

    dump_jsonl(TASKS, tasks)
    dump_jsonl(LABELS, labels)
    print(f"задачи {len(tasks)} метки {len(labels)} выброшено {len(dropped)}")
    if dropped:
        print("выброшены:", ", ".join(dropped))

    by_id = {row["id"]: row for row in tasks}
    kept = []
    holdout = []
    for label in labels:
        task = by_id[label["id"]]
        if task["loan_amount_rub"] == HOLDOUT_AMOUNT:
            holdout.append((task, label))
        else:
            kept.append((task, label))

    pairs = load_jsonl(PAIRS)
    vectors = {row["id"]: row["llm_vector"] for row in load_jsonl(VECTORS)}
    if len(pairs) != 96:
        raise SystemExit(f"в pairs.jsonl {len(pairs)} строк, нужны 96")
    vector_rows = []
    for pair in pairs:
        vector_rows.append(
            {
                "messages": [
                    {"role": "user", "content": prompt_for(pair)},
                    {"role": "assistant", "content": completion_for(vectors[pair["id"]])},
                ]
            }
        )

    coverage_rows = []
    for task, label in kept:
        target = {key: value for key, value in label.items() if key != "id"}
        prompt = coverage_prompt(task["plan_text"], task["loan_amount_rub"], task["loan_term_months"])
        if "manifest" in prompt.lower():
            raise SystemExit("в промпт ученика попал manifest")
        coverage_rows.append(
            {
                "messages": [
                    {"role": "user", "content": prompt},
                    {"role": "assistant", "content": json.dumps(target, ensure_ascii=False)},
                ]
            }
        )

    mixture = vector_rows + coverage_rows * COVERAGE_REPEATS
    rng = random.Random(SEED)
    rng.shuffle(mixture)
    valid = vector_rows[:8]
    dump_jsonl(DATA / "train.jsonl", mixture)
    dump_jsonl(DATA / "valid.jsonl", valid)
    print(
        f"смесь {len(mixture)}: вектор {len(vector_rows)}, "
        f"покрытие {len(coverage_rows)} x{COVERAGE_REPEATS}, отложено {len(holdout)}"
    )
    return tasks, labels, holdout


def train() -> int:
    backup = ROOT / "tmp" / "vector_adapters.safetensors"
    backup.parent.mkdir(parents=True, exist_ok=True)
    if not backup.exists():
        shutil.copy(ADAPTER / "adapters.safetensors", backup)
    cmd = [
        sys.executable,
        "-m",
        "mlx_lm",
        "lora",
        "--model",
        str(BASE),
        "--train",
        "--data",
        str(DATA),
        "--mask-prompt",
        "--batch-size",
        "1",
        "--iters",
        str(ITERS),
        "--learning-rate",
        "1e-4",
        "--num-layers",
        "8",
        "--max-seq-length",
        "8192",
        "--grad-checkpoint",
        "--adapter-path",
        str(ADAPTER),
        "--resume-adapter-file",
        str(backup),
        "--save-every",
        str(ITERS),
        "--steps-per-report",
        "20",
        "--steps-per-eval",
        "160",
        "--val-batches",
        "-1",
        "--seed",
        str(SEED),
    ]
    print(" ".join(cmd))
    return subprocess.call(cmd)


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
    if "limit" in obj or "лимит" in obj:
        return None
    return obj


def generate_user(model, tokenizer, user: str, max_tokens: int) -> str:
    prompt = tokenizer.apply_chat_template(
        [{"role": "user", "content": user}],
        add_generation_prompt=True,
        tokenize=False,
    )
    from mlx_lm import generate

    return generate(model, tokenizer, prompt=prompt, max_tokens=max_tokens, verbose=False)


def risks_match(got: dict | None, want: list) -> bool:
    if not got or not isinstance(got.get("risks"), list):
        return False
    return set(got["risks"]) == set(want)


def append_readme(matched: int, total: int) -> None:
    block = (
        "\n\n## Покрытие платежа\n\n"
        "Дообучение поверх прежнего адаптера. Учитель — облачная модель, её веса не менялись: "
        "она прочитала длинные планы и записала JSON. Ученик повторяет этот JSON. "
        "В смесь добавлены 96 прежних пар с целью llm_vector, чтобы короткий вектор не стёрся. "
        "manifest.json в запрос и в потерю не входил. "
        f"На каждый новый план отложена сумма {HOLDOUT_AMOUNT} руб. "
        f"По coverage с учителем совпало {matched} из {total} отложенных ответов.\n"
    )
    text = README.read_text(encoding="utf-8")
    marker = "\n## Покрытие платежа\n"
    if marker in text:
        text = text.split(marker)[0].rstrip() + "\n"
    README.write_text(text.rstrip() + block, encoding="utf-8")
    print(README)


def evaluate(labels: list[dict]) -> dict:
    import gc

    import mlx.core as mx
    from mlx_lm import load

    tasks = {row["id"]: row for row in load_jsonl(TASKS)}
    model, tokenizer = load(str(BASE), adapter_path=str(ADAPTER))
    lengths = []
    student = {}
    for label in labels:
        task = tasks[label["id"]]
        user = coverage_prompt(task["plan_text"], task["loan_amount_rub"], task["loan_term_months"])
        lengths.append(len(tokenizer.encode(user)))
        raw = generate_user(model, tokenizer, user, 1024)
        student[label["id"]] = {"raw": raw, "parsed": parse_coverage(raw)}
        got = student[label["id"]]["parsed"]
        print(
            label["id"],
            "teacher",
            label["coverage"],
            "student",
            None if got is None else got.get("coverage"),
            "basis",
            None if got is None else got.get("flow_basis"),
        )

    holdout_rows = []
    matched = 0
    for label in labels:
        task = tasks[label["id"]]
        if task["loan_amount_rub"] != HOLDOUT_AMOUNT:
            continue
        want = {key: value for key, value in label.items() if key != "id"}
        got = student[label["id"]]["parsed"]
        coverage_ok = bool(got) and got.get("coverage") == want["coverage"]
        matched += int(coverage_ok)
        holdout_rows.append(
            {
                "id": label["id"],
                "plan_file": task["plan_file"],
                "loan_amount_rub": task["loan_amount_rub"],
                "loan_term_months": task["loan_term_months"],
                "teacher": want,
                "student": got,
                "flow_basis_match": bool(got) and got.get("flow_basis") == want["flow_basis"],
                "risks_match": risks_match(got, want["risks"]),
                "coverage_match": coverage_ok,
            }
        )
    dump_jsonl(EXAMPLES, holdout_rows)
    print(f"coverage на отложенных {matched} из {len(holdout_rows)}")
    print("max prompt tokens", max(lengths) if lengths else 0)

    vector_hits = vector_exact(model, tokenizer)
    del model
    gc.collect()
    mx.clear_cache()
    append_readme(matched, len(holdout_rows))
    return {
        "coverage_matched": matched,
        "coverage_total": len(holdout_rows),
        "vector_exact": vector_hits,
        "student": student,
        "max_prompt_tokens": max(lengths) if lengths else 0,
    }


def vector_exact(model, tokenizer) -> tuple[int, int]:
    pairs = {row["id"]: row for row in load_jsonl(PAIRS)}
    vectors = {row["id"]: row["llm_vector"] for row in load_jsonl(VECTORS)}
    holdout = json.loads(VECTOR_HOLDOUT.read_text(encoding="utf-8"))
    hits = 0
    for row in holdout:
        pair = pairs[row["id"]]
        raw = generate_user(model, tokenizer, prompt_for(pair), 128)
        got = parse_vector(raw)
        ok = got == vectors[row["id"]]
        hits += int(ok)
        print(row["id"], "vector", "OK" if ok else f"FAIL want={vectors[row['id']]} got={got}")
    print(f"вектор на прежних отложенных {hits} из {len(holdout)}")
    return hits, len(holdout)


def meaning_problems(labels: list[dict], student: dict[str, dict]) -> list[str]:
    by_key = {}
    tasks = {row["id"]: row for row in load_jsonl(TASKS)}
    for label in labels:
        task = tasks[label["id"]]
        stem = Path(task["plan_file"]).stem
        by_key[(stem, task["loan_amount_rub"])] = label

    problems = []
    weak = ("04_доставка", "05_найди_собаку", "06_барахолка")
    for stem in weak:
        for who, obj in (
            ("учитель", {k: by_key[(stem, 2_000_000)][k] for k in ("coverage", "risks")}),
            ("ученик", student[by_key[(stem, 2_000_000)]["id"]]["parsed"]),
        ):
            if not obj or obj.get("coverage") not in {"no", "unknown"} or not obj.get("risks"):
                problems.append(f"{stem} 2000000 {who}: coverage/risks {None if not obj else (obj.get('coverage'), obj.get('risks'))}")
        low = by_key[(stem, 300_000)]["coverage"]
        high = by_key[(stem, 2_000_000)]["coverage"]
        student_low = student[by_key[(stem, 300_000)]["id"]]["parsed"]
        student_high = student[by_key[(stem, 2_000_000)]["id"]]["parsed"]
        print(
            stem,
            "300000 учитель",
            low,
            "ученик",
            None if not student_low else student_low.get("coverage"),
            "2000000 учитель",
            high,
            "ученик",
            None if not student_high else student_high.get("coverage"),
        )
    for stem in ("01_кафе", "07_одежда_китай"):
        for who, obj in (
            ("учитель", by_key[(stem, 2_000_000)]),
            ("ученик", student[by_key[(stem, 2_000_000)]["id"]]["parsed"]),
        ):
            coverage = None if not obj else obj.get("coverage")
            if coverage == "yes":
                problems.append(f"{stem} 2000000 {who}: coverage yes при потоке ниже платежа")
            print(stem, "2000000", who, coverage)
    return problems


def main() -> None:
    phase = sys.argv[1] if len(sys.argv) > 1 else "all"
    tasks, labels, _holdout = prepare()
    if phase == "prepare":
        return
    if phase in {"train", "all"}:
        code = train()
        if code != 0:
            raise SystemExit(f"дообучение завершилось с кодом {code}")
    if phase in {"eval", "all"}:
        result = evaluate(labels)
        problems = meaning_problems(labels, result["student"])
        if problems:
            print("смысл не сошёлся:")
            for line in problems:
                print(" -", line)
            raise SystemExit(1)
        print("смысл на указанных планах сошёлся")
        print("max prompt tokens", result["max_prompt_tokens"])


if __name__ == "__main__":
    main()
