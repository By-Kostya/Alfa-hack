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
# Ступени лимита. Этот кортеж читает формула фолбека в serve_demo.
# 350000 — сумма запроса, не ступень, в AMOUNTS её нет.
AMOUNTS = (300_000, 800_000, 2_000_000)
REQUEST_AMOUNTS = (300_000, 350_000, 800_000, 2_000_000)
RATINGS = (50, 280, 500, 750, 930, 999)
OWN_FUNDS = (None, 100_000, 150_000, 700_000)
TERMS = (12, 18, 24, 30, 36, 42, 48, 54, 60)
LIMITS = (0, 300_000, 800_000, 2_000_000)
IT_PLAN = "plans/long/02_it_разработка.docx"
SYNTH_PLAN = "synthetic"
SYNTH_QUOTE = "синтетическая строка"
SYNTH_FLOWS = (-150_000, -15_000, 20_000, 45_000, 90_000, 160_000, 400_000, 1_000_000)
SYNTH_RISK_LISTS = (
    ("empty", []),
    ("thin_margin", ["thin_margin"]),
    ("seasonality_fixed_costs", ["seasonality", "fixed_costs"]),
    ("negative_unit_economics", ["negative_unit_economics"]),
)
DEMO_LIMITS = {
    "01_кафе": {300_000: 300_000, 800_000: 300_000, 2_000_000: 300_000},
    "02_it_разработка": {300_000: 300_000, 800_000: 800_000, 2_000_000: 2_000_000},
    "03_автомойка": {300_000: 300_000, 800_000: 300_000, 2_000_000: 300_000},
    "04_доставка": {300_000: 0, 800_000: 0, 2_000_000: 0},
    "05_найди_собаку": {300_000: 0, 800_000: 0, 2_000_000: 0},
    "06_барахолка": {300_000: 0, 800_000: 0, 2_000_000: 0},
    "07_одежда_китай": {300_000: 300_000, 800_000: 300_000, 2_000_000: 300_000},
}

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


def largest_step(amount: int) -> int:
    fitted = [tier for tier in AMOUNTS if tier <= amount]
    return fitted[-1] if fitted else 0


def coverage_cap(flow: int, amount: int, term: int) -> int:
    cap = 0
    for tier in AMOUNTS:
        if tier <= amount and flow >= annuity(tier, term):
            cap = tier
    return cap


def task_id(
    plan_file: str,
    amount: int,
    rating: int,
    own: int | None,
    term: int,
    flow: int | None = None,
    risk_key: str | None = None,
) -> str:
    stem = Path(plan_file).stem[:2]
    own_part = "null" if own is None else str(own)
    base = f"limit-{stem}-a{amount}-r{rating}-own-{own_part}-t{term}"
    if flow is not None:
        base += f"-flow{flow}-risk-{risk_key}"
    return base


def is_it(plan_file: str, flow: int, risks: set[str]) -> bool:
    return (
        plan_file == IT_PLAN
        and flow >= 150_000
        and "lumpy_revenue" in risks
        and "client_concentration" in risks
    )


def payment_relation(flow: int, payment: int) -> str:
    if flow >= payment:
        return f"поток закрывает платёж {rub(payment)}, запас {rub(flow - payment)}"
    return f"платёж {rub(payment)} выше потока на {rub(payment - flow)}"


def decide(row: dict) -> tuple[int, str]:
    """Лимит разметчика. Скорер к этому моменту ещё ничего не предсказывал.

    Сравнение — поток против аннуитета на срок этой строки. Выше запрошенной
    суммы лимит не ставится. Ноль — отказ. 350000 не ступень и не возвращается.
    Исключение IT только для plans/long/02_it_разработка.docx.
    """
    report = row["encoder"]
    flow = int(report["inferred_monthly_flow_rub"])
    risks = list(report["risks"])
    risk_set = set(risks)
    amount = int(row["loan_amount_rub"])
    term = int(row["loan_term_months"])
    payment = int(row["monthly_payment_rub"])
    rating = int(row["credit_rating"])
    own = row["own_funds_rub"]
    named = risks_text(risks) if risks else "нет"
    pay_300 = annuity(300_000, term)
    pay_800 = annuity(800_000, term)
    pay_2000 = annuity(2_000_000, term)

    if flow <= 0:
        return (
            0,
            f"Поток {rub(flow)} руб. в месяц, платёж по запросу {rub(amount)} на {term} мес. равен {rub(payment)} руб. "
            f"Гасить нечем: дело каждый месяц в минусе. Риски: {named}. "
            f"Полный запрос не даю и меньший лимит тоже не даю — отрицательный поток не обслуживает ни одну сумму. Отказ.",
        )

    if is_it(report["plan_file"], flow, risk_set):
        if rating >= 280:
            if amount in AMOUNTS:
                if amount == 2_000_000:
                    return (
                        2_000_000,
                        f"Поток {rub(flow)} руб., аннуитет на 2 000 000 при сроке {term} мес. равен {rub(payment)} руб., "
                        f"{payment_relation(flow, payment)}. Это не слабый поток. "
                        f"Рейтинг {rating} не обвальный, поэтому до 800 000 не срезаю. "
                        f"{own_text(own).capitalize()}. Риски: {named}. Лимит 2 000 000.",
                    )
                return (
                    amount,
                    f"Поток {rub(flow)} руб. против платежа {rub(payment)} руб. на {term} мес., "
                    f"{payment_relation(flow, payment)}. "
                    f"Рейтинг {rating} не обвальный, риски ({named}) этот запас не съедают. "
                    f"{own_text(own).capitalize()}. Лимит равен запросу {rub(amount)}.",
                )
            return (
                300_000,
                f"Запрос {rub(amount)} ступенью не является. Наибольшая ступень не выше запроса — 300 000, "
                f"её платёж на {term} мес. равен {rub(pay_300)}. Поток {rub(flow)} руб., {payment_relation(flow, pay_300)}. "
                f"Рейтинг {rating}. {own_text(own).capitalize()}. Риски: {named}. Лимит 300 000.",
            )
        return (
            300_000,
            f"Поток {rub(flow)} руб. На 800 000 при сроке {term} мес. платёж {rub(pay_800)}: {payment_relation(flow, pay_800)}. "
            f"Рейтинг {rating} обвальный, а выручка рваная и сидит на нескольких клиентах. "
            f"На 2 000 000 платёж {rub(pay_2000)}: {payment_relation(flow, pay_2000)}. "
            f"Оставляю 300 000: платёж {rub(pay_300)} поток держит с большим запасом. Выше не иду.",
        )

    cap = coverage_cap(flow, amount, term)
    tight = flow < pay_800

    if cap == 0:
        return (
            0,
            f"Поток {rub(flow)} руб. ниже даже платежа {rub(pay_300)} на 300 000 при сроке {term} мес. Риски: {named}. Отказ.",
        )

    if own is None:
        return (
            0,
            f"Поток {rub(flow)} руб., платёж на запрошенные {rub(amount)} при сроке {term} мес. равен {rub(payment)} руб. "
            f"Свои деньги не указаны, доход и капитал не подтверждены, опереться не на что. Риски: {named}. Отказ.",
        )

    if rating <= 50:
        if (not tight) and own >= 700_000:
            return (
                300_000,
                f"Поток {rub(flow)} руб. покрывает платёж {rub(pay_800)} на 800 000 при сроке {term} мес., но рейтинг {rating} обвальный. "
                f"Свои {rub(own)} руб. и запас потока позволяют только малый лимит: платёж {rub(pay_300)}. "
                f"На 2 000 000 платёж {rub(pay_2000)}: {payment_relation(flow, pay_2000)}. Риски: {named}. Лимит 300 000.",
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
                f"Свои {rub(own)} руб. тянут малый платёж {rub(pay_300)} на {term} мес., но не больший лимит. "
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
            f"Поток {rub(flow)} руб. покрывает только платёж {rub(pay_300)} на {term} мес. и не покрывает {rub(pay_800)} и {rub(pay_2000)}. "
            f"Слабый поток на 2 000 000 не получает 2 000 000 и не получает 800 000. "
            f"{own_text(own).capitalize()}, рейтинг {rating}. Риски: {named}. Лимит 300 000.",
        )

    if own >= 700_000:
        limit = cap
        if amount >= 2_000_000 and limit < amount:
            return (
                limit,
                f"Поток {rub(flow)} руб. покрывает платёж {rub(pay_800)} на 800 000 при сроке {term} мес. "
                f"(запас {rub(flow - pay_800)}) и не покрывает платёж {rub(pay_2000)} на 2 000 000. "
                f"Для двух миллионов поток слабый. Свои {rub(own)} руб. и рейтинг {rating} подтверждают 800 000, не выше. "
                f"Риски: {named}. Лимит {rub(limit)}.",
            )
        return (
            limit,
            f"Поток {rub(flow)} руб. против платежа {rub(payment)} на {term} мес., {payment_relation(flow, payment)}. "
            f"Свои {rub(own)} руб. закрывают просадку по рискам ({named}), рейтинг {rating}. "
            f"Лимит {rub(limit)}.",
        )

    limit = min(cap, 300_000)
    if limit == amount:
        return (
            limit,
            f"Поток {rub(flow)} руб. закрывает платёж {rub(payment)} по запросу {rub(amount)} на {term} мес. "
            f"Свои деньги только {rub(own)} руб., для большего лимита этой подушки мало. Риски: {named}. Рейтинг {rating}. "
            f"Платёж на 800 000 равен {rub(pay_800)}: {payment_relation(flow, pay_800)}. "
            f"На 2 000 000 платёж {rub(pay_2000)}: {payment_relation(flow, pay_2000)}. "
            f"Лимит {rub(limit)}.",
        )
    return (
        limit,
        f"Средний поток {rub(flow)} руб. при сроке {term} мес. {payment_relation(flow, pay_800)} на 800 000, "
        f"но свои деньги только {rub(own)} руб. и не держат просадку. Риски: {named}. Рейтинг {rating}. "
        f"На 2 000 000 платёж {rub(pay_2000)}: {payment_relation(flow, pay_2000)}. "
        f"Свои ниже 700 000, выше 300 000 не поднимаю. Платёж {rub(pay_300)} поток закрывает. Лимит 300 000.",
    )


def make_task(
    plan_file: str,
    flow: int,
    flow_basis: str,
    risks: list[str],
    quote: str,
    amount: int,
    rating: int,
    own: int | None,
    term: int,
    risk_key: str | None = None,
) -> dict:
    confirmed = own is not None
    return {
        "id": task_id(plan_file, amount, rating, own, term, None if risk_key is None else flow, risk_key),
        "own_funds_rub": own,
        "income_confirmed": confirmed,
        "costs_confirmed": False,
        "capital_confirmed": confirmed,
        "loan_amount_rub": amount,
        "loan_term_months": term,
        "credit_rating": rating,
        "encoder": {
            "plan_file": plan_file,
            "inferred_monthly_flow_rub": flow,
            "flow_basis": flow_basis,
            "risks": list(risks),
            "quote": quote,
        },
        "monthly_payment_rub": annuity(amount, term),
    }


def build_tasks(reports: list[dict]) -> list[dict]:
    rows = []
    for report in reports:
        quote = report["quote"]
        if not quote:
            continue
        for amount in REQUEST_AMOUNTS:
            for rating in RATINGS:
                for own in OWN_FUNDS:
                    for term in TERMS:
                        rows.append(
                            make_task(
                                report["plan_file"],
                                int(report["inferred_monthly_flow_rub"]),
                                report["flow_basis"],
                                list(report["risks"]),
                                quote,
                                amount,
                                rating,
                                own,
                                term,
                            )
                        )
    for flow in SYNTH_FLOWS:
        for risk_key, risks in SYNTH_RISK_LISTS:
            for amount in REQUEST_AMOUNTS:
                for rating in RATINGS:
                    for own in OWN_FUNDS:
                        for term in TERMS:
                            rows.append(
                                make_task(
                                    SYNTH_PLAN,
                                    flow,
                                    SYNTH_PLAN,
                                    risks,
                                    SYNTH_QUOTE,
                                    amount,
                                    rating,
                                    own,
                                    term,
                                    risk_key,
                                )
                            )
    return rows


def check_policy(rows: list[dict], labels: dict[str, dict]) -> None:
    counts: dict[str, int] = {}
    by_limit: dict[int, int] = {value: 0 for value in LIMITS}
    seen: set[str] = set()
    for row in rows:
        if row["id"] in seen:
            raise SystemExit(f"повтор id {row['id']}")
        seen.add(row["id"])
        plan = row["encoder"]["plan_file"]
        counts[plan] = counts.get(plan, 0) + 1
        limit = labels[row["id"]]["limit_rub"]
        amount = int(row["loan_amount_rub"])
        term = int(row["loan_term_months"])
        flow = int(row["encoder"]["inferred_monthly_flow_rub"])
        own = row["own_funds_rub"]
        rating = int(row["credit_rating"])
        risks = set(row["encoder"]["risks"])
        if row["monthly_payment_rub"] != annuity(amount, term):
            raise SystemExit(f"{row['id']}: платёж не аннуитет на срок строки")
        if limit not in LIMITS:
            raise SystemExit(f"{row['id']}: лимит {limit} вне шкалы")
        if limit > amount:
            raise SystemExit(f"{row['id']}: лимит выше запроса")
        if flow <= 0 and limit != 0:
            raise SystemExit(f"{row['id']}: отрицательный поток получил {limit}")
        it = is_it(plan, flow, risks)
        if it and rating >= 280:
            expected = amount if amount in AMOUNTS else largest_step(amount)
            if limit != expected:
                raise SystemExit(f"{row['id']}: IT лимит {limit}, ожидался {expected}")
        if it and rating < 280 and limit != 300_000:
            raise SystemExit(f"{row['id']}: IT при рейтинге {rating} получил {limit}")
        if (not it) and own is None and limit != 0:
            raise SystemExit(f"{row['id']}: свои не указаны, лимит {limit}")
        if (not it) and own is not None and own < 700_000 and limit > 300_000:
            raise SystemExit(f"{row['id']}: свои {own} подняли лимит до {limit}")
        if (not it) and limit == 2_000_000 and flow < annuity(2_000_000, term):
            raise SystemExit(f"{row['id']}: поток {flow} не закрывает платёж на 2 000 000 при сроке {term}")
        weak_full = {"04_доставка", "05_найди_собаку", "06_барахолка"}
        if any(name in plan for name in weak_full) and limit != 0:
            raise SystemExit(f"{row['id']}: слабый план получил {limit}")
        by_limit[limit] += 1
    real = {plan: count for plan, count in counts.items() if plan != SYNTH_PLAN}
    if len(real) != 7 or len(set(real.values())) != 1:
        raise SystemExit(f"реальные планы не поровну: {real}")
    if SYNTH_PLAN not in counts:
        raise SystemExit("нет синтетики")
    print("строк", len(rows), "по планам", counts)
    print("лимиты", by_limit)


def spot_label(plan: str, flow: int, risks: list[str], amount: int, term: int, rating: int, own: int | None) -> int:
    row = make_task(plan, flow, "explicit", risks, "проверка", amount, rating, own, term)
    limit, _reason = decide(row)
    return limit


def check_spots() -> None:
    it_risks = ["client_concentration", "lumpy_revenue"]
    cafe = "plans/long/01_кафе.docx"
    pay24 = annuity(800_000, 24)
    cafe24 = spot_label(cafe, 45_000, ["thin_margin", "rent", "slow_ramp"], 800_000, 24, 500, 700_000)
    if pay24 > 45_000:
        raise SystemExit(
            f"аннуитет 800000 на 24 мес. равен {pay24}, это выше потока 45000. "
            f"Метка decide {cafe24}. Ожидаемую 800000 не подменяю."
        )
    checks = [
        (spot_label(cafe, 45_000, ["thin_margin", "rent", "slow_ramp"], 800_000, 12, 500, 700_000), 300_000, "кафе 12 мес."),
        (cafe24, 800_000, "кафе 24 мес."),
        (spot_label(SYNTH_PLAN, 1_000_000, it_risks, 350_000, 60, 999, 150_000), 300_000, "прогон 350000"),
        (spot_label(SYNTH_PLAN, 160_000, it_risks, 2_000_000, 12, 500, 700_000), 800_000, "синтетика поток 160000"),
        (spot_label(SYNTH_PLAN, 1_000_000, it_risks, 2_000_000, 12, 999, 150_000), 300_000, "синтетика поток 1000000"),
        (spot_label(cafe, 160_000, it_risks, 2_000_000, 12, 500, 700_000), 800_000, "чужой план поток 160000"),
        (spot_label(cafe, 1_000_000, it_risks, 2_000_000, 12, 999, 150_000), 300_000, "чужой план поток 1000000"),
        (spot_label(IT_PLAN, 160_000, it_risks, 350_000, 12, 500, 100_000), 300_000, "IT запрос 350000"),
        (spot_label(IT_PLAN, 160_000, it_risks, 2_000_000, 12, 280, 100_000), 2_000_000, "IT запрос 2000000"),
        (spot_label(SYNTH_PLAN, -150_000, [], 300_000, 60, 999, 700_000), 0, "отрицательный поток"),
        (spot_label(SYNTH_PLAN, 400_000, [], 800_000, 12, 999, None), 0, "свои не указаны"),
    ]
    failed = [f"{name}: метка {got}, ожидалось {expected}" for got, expected, name in checks if got != expected]
    if failed:
        raise SystemExit("точечные проверки:\n" + "\n".join(failed))


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
    if len(by_id) != len(labels):
        raise SystemExit("id меток пересекаются")
    check_policy(rows, by_id)
    check_spots()
    vector = featurize(rows[0])
    if vector.shape != (30,):
        raise SystemExit(f"входов {vector.shape[0]}, нужно 30")
    if abs(float(vector[4]) - rows[0]["loan_term_months"] / 12.0) > 1e-6:
        raise SystemExit("срок в сети не делится на 12")
    print("--- демо, семь планов, рейтинг 500, свои 100000, срок 12 ---")
    mismatches = []
    for row in demo_rows(rows):
        label = by_id[row["id"]]
        plan = Path(row["encoder"]["plan_file"]).stem
        expected = DEMO_LIMITS[plan][row["loan_amount_rub"]]
        got = label["limit_rub"]
        print(
            plan,
            row["loan_amount_rub"],
            "поток",
            row["encoder"]["inferred_monthly_flow_rub"],
            "платёж",
            row["monthly_payment_rub"],
            "лимит",
            got,
        )
        if got != expected:
            mismatches.append(f"{plan} сумма {row['loan_amount_rub']}: метка {got}, таблица {expected}")
    if mismatches:
        raise SystemExit("демо не сошлось:\n" + "\n".join(mismatches))
    dump_jsonl(TASKS, rows)
    dump_jsonl(LABELS, labels)
    print(TASKS)
    print(LABELS)


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
        float(row["loan_term_months"]) / 12.0,
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
        {"index": 4, "name": "loan_term_months", "transform": "делить на 12"},
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
    print("--- отложенные, только расхождения ---")
    for index in hold_idx:
        row = rows[int(index)]
        scorer_limit = int(pred[int(index)])
        agent_limit = labels[row["id"]]["limit_rub"]
        if scorer_limit != agent_limit:
            print(format_case(row, scorer_limit, agent_limit))
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
    plans = {f"plans/long/{stem}.docx" for stem in DEMO_LIMITS}
    picked = [
        row
        for row in rows
        if row["encoder"]["plan_file"] in plans
        and row["credit_rating"] == 500
        and row["own_funds_rub"] == 100_000
        and row["loan_term_months"] == 12
        and row["loan_amount_rub"] in AMOUNTS
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
