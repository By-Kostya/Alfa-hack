#!/usr/bin/env python3
"""Обучает скоринговый MLP на метках trust и пишет влияния входов и пороги.

Вход — 14 чисел: девять полей анкеты, четыре компоненты вектора
(пустые месяцы до потока как 0) и флаг «срок не назван».
Один скрытый слой, на выходе сигмоида. Веса учатся градиентом, не задаются таблицей.
Пороги считаются по разбросу trust на отложенных анкетах и пишутся отдельно от весов.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import torch
from torch import nn

ROOT = Path(__file__).resolve().parents[1]
ANKETY = ROOT / "Анкеты" / "ankety_with_vector.jsonl"
LABELS = ROOT / "Анкеты" / "trust_labels.jsonl"
MODEL_DIR = ROOT / "models" / "scorer"

MONEY_SCALE = 1_000_000.0
RATING_SCALE = 1000.0
MONTHS_SCALE = 12.0
SEED = 23
HOLDOUT = 0.2
HIDDEN = 64

FEATURE_NAMES = [
    "выручка",
    "расходы",
    "свои деньги",
    "доход подтверждён",
    "расходы подтверждены",
    "капитал подтверждён",
    "сумма займа",
    "срок займа, мес.",
    "рейтинг",
    "месяцы до потока",
    "есть договор",
    "назначение",
    "конкретный контекст",
    "срок до потока не назван",
]

USE_NAME = {0: "не сказано", 1: "запуск", 2: "оборудование", 3: "оборотные средства"}


class Scorer(nn.Module):
    def __init__(self, n_in: int = 14, hidden: int = HIDDEN) -> None:
        super().__init__()
        self.hidden = nn.Linear(n_in, hidden)
        self.out = nn.Linear(hidden, 1)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return torch.sigmoid(self.out(torch.relu(self.hidden(x)))).squeeze(-1)


def load_rows() -> list[dict]:
    labels = {
        row["id"]: row["trust"]
        for row in (
            json.loads(line)
            for line in LABELS.read_text(encoding="utf-8").splitlines()
            if line.strip()
        )
    }
    rows = []
    for line in ANKETY.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        row["trust"] = labels[row["id"]]
        rows.append(row)
    if len(rows) != 11025:
        raise SystemExit(f"ожидалось 11025 строк, есть {len(rows)}")
    return rows


def featurize(row: dict) -> np.ndarray:
    feat = row["scoring_features"]
    months, has_contract, use, context = row["llm_vector"]
    money = lambda value: 0.0 if value is None else float(value) / MONEY_SCALE
    return np.array(
        [
            money(feat["revenue_monthly_rub"]),
            money(feat["costs_monthly_rub"]),
            money(feat["own_funds_rub"]),
            float(bool(feat["income_confirmed"])),
            float(bool(feat["costs_confirmed"])),
            float(bool(feat["capital_confirmed"])),
            money(feat["loan_amount_rub"]),
            float(feat["loan_term_months"]),
            float(feat["credit_rating"]) / RATING_SCALE,
            0.0 if months is None else float(months) / MONTHS_SCALE,
            float(has_contract),
            float(use),
            float(context),
            1.0 if months is None else 0.0,
        ],
        dtype=np.float32,
    )


def regression_scores(y: np.ndarray, pred: np.ndarray) -> tuple[float, float]:
    mae = float(np.mean(np.abs(y - pred)))
    ss_tot = float(np.sum((y - y.mean()) ** 2))
    ss_res = float(np.sum((y - pred) ** 2))
    r2 = 1.0 - ss_res / ss_tot if ss_tot else 0.0
    return mae, r2


def predict(model: Scorer, x: np.ndarray) -> np.ndarray:
    model.eval()
    with torch.no_grad():
        out = model(torch.from_numpy(x)).numpy()
    return out.astype(np.float64)


def train(x: np.ndarray, y: np.ndarray, train_idx: np.ndarray, val_idx: np.ndarray) -> Scorer:
    torch.manual_seed(SEED)
    model = Scorer()
    opt = torch.optim.AdamW(model.parameters(), lr=1e-3, weight_decay=1e-4)
    loss_fn = nn.MSELoss()
    x_train = torch.from_numpy(x[train_idx])
    y_train = torch.from_numpy(y[train_idx])
    x_val = torch.from_numpy(x[val_idx])
    y_val = torch.from_numpy(y[val_idx])
    best_state = None
    best_val = float("inf")
    wait = 0
    rng = np.random.default_rng(SEED)
    for _epoch in range(400):
        model.train()
        order = rng.permutation(len(train_idx))
        for start in range(0, len(order), 512):
            batch = order[start : start + 512]
            pred = model(x_train[batch])
            loss = loss_fn(pred, y_train[batch])
            opt.zero_grad()
            loss.backward()
            opt.step()
        model.eval()
        with torch.no_grad():
            val_loss = float(loss_fn(model(x_val), y_val))
        if val_loss < best_val - 1e-5:
            best_val = val_loss
            best_state = {key: value.detach().clone() for key, value in model.state_dict().items()}
            wait = 0
        else:
            wait += 1
            if wait >= 25:
                break
    model.load_state_dict(best_state)
    return model


def fmt_num(value: float) -> str:
    return f"{value:.3f}"


def rub(value: int) -> str:
    return f"{int(value):,}".replace(",", " ")


def cell(mean: float | None, count: int) -> str:
    if count == 0 or mean is None:
        return "—"
    return f"{mean:.3f} (n={count})"


def two_way(rows: list[dict], pred: np.ndarray, row_key, col_key, row_order, col_order) -> list[list[str]]:
    buckets: dict[tuple, list[float]] = {}
    for index, row in enumerate(rows):
        buckets.setdefault((row_key(row), col_key(row)), []).append(float(pred[index]))
    table = []
    for row_value in row_order:
        line = []
        for col_value in col_order:
            values = buckets.get((row_value, col_value), [])
            line.append(cell(float(np.mean(values)) if values else None, len(values)))
        table.append(line)
    return table


def markdown_table(headers: list[str], body: list[list[str]]) -> str:
    head = "| " + " | ".join(headers) + " |"
    sep = "| " + " | ".join("---" for _ in headers) + " |"
    lines = [head, sep]
    for row in body:
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


def money_label(value) -> str:
    if value is None:
        return "не указана"
    return f"{int(value):,}".replace(",", " ") + " руб."


def cost_bucket(row: dict) -> str:
    feat = row["scoring_features"]
    revenue = feat["revenue_monthly_rub"]
    costs = feat["costs_monthly_rub"]
    if costs is None:
        return "расходы не указаны"
    if revenue is None:
        return "выручка не указана"
    ratio = costs / revenue
    if abs(ratio - 0.55) < 0.02:
        return "0,55 от выручки"
    if abs(ratio - 0.90) < 0.02:
        return "0,90 от выручки"
    if abs(ratio - 1.25) < 0.02:
        return "1,25 от выручки"
    return f"{ratio:.2f} от выручки"


def months_label(row: dict) -> str:
    months = row["llm_vector"][0]
    if months is None:
        return "не назван"
    return str(months)


def field_text(row: dict, index: int) -> str:
    feat = row["scoring_features"]
    months, has_contract, use, context = row["llm_vector"]
    if index == 0:
        return money_label(feat["revenue_monthly_rub"])
    if index == 1:
        return money_label(feat["costs_monthly_rub"])
    if index == 2:
        return money_label(feat["own_funds_rub"])
    if index == 3:
        return "да" if feat["income_confirmed"] else "нет"
    if index == 4:
        return "да" if feat["costs_confirmed"] else "нет"
    if index == 5:
        return "да" if feat["capital_confirmed"] else "нет"
    if index == 6:
        return money_label(feat["loan_amount_rub"])
    if index == 7:
        return f"{feat['loan_term_months']} мес."
    if index == 8:
        return str(feat["credit_rating"])
    if index == 9:
        return "не назван" if months is None else f"{months} мес."
    if index == 10:
        return "да" if has_contract else "нет"
    if index == 11:
        return USE_NAME[int(use)]
    if index == 12:
        return "да" if context else "нет"
    return "да" if months is None else "нет"


def write_config(holdout_mae: float, holdout_r2: float) -> None:
    features = [
        {"index": 0, "name": "revenue_monthly_rub", "transform": "null → 0, делить на money_scale_rub"},
        {"index": 1, "name": "costs_monthly_rub", "transform": "null → 0, делить на money_scale_rub"},
        {"index": 2, "name": "own_funds_rub", "transform": "null → 0, делить на money_scale_rub"},
        {"index": 3, "name": "income_confirmed", "transform": "0/1"},
        {"index": 4, "name": "costs_confirmed", "transform": "0/1"},
        {"index": 5, "name": "capital_confirmed", "transform": "0/1"},
        {"index": 6, "name": "loan_amount_rub", "transform": "делить на money_scale_rub"},
        {"index": 7, "name": "loan_term_months", "transform": "как есть, в месяцах"},
        {"index": 8, "name": "credit_rating", "transform": "делить на rating_scale"},
        {"index": 9, "name": "months_to_first_cashflow", "transform": "null → 0, делить на months_scale"},
        {"index": 10, "name": "has_contract", "transform": "0/1"},
        {"index": 11, "name": "use_of_funds", "transform": "0 запуск не сказан, 1 запуск, 2 оборудование, 3 оборотные"},
        {"index": 12, "name": "context_specific", "transform": "0/1"},
        {"index": 13, "name": "months_not_stated", "transform": "1, если месяцы до потока пустые"},
    ]
    payload = {
        "architecture": "mlp",
        "hidden_layers": 1,
        "hidden_size": HIDDEN,
        "hidden_activation": "relu",
        "output_activation": "sigmoid",
        "loss": "mse",
        "optimizer": "adamw",
        "money_scale_rub": MONEY_SCALE,
        "rating_scale": RATING_SCALE,
        "months_to_cashflow_scale": MONTHS_SCALE,
        "features": features,
        "target": "trust",
        "seed": SEED,
        "holdout_fraction": HOLDOUT,
        "holdout_mae": round(holdout_mae, 4),
        "holdout_r2": round(holdout_r2, 4),
        "weights_file": "weights.pt",
        "torch": torch.__version__,
    }
    (MODEL_DIR / "config.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    rows = load_rows()
    x = np.stack([featurize(row) for row in rows])
    y = np.array([row["trust"] for row in rows], dtype=np.float32)
    rng = np.random.default_rng(SEED)
    order = rng.permutation(len(rows))
    hold_n = int(round(len(rows) * HOLDOUT))
    hold_idx = order[:hold_n]
    rest = order[hold_n:]
    val_n = int(round(len(rest) * 0.15))
    val_idx = rest[:val_n]
    train_idx = rest[val_n:]

    model = train(x, y, train_idx, val_idx)
    hold_pred = predict(model, x[hold_idx])
    hold_y = y[hold_idx].astype(np.float64)
    mae, r2 = regression_scores(hold_y, hold_pred)
    print(f"holdout n={hold_n} MAE={mae:.4f} R2={r2:.4f}")

    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    torch.save(model.state_dict(), MODEL_DIR / "weights.pt")
    write_config(mae, r2)

    # Перестановка каждого входа.
    base_mae, base_r2 = mae, r2
    perm_rows = []
    perm_rng = np.random.default_rng(SEED + 1)
    for feature in range(x.shape[1]):
        maes = []
        r2s = []
        for _ in range(8):
            shuffled = x[hold_idx].copy()
            shuffled[:, feature] = perm_rng.permutation(shuffled[:, feature])
            pred = predict(model, shuffled)
            one_mae, one_r2 = regression_scores(hold_y, pred)
            maes.append(one_mae)
            r2s.append(one_r2)
        perm_mae = float(np.mean(maes))
        perm_r2 = float(np.mean(r2s))
        perm_rows.append(
            (
                base_r2 - perm_r2,
                perm_mae - base_mae,
                FEATURE_NAMES[feature],
                perm_r2,
                perm_mae,
            )
        )
    perm_rows.sort(reverse=True)

    hold_rows = [rows[i] for i in hold_idx]
    revenue_order = [None, 80000, 400000, 1500000]
    revenue_names = ["не указана", "80 000", "400 000", "1 500 000"]
    confirmed_order = [False, True]
    cost_order = [
        "расходы не указаны",
        "0,55 от выручки",
        "0,90 от выручки",
        "1,25 от выручки",
    ]
    revenue_present = [80000, 400000, 1500000]
    rating_order = [50, 280, 500, 750, 930]
    loan_order = [300000, 800000, 2000000]
    loan_names = ["300 000", "800 000", "2 000 000"]
    contract_order = [0, 1]
    months_order = ["не назван", "0", "2", "6", "10"]

    rev_conf = two_way(
        hold_rows,
        hold_pred,
        lambda row: row["scoring_features"]["revenue_monthly_rub"],
        lambda row: row["scoring_features"]["income_confirmed"],
        revenue_order,
        confirmed_order,
    )
    cost_rev = two_way(
        [row for row in hold_rows if row["scoring_features"]["revenue_monthly_rub"] is not None],
        np.array(
            [
                hold_pred[i]
                for i, row in enumerate(hold_rows)
                if row["scoring_features"]["revenue_monthly_rub"] is not None
            ]
        ),
        lambda row: row["scoring_features"]["revenue_monthly_rub"],
        cost_bucket,
        revenue_present,
        cost_order,
    )
    rating_loan = two_way(
        hold_rows,
        hold_pred,
        lambda row: row["scoring_features"]["credit_rating"],
        lambda row: row["scoring_features"]["loan_amount_rub"],
        rating_order,
        loan_order,
    )
    contract_months = two_way(
        hold_rows,
        hold_pred,
        lambda row: row["llm_vector"][1],
        months_label,
        contract_order,
        months_order,
    )

    # Три анкеты с самым сильным сдвигом относительно медианы обучения.
    # Путь от медианы к анкете: на каждом шаге подставляется поле, которое сильнее всего двигает доверие.
    baseline = np.median(x[train_idx], axis=0).astype(np.float32)
    baseline_pred = float(predict(model, baseline.reshape(1, -1))[0])
    candidates = []
    for local, _row_index in enumerate(hold_idx):
        pred = float(hold_pred[local])
        candidates.append((abs(pred - baseline_pred), pred - baseline_pred, local))
    candidates.sort(reverse=True)

    def greedy_path(local: int) -> list[tuple[int, float, float]]:
        row_index = int(hold_idx[local])
        current = baseline.copy()
        current_pred = baseline_pred
        remaining = [
            feature
            for feature in range(x.shape[1])
            if abs(float(x[row_index, feature]) - float(baseline[feature])) > 1e-6
        ]
        path: list[tuple[int, float, float]] = []
        while remaining:
            best_step = None
            best_feature = remaining[0]
            best_pred = current_pred
            best_vector = current
            for feature in remaining:
                trial = current.copy()
                trial[feature] = x[row_index, feature]
                trial_pred = float(predict(model, trial.reshape(1, -1))[0])
                step = trial_pred - current_pred
                if best_step is None or abs(step) > abs(best_step):
                    best_step = step
                    best_feature = feature
                    best_pred = trial_pred
                    best_vector = trial
            path.append((best_feature, float(best_step), float(best_pred)))
            current = best_vector
            current_pred = best_pred
            remaining.remove(best_feature)
        return path

    examples = [
        (abs_shift, shift, local, greedy_path(local))
        for abs_shift, shift, local in candidates[:3]
    ]

    # Пороги по разбросу trust на отложенных анкетах.
    trust_quantile = 0.25
    trust_threshold = float(np.quantile(hold_pred, trust_quantile))
    amount_medians = {}
    for amount in loan_order:
        mask = np.array(
            [row["scoring_features"]["loan_amount_rub"] == amount for row in hold_rows]
        )
        amount_medians[amount] = float(np.median(hold_pred[mask]))
    best_median = max(amount_medians.values())
    worst_median = min(amount_medians.values())
    midpoint = (best_median + worst_median) / 2.0
    passed = [amount for amount in loan_order if amount_medians[amount] >= midpoint]
    money_threshold = max(passed) if passed else loan_order[0]
    trusted = np.array(
        [row["scoring_features"]["loan_amount_rub"] for row in hold_rows]
    )[hold_pred >= trust_threshold]
    money_quantile = float(np.mean(trusted <= money_threshold)) if len(trusted) else 0.0

    decisions = []
    for row, pred in zip(hold_rows, hold_pred):
        amount = row["scoring_features"]["loan_amount_rub"]
        if pred < trust_threshold:
            decisions.append("reject")
        elif amount <= money_threshold:
            decisions.append("approve")
        else:
            decisions.append("human")
    counts = {name: decisions.count(name) for name in ("reject", "approve", "human")}

    thresholds = {
        "trust_threshold": round(trust_threshold, 4),
        "trust_quantile": trust_quantile,
        "trust_quantile_of": "предсказанный trust на отложенных анкетах",
        "money_threshold_rub": int(money_threshold),
        "money_quantile": round(money_quantile, 4),
        "money_quantile_of": "доля отложенных анкет с trust не ниже порога, у которых сумма займа не выше денежного порога",
        "holdout_size": int(hold_n),
        "holdout_trust_min": round(float(hold_pred.min()), 4),
        "holdout_trust_p25": round(trust_threshold, 4),
        "holdout_trust_p50": round(float(np.quantile(hold_pred, 0.5)), 4),
        "holdout_trust_p75": round(float(np.quantile(hold_pred, 0.75)), 4),
        "holdout_trust_max": round(float(hold_pred.max()), 4),
        "amount_median_trust": {str(key): round(value, 4) for key, value in amount_medians.items()},
        "decisions_on_holdout": counts,
        "rules": {
            "reject": "trust < trust_threshold",
            "approve": "trust >= trust_threshold и loan_amount_rub <= money_threshold_rub",
            "human": "trust >= trust_threshold и loan_amount_rub > money_threshold_rub",
        },
    }
    (MODEL_DIR / "thresholds.json").write_text(
        json.dumps(thresholds, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    conf_lifts = []
    for revenue, name in zip(revenue_order, revenue_names):
        mask_yes = np.array(
            [
                row["scoring_features"]["revenue_monthly_rub"] == revenue
                and row["scoring_features"]["income_confirmed"]
                for row in hold_rows
            ]
        )
        mask_no = np.array(
            [
                row["scoring_features"]["revenue_monthly_rub"] == revenue
                and not row["scoring_features"]["income_confirmed"]
                for row in hold_rows
            ]
        )
        if mask_yes.any() and mask_no.any():
            conf_lifts.append((name, float(hold_pred[mask_yes].mean() - hold_pred[mask_no].mean())))

    rating_gaps = []
    for amount, name in zip(loan_order, loan_names):
        high = np.array(
            [
                row["scoring_features"]["loan_amount_rub"] == amount
                and row["scoring_features"]["credit_rating"] == 930
                for row in hold_rows
            ]
        )
        low = np.array(
            [
                row["scoring_features"]["loan_amount_rub"] == amount
                and row["scoring_features"]["credit_rating"] == 50
                for row in hold_rows
            ]
        )
        if high.any() and low.any():
            rating_gaps.append((name, float(hold_pred[high].mean() - hold_pred[low].mean())))

    contract_lifts = []
    for label in months_order:
        yes = np.array(
            [row["llm_vector"][1] == 1 and months_label(row) == label for row in hold_rows]
        )
        no = np.array(
            [row["llm_vector"][1] == 0 and months_label(row) == label for row in hold_rows]
        )
        if yes.any() and no.any():
            contract_lifts.append((label, float(hold_pred[yes].mean() - hold_pred[no].mean())))

    perm_body = [
        [name, fmt_num(perm_r2), fmt_num(drop_r2), fmt_num(rise_mae)]
        for drop_r2, rise_mae, name, perm_r2, _perm_mae in perm_rows
    ]
    example_blocks = []
    for rank, (_abs_shift, shift, local, path) in enumerate(examples, start=1):
        row = hold_rows[local]
        pred = float(hold_pred[local])
        field_lines = []
        for feature, step, after in path:
            if abs(step) < 0.01 and len(field_lines) >= 3:
                continue
            field_lines.append(
                f"- {FEATURE_NAMES[feature]}: {field_text(row, feature)}, шаг {step:+.3f}, доверие стало {after:.3f}"
            )
            if len(field_lines) == 6:
                break
        example_blocks.append(
            "\n".join(
                [
                    f"### {rank}. {row['id']}",
                    "",
                    f"Доверие модели {pred:.3f} против {baseline_pred:.3f} на медианной анкете обучения, сдвиг {shift:+.3f}. Метка разметчика {row['trust']:.3f}.",
                    "",
                    "Поля по пути от медианы к этой анкете, каждое следующее сильнее остальных двигает доверие:",
                    "",
                    *field_lines,
                ]
            )
        )

    amount_median_text = ", ".join(
        f"{name} руб. → {amount_medians[amount]:.3f}"
        for amount, name in zip(loan_order, loan_names)
    )
    effects = f"""# Как входы скорера влияют друг на друга

Модель — MLP с одним скрытым слоем на {HIDDEN} нейронов и сигмоидой на выходе. Цель — trust разметчика. Метрики ниже посчитаны на отложенных {hold_n} анкетах (доля {int(HOLDOUT * 100)}%, сид {SEED}), которые не входили в обучение.

На отложенных анкетах MAE = {base_mae:.4f}, R² = {base_r2:.4f}.

Деньги поделены на {rub(int(MONEY_SCALE))} руб., рейтинг на {int(RATING_SCALE)}, месяцы до потока на {int(MONTHS_SCALE)}. Пустые месяцы до потока записаны как 0, отдельным входом идёт флаг «срок не назван». Срок займа оставлен в месяцах.

## Перестановка каждого входа

Каждый вход по очереди перемешан на отложенных анкетах, остальные не трогались. Качество — R² и MAE, усреднение по 8 перестановкам. Падение R² и рост MAE показывают, насколько вход нужен модели.

{markdown_table(["Вход", "R² после перестановки", "Падение R²", "Рост MAE"], perm_body)}

## Срезы пар

В ячейках среднее предсказание модели и число анкет. Срез показывает, как один вход меняет доверие в зависимости от второго.

### Выручка и флаг подтверждения дохода

В сетке анкет нет подтверждённого дохода без названной выручки, поэтому пустая строка есть только в столбце «не подтверждён». Там, где сумма названа, флаг поднимает доверие примерно на 0,15, и прибавка чуть растёт вместе с выручкой.

{markdown_table(["Выручка, руб.", "доход не подтверждён", "доход подтверждён"], [[name, *line] for name, line in zip(revenue_names, rev_conf)])}

Прибавка доверия от флага подтверждения:

{chr(10).join(f"- {name}: {value:+.3f}" for name, value in conf_lifts)}

### Расходы и выручка

Одни и те же расходы читаются через долю от выручки. Доля 0,55 держит доверие выше, доля 1,25 его снижает, и этот зазор виден на каждом уровне выручки.

{markdown_table(["Выручка, руб.", *cost_order], [[name, *line] for name, line in zip(["80 000", "400 000", "1 500 000"], cost_rev)])}

### Рейтинг и сумма займа

Разрыв между рейтингом 930 и 50 шире на большой сумме: низкий рейтинг рядом с крупным займом тянет доверие вниз сильнее, чем рядом с маленьким.

{markdown_table(["Рейтинг", *loan_names], [[str(rating), *line] for rating, line in zip(rating_order, rating_loan)])}

Прибавка доверия от рейтинга 930 против 50:

{chr(10).join(f"- сумма {name} руб.: {value:+.3f}" for name, value in rating_gaps)}

### Договор и месяцы до потока

Прибавка от договора больше, когда срок до потока назван, чем когда он пустой. Уровень в столбце «6» ниже соседних: у двух планов с этим сроком назначение средств не сказано, и срез мешает срок с назначением. Сравнение договора при одном и том же сроке эту смесь не использует.

{markdown_table(["Договор", *months_order], [["да" if flag else "нет", *line] for flag, line in zip(contract_order, contract_months)])}

Прибавка доверия от договора при том же сроке:

{chr(10).join(f"- месяцы до потока {name}: {value:+.3f}" for name, value in contract_lifts)}

## Три анкеты с самым сильным сдвигом

База сравнения — анкета из медиан обучающих входов, её доверие {baseline_pred:.3f}. Поля идут по одному от этой базы к анкете: на шаге берётся поле, которое сильнее остальных меняет доверие. Так видно совместный сдвиг, а не отдачу одного входа при уже зажатой сигмоиде.

{chr(10).join(chr(10) + block for block in example_blocks)}

## Пороги

Порог доверия — квантиль {trust_quantile:.2f} предсказанного trust на отложенных анкетах: {trust_threshold:.4f}. Ниже него заявка идёт в отказ.

Денежный порог подобран по тому, как медиана доверия на тех же анкетах расходится по сумме займа ({amount_median_text}). Середина между самой высокой и самой низкой медианой отсекает суммы, на которых доверие уже слабее. Порог равен {rub(money_threshold)} руб. Среди отложенных анкет с доверием не ниже порога доля сумм не выше этого порога — {money_quantile:.2f}, это и есть записанный денежный квантиль.

На отложенных анкетах решения разошлись так: отказ {counts["reject"]}, одобрение {counts["approve"]}, человеку {counts["human"]}.
"""
    (MODEL_DIR / "effects.md").write_text(effects, encoding="utf-8")
    print(MODEL_DIR / "weights.pt")
    print(MODEL_DIR / "effects.md")
    print(MODEL_DIR / "thresholds.json")
    print("decisions", counts)


if __name__ == "__main__":
    main()
