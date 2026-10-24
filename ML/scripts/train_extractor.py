#!/usr/bin/env python3
"""Дообучает Qwen2.5-1.5B на 96 парах предсказывать llm_vector.

Отложенные пары в обучение не входят. Сверка — точное совпадение четырёх компонент
с меткой разметчика. Если дообучение разваливается, карточка оставляет промпт
с теми же правилами вектора.
"""

from __future__ import annotations

import json
import random
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAIRS = ROOT / "Анкеты" / "pairs.jsonl"
LABELS = ROOT / "Анкеты" / "vector_labels.jsonl"
OUT = ROOT / "models" / "extractor"
BASE = OUT / "base"
DATA = OUT / "data"
ADAPTER = OUT / "adapters"
SEED = 23
HOLDOUT_N = 16

RULES = """Ты извлекаешь вектор из документов кредитной анкеты. Верни одну JSON-строку без пояснений и без markdown.

Смотри только на plan_text и contract_text. Сумму займа, срок, рейтинг и флаги подтверждения не выводи и не додумывай.

Верни объект {"llm_vector": [months_to_first_cashflow, has_contract, use_of_funds, context_specific]}.

Правила вектора, строго в этом порядке:

1. months_to_first_cashflow — целое число месяцев из plan_text. Если поступления уже идут и до них 0 месяцев, ставь 0. Если срок в плане не назван, ставь null.
2. has_contract — 1 или 0, решай только по contract_text. 1, если это договор поставки, услуг, аренды или предварительный заказ с названными сторонами. 0, если это рамочная договорённость без твёрдой суммы, обрывок, письмо «давайте работать» или пустой бланк. Упоминание клиента в бизнес-плане договором не считается.
3. use_of_funds — только из plan_text: 1 запуск, 2 оборудование, 3 оборотные средства, 0 если назначение не сказано или из текста не выбрать одно.
4. context_specific — 1, если в plan_text названы и покупатель, и за счёт чего бизнес получает деньги. Иначе 0. Общие слова вроде «городское дело» и «обычная деятельность» — это 0.
"""


def load_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def prompt_for(pair: dict) -> str:
    return (
        RULES
        + "\nplan_text:\n"
        + pair["plan_text"]
        + "\n\ncontract_text:\n"
        + pair["contract_text"]
    )


def completion_for(vector: list) -> str:
    return json.dumps({"llm_vector": vector}, ensure_ascii=False)


def prepare() -> tuple[list[dict], list[dict]]:
    pairs = load_jsonl(PAIRS)
    labels = {row["id"]: row["llm_vector"] for row in load_jsonl(LABELS)}
    rows = []
    for pair in pairs:
        vector = labels[pair["id"]]
        rows.append(
            {
                "id": pair["id"],
                "plan_file": pair["plan_file"],
                "contract_file": pair["contract_file"],
                "messages": [
                    {"role": "user", "content": prompt_for(pair)},
                    {"role": "assistant", "content": completion_for(vector)},
                ],
                "llm_vector": vector,
            }
        )
    rng = random.Random(SEED)
    order = rows[:]
    rng.shuffle(order)
    holdout = order[:HOLDOUT_N]
    rest = order[HOLDOUT_N:]
    valid = rest[:8]
    train = rest[8:]
    DATA.mkdir(parents=True, exist_ok=True)

    def dump(path: Path, subset: list[dict]) -> None:
        with path.open("w", encoding="utf-8") as handle:
            for row in subset:
                handle.write(
                    json.dumps({"messages": row["messages"]}, ensure_ascii=False) + "\n"
                )

    dump(DATA / "train.jsonl", train)
    dump(DATA / "valid.jsonl", valid)
    dump(DATA / "test.jsonl", holdout)
    (OUT / "holdout.json").write_text(
        json.dumps(
            [
                {
                    "id": row["id"],
                    "plan_file": row["plan_file"],
                    "contract_file": row["contract_file"],
                    "llm_vector": row["llm_vector"],
                }
                for row in holdout
            ],
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"train {len(train)} valid {len(valid)} holdout {len(holdout)}")
    return train, holdout


def parse_vector(text: str) -> list | None:
    raw = text.strip()
    raw = re.sub(r"^```(?:json)?", "", raw).strip()
    raw = re.sub(r"```$", "", raw).strip()
    start = raw.find("{")
    end = raw.rfind("}")
    try:
        if start >= 0 and end > start:
            vector = json.loads(raw[start : end + 1])["llm_vector"]
        else:
            left = raw.find("[")
            right = raw.rfind("]")
            vector = json.loads(raw[left : right + 1])
        months = None if vector[0] is None else int(vector[0])
        return [months, int(vector[1]), int(vector[2]), int(vector[3])]
    except (json.JSONDecodeError, KeyError, TypeError, ValueError, IndexError):
        return None


def exact_match(holdout: list[dict], adapter: Path | None) -> dict:
    import gc

    import mlx.core as mx
    from mlx_lm import generate, load

    kwargs = {"adapter_path": str(adapter)} if adapter else {}
    model, tokenizer = load(str(BASE), **kwargs)
    hits = 0
    parsed = 0
    details = []
    lengths = []
    for row in holdout:
        user = row["messages"][0]["content"]
        prompt = tokenizer.apply_chat_template(
            [{"role": "user", "content": user}],
            add_generation_prompt=True,
            tokenize=False,
        )
        lengths.append(len(tokenizer.encode(prompt)))
        output = generate(model, tokenizer, prompt=prompt, max_tokens=128, verbose=False)
        got = parse_vector(output)
        want = row["llm_vector"]
        ok = got == want
        hits += int(ok)
        parsed += int(got is not None)
        details.append({"id": row["id"], "want": want, "got": got, "ok": ok, "raw": output[:300]})
        print(row["id"], "OK" if ok else f"FAIL want={want} got={got}")
    del model
    gc.collect()
    mx.clear_cache()
    return {
        "n": len(holdout),
        "exact": hits,
        "exact_rate": hits / len(holdout) if holdout else 0.0,
        "parsed": parsed,
        "max_prompt_tokens": max(lengths) if lengths else 0,
        "details": details,
    }


def train() -> int:
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
        "240",
        "--learning-rate",
        "1e-4",
        "--num-layers",
        "8",
        "--max-seq-length",
        "4096",
        "--grad-checkpoint",
        "--adapter-path",
        str(ADAPTER),
        "--save-every",
        "120",
        "--steps-per-report",
        "20",
        "--steps-per-eval",
        "60",
        "--val-batches",
        "-1",
        "--seed",
        str(SEED),
    ]
    print(" ".join(cmd))
    return subprocess.call(cmd)


def write_readme(base_eval: dict | None, tuned_eval: dict | None, kept_weights: bool, note: str) -> None:
    def block(title: str, result: dict | None) -> str:
        if result is None:
            return f"{title}: не считалось."
        return (
            f"{title}: точное совпадение {result['exact']} из {result['n']} "
            f"({result['exact_rate']:.0%}), разобрано ответов {result['parsed']}."
        )

    prompt = RULES.strip()
    if kept_weights:
        body = f"""# Экстрактор вектора

Открытая модель Qwen2.5-1.5B-Instruct, 1,54 млрд параметров, веса в 4 бита лежат в `base/`.
Поверх них LoRA на восьми слоях, адаптер в `adapters/`. Облачная модель не дообучалась: цель — её `llm_vector` на 96 парах.

Обучение: 72 пары, 8 пар для контроля потерь, 16 пар отложены (сид {SEED}). В запрос не входили gold.jsonl и manifest.json. Промпт маскировался, учился только ответ.

{block("База без дообучения", base_eval)}
{block("После LoRA", tuned_eval)}

Четыре компоненты совпали с меткой разметчика на {tuned_eval['exact'] if tuned_eval else 0} из {tuned_eval['n'] if tuned_eval else 0} отложенных пар. Карточка этого запуска — этот файл, веса — `base/` и `adapters/`.

Промпт на входе тот же, что у разметчика для вектора:

```
{prompt}
```

Дальше в том же сообщении идут `plan_text` и `contract_text`. Ответ — одна JSON-строка `{{"llm_vector": [...]}}`.
"""
    else:
        body = f"""# Экстрактор вектора

Дообучение малой модели на 96 парах не стало рабочим экстрактором. {note}

{block("База без дообучения", base_eval)}
{block("После попытки LoRA", tuned_eval)}

Веса дообучения в работу не ставятся. Экстрактор — этот промпт, правила вектора те же, что у разметчика. Облачная модель по-прежнему только размечает и здесь не учится.

```
{prompt}
```

Дальше в том же сообщении идут `plan_text` и `contract_text`. Ответ — одна JSON-строка `{{"llm_vector": [months_to_first_cashflow, has_contract, use_of_funds, context_specific]}}`.
`months_to_first_cashflow` — целое или null, остальные три компоненты — целые 0/1, 0–3 и 0/1.
"""
    (OUT / "README.md").write_text(body, encoding="utf-8")
    print(OUT / "README.md")


def main() -> None:
    _train_rows, holdout = prepare()
    base_eval = None
    tuned_eval = None
    note = ""
    try:
        print("нулевая проверка базы")
        base_eval = exact_match(holdout, None)
        print("max prompt tokens", base_eval["max_prompt_tokens"], "exact", base_eval["exact_rate"])
    except Exception as exc:  # noqa: BLE001
        note = f"База не посчиталась: {exc}."
        print(note)
    code = 1
    try:
        code = train()
    except Exception as exc:  # noqa: BLE001
        note = f"Запуск дообучения упал: {exc}."
        print(note)
    if code != 0:
        note = note or f"Дообучение завершилось с кодом {code}."
    else:
        try:
            tuned_eval = exact_match(holdout, ADAPTER)
            print("tuned exact", tuned_eval["exact_rate"])
        except Exception as exc:  # noqa: BLE001
            note = f"Адаптер не прочитался: {exc}."
            print(note)
    base_rate = base_eval["exact_rate"] if base_eval else 0.0
    tuned_rate = tuned_eval["exact_rate"] if tuned_eval else 0.0
    kept = tuned_eval is not None and tuned_rate >= 0.75 and tuned_rate + 1e-9 >= base_rate
    if not kept and not note:
        note = (
            f"Точное совпадение после LoRA {tuned_rate:.0%} при базе {base_rate:.0%}. "
            "На отложенных парах четыре компоненты целиком не держатся, поэтому остаётся промпт."
        )
    (OUT / "eval.json").write_text(
        json.dumps(
            {"base": base_eval, "tuned": tuned_eval, "kept_weights": kept},
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    write_readme(base_eval, tuned_eval, kept, note)


if __name__ == "__main__":
    main()
