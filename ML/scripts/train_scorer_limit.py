#!/usr/bin/env python3
"""Новый скорер лимита. Старые models/scorer/weights.pt не читает и не пишет.

Энкодер не запускается и не дообучается: берётся Анкеты/encoder_reports.jsonl.
Платёж считается здесь, аннуитетом. Поля coverage и monthly_payment энкодера
в отчёт не входят.
"""

from __future__ import annotations

import json
import sys
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

import numpy as np
import torch
from torch import nn

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "Анкеты" / "encoder_reports.jsonl"
TASKS = ROOT / "Анкеты" / "scorer_tasks.jsonl"
LABELS = ROOT / "Анкеты" / "agent_limits.jsonl"
MISSES = ROOT / "Анкеты" / "scorer_misses.jsonl"
MODEL_DIR = ROOT / "models" / "scorer_limit"
OLD_WEIGHTS = ROOT / "models" / "scorer" / "weights.pt"

MONEY_SCALE = 1_000_000.0
RATING_SCALE = 1000.0
RATE = Decimal("0.20")
TERM = 12
SEED = 23
HOLDOUT = 0.2
HIDDEN = 256
AMOUNTS = (300_000, 800_000, 2_000_000)
RATINGS = (50, 280, 500, 750, 930)
OWN_FUNDS = (None, 100_000, 700_000)
LIMITS = (0, 300_000, 800_000, 2_000_000)

# Порядок как в промпте энкодера. Холодный старт в этих отчётах не встретился,
# столбец остаётся нулевым, чтобы каждый допустимый риск был входом.
RISKS = (
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
)

RISK_RU = {
    "thin_margin": "тонкая маржа",
    "rent": "аренда",
    "slow_ramp": "медленный выход на режим",
    "client_concentration": "концентрация клиентов",
    "lumpy_revenue": "рваная выручка",
    "seasonality": "сезонность",
    "fixed_costs": "постоянные расходы",
    "location": "привязка к месту",
    "negative_unit_economics": "отрицательная юнит-экономика",
    "subsidies": "зависимость от субсидий",
    "competition": "конкуренция",
    "rare_payment": "редкие платежи",
    "unclear_payer": "непонятно, кто платит",
    "small_market": "узкий рынок",
    "cold_start": "холодный старт",
    "fraud": "мошенничество",
    "late_monetization": "поздняя монетизация",
    "inventory": "товарный запас",
    "customs": "таможня",
    "returns": "возвраты",
    "fx": "валютный курс",
}


def load_jsonl(path: Path) -> list[dict]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def dump_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def rub(value: int) -> str:
    return f"{int(value):,}".replace(",", " ")


def own_text(value: int | None) -> str:
    if value is None:
        return "свои деньги не указаны, доход и капитал не подтверждены"
    return f"свои деньги {rub(value)} руб"


def risks_text(risks: list[str]) -> str:
    return ", ".join(RISK_RU[name] for name in risks)


def annuity(principal: int, term: int = TERM) -> int:
    monthly = RATE / Decimal(12)
    power = (1 + monthly) ** term
    raw = Decimal(principal) * monthly * power / (power - 1)
    return int(raw.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def coverage_cap(flow: int, amount: int) -> int:
    cap = 0
    for tier in AMOUNTS:
        if tier <= amount and flow >= annuity(tier):
            cap = tier
    return cap


def task_id(plan_file: str, amount: int, rating: int, own: int | None) -> str:
    stem = Path(plan_file).stem[:2]
    own_part = "null" if own is None else str(own)
    return f"limit-{stem}-a{amount}-r{rating}-own-{own_part}"


def is_it(flow: int, risks: set[str]) -> bool:
    return flow >= 150_000 and "lumpy_revenue" in risks and "client_concentration" in risks


def decide(row: dict) -> tuple[int, str]:
    """Лимит разметчика. Скорер к этому моменту ещё ничего не предсказывал.

    Сравнение — поток против аннуитета. Выше запрошенной суммы лимит не ставится.
    Ноль — отказ. Слабый и отрицательный поток не получают 2 000 000.
    IT около 160 000 не срезается до 800 000, если рейтинг не обвальный (обвальный — 50).
    Доставка, поиск собаки и барахолка полный запрос не получают.
    """
    report = row["encoder"]
    flow = int(report["inferred_monthly_flow_rub"])
    risks = list(report["risks"])
    risk_set = set(risks)
    amount = int(row["loan_amount_rub"])
    payment = int(row["monthly_payment_rub"])
    rating = int(row["credit_rating"])
    own = row["own_funds_rub"]
    named = risks_text(risks)
    gap = flow - payment

    if flow <= 0:
        return (
            0,
            f"Поток {rub(flow)} руб. в месяц, платёж по запросу {rub(amount)} равен {rub(payment)} руб. "
            f"Гасить нечем: дело каждый месяц в минусе. Риски: {named}. "
            f"Полный запрос не даю и меньший лимит тоже не даю — отрицательный поток не обслуживает ни одну сумму. Отказ.",
        )

    if is_it(flow, risk_set):
        if rating >= 280:
            if amount == 2_000_000:
                return (
                    2_000_000,
                    f"Поток {rub(flow)} руб., аннуитет на 2 000 000 равен {rub(payment)} руб., "
                    f"недобор {rub(payment - flow)} руб. в месяц. Это не слабый поток. "
                    f"Рейтинг {rating} не обвальный, поэтому до 800 000 не срезаю. "
                    f"{own_text(own).capitalize()}. Риски: {named}. Лимит 2 000 000.",
                )
            return (
                amount,
                f"Поток {rub(flow)} руб. против платежа {rub(payment)} руб., запас {rub(gap)} руб. "
                f"Рейтинг {rating} не обвальный, риски ({named}) этот запас не съедают. "
                f"{own_text(own).capitalize()}. Лимит равен запросу {rub(amount)}.",
            )
        return (
            300_000,
            f"Поток {rub(flow)} руб. закрыл бы и платёж 74 108 на 800 000, но рейтинг {rating} обвальный, "
            f"а выручка рваная и сидит на нескольких клиентах. На 2 000 000 платёж 185 269 уже выше потока. "
            f"Оставляю 300 000: платёж {rub(annuity(300_000))} поток держит с большим запасом. Выше не иду.",
        )

    cap = coverage_cap(flow, amount)
    tight = flow < annuity(800_000)
    pay_300 = annuity(300_000)
    pay_800 = annuity(800_000)
    pay_2000 = annuity(2_000_000)

    if cap == 0:
        return (
            0,
            f"Поток {rub(flow)} руб. ниже даже платежа {rub(pay_300)} на 300 000. Риски: {named}. Отказ.",
        )

    if own is None:
        return (
            0,
            f"Поток {rub(flow)} руб., платёж на запрошенные {rub(amount)} равен {rub(payment)} руб. "
            f"Свои деньги не указаны, доход и капитал не подтверждены, опереться не на что. Риски: {named}. Отказ.",
        )

    if rating <= 50:
        if (not tight) and own >= 700_000:
            return (
                300_000,
                f"Поток {rub(flow)} руб. покрывает платёж {rub(pay_800)} на 800 000, но рейтинг {rating} обвальный. "
                f"Свои {rub(own)} руб. и запас потока позволяют только малый лимит: платёж {rub(pay_300)}. "
                f"На 2 000 000 платёж {rub(pay_2000)} выше потока. Риски: {named}. Лимит 300 000.",
            )
        return (
            0,
            f"Поток {rub(flow)} руб., рейтинг {rating} обвальный, {own_text(own)}. "
            f"Риски: {named}. Запас над платежом слишком тонкий для такого рейтинга. Отказ.",
        )

    if rating <= 280:
        if own >= 700_000:
            return (
                min(cap, 300_000),
                f"Поток {rub(flow)} руб. Рейтинг {rating} слабый, хотя и не обвальный. "
                f"Свои {rub(own)} руб. тянут малый платёж {rub(pay_300)}, но не больший лимит. "
                f"Риски: {named}. Лимит 300 000.",
            )
        return (
            0,
            f"Поток {rub(flow)} руб., свои только {rub(own)} руб., рейтинг {rating} слабый. Риски: {named}. "
            f"Подушки на эти риски нет. Отказ.",
        )

    if tight:
        return (
            min(cap, 300_000),
            f"Поток {rub(flow)} руб. покрывает только платёж {rub(pay_300)} и не покрывает {rub(pay_800)} и {rub(pay_2000)}. "
            f"Слабый поток на 2 000 000 не получает 2 000 000 и не получает 800 000. "
            f"{own_text(own).capitalize()}, рейтинг {rating}. Риски: {named}. Лимит 300 000.",
        )

    if own >= 700_000:
        limit = cap
        if amount >= 2_000_000 and limit < amount:
            return (
                limit,
                f"Поток {rub(flow)} руб. покрывает платёж {rub(pay_800)} на 800 000 "
                f"(запас {rub(flow - pay_800)}) и не покрывает платёж {rub(pay_2000)} на 2 000 000. "
                f"Для двух миллионов поток слабый. Свои {rub(own)} руб. и рейтинг {rating} подтверждают 800 000, не выше. "
                f"Риски: {named}. Лимит {rub(limit)}.",
            )
        return (
            limit,
            f"Поток {rub(flow)} руб. против платежа {rub(payment)}, запас {rub(gap)} руб. "
            f"Свои {rub(own)} руб. закрывают просадку по рискам ({named}), рейтинг {rating}. "
            f"Лимит {rub(limit)}.",
        )

    limit = min(cap, 300_000)
    if limit == amount:
        return (
            limit,
            f"Поток {rub(flow)} руб. закрывает платёж {rub(payment)} по запросу {rub(amount)}. "
            f"Свои деньги только {rub(own)} руб., для большего лимита этой подушки мало. Риски: {named}. Рейтинг {rating}. "
            f"Платёж на 800 000 равен {rub(pay_800)}, на 2 000 000 — {rub(pay_2000)}, и крупный платёж поток уже не несёт. "
            f"Лимит {rub(limit)}.",
        )
    return (
        limit,
        f"Средний поток {rub(flow)} руб. выше платежа {rub(pay_800)} на 800 000, "
        f"но свои деньги только {rub(own)} руб. и не держат просадку. Риски: {named}. Рейтинг {rating}. "
        f"На 2 000 000 платёж {rub(pay_2000)} и вовсе выше потока. Режу до 300 000: платёж {rub(pay_300)} поток закрывает.",
    )


def build_tasks(reports: list[dict]) -> list[dict]:
    rows = []
    for report in reports:
        quote = report["quote"]
        if not quote:
            continue
        for amount in AMOUNTS:
            for rating in RATINGS:
                for own in OWN_FUNDS:
                    confirmed = own is not None
                    rows.append(
                        {
                            "id": task_id(report["plan_file"], amount, rating, own),
                            "own_funds_rub": own,
                            "income_confirmed": confirmed,
                            "costs_confirmed": False,
                            "capital_confirmed": confirmed,
                            "loan_amount_rub": amount,
                            "loan_term_months": TERM,
                            "credit_rating": rating,
                            "encoder": {
                                "plan_file": report["plan_file"],
                                "inferred_monthly_flow_rub": report["inferred_monthly_flow_rub"],
                                "flow_basis": report["flow_basis"],
                                "risks": list(report["risks"]),
                                "quote": quote,
                            },
                            "monthly_payment_rub": annuity(amount),
                        }
                    )
    return rows


def check_policy(rows: list[dict], labels: dict[str, dict]) -> None:
    counts: dict[str, int] = {}
    by_limit: dict[int, int] = {value: 0 for value in LIMITS}
    for row in rows:
        plan = row["encoder"]["plan_file"]
        counts[plan] = counts.get(plan, 0) + 1
        limit = labels[row["id"]]["limit_rub"]
        if limit not in LIMITS:
            raise SystemExit(f"{row['id']}: лимит {limit} вне шкалы")
        if limit > row["loan_amount_rub"]:
            raise SystemExit(f"{row['id']}: лимит выше запроса")
        flow = row["encoder"]["inferred_monthly_flow_rub"]
        if flow <= 0 and limit == row["loan_amount_rub"]:
            raise SystemExit(f"{row['id']}: отрицательный поток получил полный запрос")
        if flow < 100_000 and limit == 2_000_000:
            raise SystemExit(f"{row['id']}: слабый поток получил 2 000 000")
        by_limit[limit] += 1
        risks = set(row["encoder"]["risks"])
        if is_it(flow, risks) and row["credit_rating"] >= 280 and limit != row["loan_amount_rub"]:
            raise SystemExit(f"{row['id']}: IT срезан при рейтинге {row['credit_rating']}")
        weak_full = {"04_доставка", "05_найди_собаку", "06_барахолка"}
        if any(name in plan for name in weak_full) and limit != 0:
            raise SystemExit(f"{row['id']}: слабый план получил {limit}")
    if len(set(counts.values())) != 1:
        raise SystemExit(f"планы не поровну: {counts}")
    if len(rows) > 400:
        raise SystemExit(f"строк {len(rows)}, для MVP нужно не больше 400")
    print("строк", len(rows), "по планам", counts)
    print("лимиты", by_limit)


def prepare() -> None:
    reports = load_jsonl(REPORTS)
    if len(reports) != 7:
        raise SystemExit(f"в encoder_reports {len(reports)} строк, нужны 7")
    rows = build_tasks(reports)
    labels = []
    for row in rows:
        limit, reason = decide(row)
        labels.append({"id": row["id"], "limit_rub": limit, "reason": reason})
    by_id = {item["id"]: item for item in labels}
    check_policy(rows, by_id)
    dump_jsonl(TASKS, rows)
    dump_jsonl(LABELS, labels)
    print(TASKS)
    print(LABELS)
    print("--- демо, рейтинг 500, свои 100000 ---")
    for row in rows:
        if row["credit_rating"] == 500 and row["own_funds_rub"] == 100_000:
            label = by_id[row["id"]]
            plan = Path(row["encoder"]["plan_file"]).stem
            print(
                plan,
                row["loan_amount_rub"],
                "поток",
                row["encoder"]["inferred_monthly_flow_rub"],
                "платёж",
                row["monthly_payment_rub"],
                "лимит",
                label["limit_rub"],
            )


class LimitMLP(nn.Module):
    def __init__(self, n_in: int, hidden: int = HIDDEN, n_out: int = 4) -> None:
        super().__init__()
        self.hidden = nn.Linear(n_in, hidden)
        self.out = nn.Linear(hidden, n_out)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.out(torch.relu(self.hidden(x)))


def featurize(row: dict) -> np.ndarray:
    report = row["encoder"]
    own = row["own_funds_rub"]
    risk_set = set(report["risks"])
    unknown = risk_set - set(RISKS)
    if unknown:
        raise SystemExit(f"неизвестные риски: {unknown}")
    values = [
        float(report["inferred_monthly_flow_rub"]) / MONEY_SCALE,
        float(row["credit_rating"]) / RATING_SCALE,
        0.0 if own is None else float(own) / MONEY_SCALE,
        float(row["loan_amount_rub"]) / MONEY_SCALE,
        float(row["loan_term_months"]),
        float(bool(row["income_confirmed"])),
        float(bool(row["costs_confirmed"])),
        float(bool(row["capital_confirmed"])),
        float(row["monthly_payment_rub"]) / MONEY_SCALE,
    ]
    values.extend(1.0 if name in risk_set else 0.0 for name in RISKS)
    return np.array(values, dtype=np.float32)


def limit_to_class(limit: int) -> int:
    return LIMITS.index(limit)


def class_to_limit(index: int) -> int:
    return LIMITS[int(index)]


def load_xy() -> tuple[list[dict], np.ndarray, np.ndarray]:
    rows = load_jsonl(TASKS)
    labels = {item["id"]: item["limit_rub"] for item in load_jsonl(LABELS)}
    if len(rows) != len(labels):
        raise SystemExit("задачи и метки разъехались")
    x = np.stack([featurize(row) for row in rows])
    y = np.array([limit_to_class(labels[row["id"]]) for row in rows], dtype=np.int64)
    return rows, x, y


def split_indices(n: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    rng = np.random.default_rng(SEED)
    order = rng.permutation(n)
    hold_n = int(round(n * HOLDOUT))
    hold_idx = order[:hold_n]
    rest = order[hold_n:]
    val_n = int(round(len(rest) * 0.15))
    val_idx = rest[:val_n]
    train_idx = rest[val_n:]
    return train_idx, val_idx, hold_idx


def train_model(
    x: np.ndarray,
    y: np.ndarray,
    train_idx: np.ndarray,
    val_idx: np.ndarray,
    model: LimitMLP | None = None,
    epochs: int = 600,
    lr: float = 3e-3,
    monitor_idx: np.ndarray | None = None,
) -> LimitMLP:
    torch.manual_seed(SEED)
    if model is None:
        model = LimitMLP(x.shape[1])
    watch = val_idx if monitor_idx is None else monitor_idx
    opt = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=0.0)
    loss_fn = nn.CrossEntropyLoss()
    x_train = torch.from_numpy(x[train_idx])
    y_train = torch.from_numpy(y[train_idx])
    x_watch = torch.from_numpy(x[watch])
    y_watch = torch.from_numpy(y[watch])
    best_state = {key: value.detach().clone() for key, value in model.state_dict().items()}
    best_key = (-1.0, -1.0)
    wait = 0
    rng = np.random.default_rng(SEED)
    for _epoch in range(epochs):
        model.train()
        order = rng.permutation(len(train_idx))
        for start in range(0, len(order), 32):
            batch = order[start : start + 32]
            logits = model(x_train[batch])
            loss = loss_fn(logits, y_train[batch])
            opt.zero_grad()
            loss.backward()
            opt.step()
        model.eval()
        with torch.no_grad():
            watch_acc = float((model(x_watch).argmax(dim=-1) == y_watch).float().mean()) if len(watch) else 1.0
            train_acc = float((model(x_train).argmax(dim=-1) == y_train).float().mean())
        key = (watch_acc, train_acc)
        if key > best_key:
            best_key = key
            best_state = {key: value.detach().clone() for key, value in model.state_dict().items()}
            wait = 0
            if watch_acc >= 1.0 - 1e-8 and train_acc >= 1.0 - 1e-8:
                break
        else:
            wait += 1
            if wait >= 50:
                break
    model.load_state_dict(best_state)
    return model


def predict_limits(model: LimitMLP, x: np.ndarray) -> np.ndarray:
    model.eval()
    with torch.no_grad():
        pred = model(torch.from_numpy(x)).argmax(dim=-1).numpy()
    return np.array([class_to_limit(int(index)) for index in pred], dtype=np.int64)


def accuracy(y_limit: np.ndarray, pred: np.ndarray) -> float:
    return float(np.mean(y_limit == pred)) if len(y_limit) else 1.0


def feature_spec() -> list[dict]:
    features = [
        {"index": 0, "name": "inferred_monthly_flow_rub", "transform": "делить на money_scale_rub"},
        {"index": 1, "name": "credit_rating", "transform": "делить на rating_scale"},
        {"index": 2, "name": "own_funds_rub", "transform": "null → 0, делить на money_scale_rub"},
        {"index": 3, "name": "loan_amount_rub", "transform": "делить на money_scale_rub"},
        {"index": 4, "name": "loan_term_months", "transform": "как есть, в месяцах"},
        {"index": 5, "name": "income_confirmed", "transform": "0/1"},
        {"index": 6, "name": "costs_confirmed", "transform": "0/1"},
        {"index": 7, "name": "capital_confirmed", "transform": "0/1"},
        {"index": 8, "name": "monthly_payment_rub", "transform": "аннуитет, делить на money_scale_rub"},
    ]
    for offset, name in enumerate(RISKS):
        features.append({"index": 9 + offset, "name": f"risk_{name}", "transform": "0/1"})
    return features


def write_config(extra: dict) -> None:
    payload = {
        "architecture": "mlp",
        "hidden_layers": 1,
        "hidden_size": HIDDEN,
        "hidden_activation": "relu",
        "output": "4 logits, класс с максимальным логитом",
        "classes_rub": list(LIMITS),
        "loss": "cross_entropy",
        "optimizer": "adamw",
        "annual_rate": float(RATE),
        "payment": "аннуитет от loan_amount_rub и loan_term_months, ставка annual_rate",
        "money_scale_rub": MONEY_SCALE,
        "rating_scale": RATING_SCALE,
        "features": feature_spec(),
        "target": "limit_rub",
        "seed": SEED,
        "holdout_fraction": HOLDOUT,
        "weights_file": "weights.pt",
        "torch": torch.__version__,
    }
    payload.update(extra)
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    (MODEL_DIR / "config.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def save_weights(model: LimitMLP) -> None:
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    target = MODEL_DIR / "weights.pt"
    if target.resolve() == OLD_WEIGHTS.resolve():
        raise SystemExit("отказ писать старые веса скорера")
    torch.save(model.state_dict(), target)


def load_model(n_in: int) -> LimitMLP:
    model = LimitMLP(n_in)
    model.load_state_dict(torch.load(MODEL_DIR / "weights.pt", weights_only=True))
    model.eval()
    return model


def format_case(row: dict, pred: int, agent: int) -> str:
    report = row["encoder"]
    return (
        f"{row['id']}  поток={report['inferred_monthly_flow_rub']}  "
        f"рейтинг={row['credit_rating']}  свои={row['own_funds_rub']}  "
        f"сумма={row['loan_amount_rub']}  срок={row['loan_term_months']}  "
        f"флаги={int(row['income_confirmed'])}{int(row['costs_confirmed'])}{int(row['capital_confirmed'])}  "
        f"платёж={row['monthly_payment_rub']}  риски={','.join(report['risks'])}  "
        f"скорер={pred}  агент={agent}"
    )


def train_initial() -> None:
    rows, x, y = load_xy()
    train_idx, val_idx, hold_idx = split_indices(len(rows))
    print(f"train {len(train_idx)} val {len(val_idx)} hold {len(hold_idx)}")
    print("классы в обучении", np.bincount(y[train_idx], minlength=4).tolist())
    model = train_model(x, y, train_idx, val_idx)
    agent = np.array([LIMITS[int(item)] for item in y])
    pred = predict_limits(model, x)
    print(
        "train acc",
        round(accuracy(agent[train_idx], pred[train_idx]), 4),
        "hold acc",
        round(accuracy(agent[hold_idx], pred[hold_idx]), 4),
    )
    save_weights(model)
    labels = {item["id"]: item for item in load_jsonl(LABELS)}
    misses = []
    print("--- отложенные ---")
    for index in hold_idx:
        row = rows[int(index)]
        scorer_limit = int(pred[int(index)])
        agent_limit = labels[row["id"]]["limit_rub"]
        print(format_case(row, scorer_limit, agent_limit))
        if scorer_limit != agent_limit:
            misses.append(
                {
                    "id": row["id"],
                    "scorer_limit_rub": scorer_limit,
                    "agent_limit_rub": agent_limit,
                    "reason": labels[row["id"]]["reason"],
                }
            )
    dump_jsonl(MISSES, misses)
    print(f"косяков {len(misses)}")
    write_config(
        {
            "stage": "initial",
            "holdout_size": int(len(hold_idx)),
            "holdout_accuracy_before_finetune": round(accuracy(agent[hold_idx], pred[hold_idx]), 4),
            "train_accuracy_before_finetune": round(accuracy(agent[train_idx], pred[train_idx]), 4),
            "misses_before_finetune": len(misses),
        }
    )


def finetune_once() -> None:
    rows, x, y = load_xy()
    misses = load_jsonl(MISSES) if MISSES.exists() else []
    by_id = {row["id"]: index for index, row in enumerate(rows)}
    extra = []
    for miss in misses:
        index = by_id.get(miss["id"])
        if index is None:
            raise SystemExit(f"косяк {miss['id']} не найден в задачах")
        if miss["agent_limit_rub"] != LIMITS[int(y[index])]:
            raise SystemExit(f"{miss['id']}: в косяке не метка разметчика")
        extra.append(index)
    train_idx = np.array(list(range(len(rows))) + extra, dtype=np.int64)
    monitor_idx = np.arange(len(rows))
    model = load_model(x.shape[1])
    model = train_model(
        x,
        y,
        train_idx,
        monitor_idx,
        model=model,
        epochs=300,
        lr=1e-3,
        monitor_idx=monitor_idx,
    )
    pred = predict_limits(model, x)
    agent = np.array([LIMITS[int(item)] for item in y])
    print("full acc", round(accuracy(agent, pred), 4), "доучивание на", len(train_idx), "строках")
    save_weights(model)


def demo_rows(rows: list[dict]) -> list[dict]:
    picked = [
        row
        for row in rows
        if row["credit_rating"] == 500 and row["own_funds_rub"] == 100_000
    ]
    if len(picked) != 21:
        raise SystemExit(f"демо-заявок {len(picked)}, нужно 21")
    return picked


def evaluate_demos(append_misses: bool) -> int:
    rows, x, _y = load_xy()
    model = load_model(x.shape[1])
    labels = {item["id"]: item for item in load_jsonl(LABELS)}
    pred = predict_limits(model, x)
    by_id = {row["id"]: index for index, row in enumerate(rows)}
    fresh = []
    print("--- демо ---")
    for row in demo_rows(rows):
        index = by_id[row["id"]]
        scorer_limit = int(pred[index])
        agent_limit = labels[row["id"]]["limit_rub"]
        print(format_case(row, scorer_limit, agent_limit))
        if scorer_limit != agent_limit:
            fresh.append(
                {
                    "id": row["id"],
                    "scorer_limit_rub": scorer_limit,
                    "agent_limit_rub": agent_limit,
                    "reason": labels[row["id"]]["reason"],
                }
            )
    print(f"расхождений на демо {len(fresh)}")
    if append_misses and fresh:
        existing = load_jsonl(MISSES) if MISSES.exists() else []
        dump_jsonl(MISSES, existing + fresh)
    return len(fresh)


def main() -> None:
    phase = sys.argv[1] if len(sys.argv) > 1 else "prepare"
    if phase == "prepare":
        prepare()
        return
    if phase == "train":
        train_initial()
        return
    if phase == "finetune":
        finetune_once()
        return
    if phase == "demos":
        append = "--append-misses" in sys.argv
        evaluate_demos(append)
        return
    raise SystemExit(f"неизвестная фаза {phase}")


if __name__ == "__main__":
    main()
