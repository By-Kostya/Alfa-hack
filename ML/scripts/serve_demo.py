#!/usr/bin/env python3
"""Ручной прогон: свой текст, аннуитет, энкодер и скорер лимита.

Qwen и MLP читаются один раз при старте. Веса не пишутся, дообучения нет.
Если энкодер или скорер обрываются, лимит досчитывает формула, а журнал
показывает, на каком шаге это случилось.
"""

from __future__ import annotations

import json
import re
import sys
import traceback
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tmp"))
sys.path.insert(0, str(ROOT / "scripts"))

import run_encoder_reports as encoder_run
from train_scorer_limit import (
    AMOUNTS,
    LIMITS,
    MONEY_SCALE,
    RATING_SCALE,
    RISKS,
    LimitMLP,
    annuity,
    class_to_limit,
    feature_spec,
    featurize,
    load_model,
    rub,
)

HOST = "127.0.0.1"
PORT = 8765
INDEX = ROOT / "demo" / "index.html"

ENCODER = None
TOKENIZER = None
GENERATE = None
SCORER: LimitMLP | None = None

# Подписи как на экране кабинета. Коды и порядок входов сети не меняются.
RISK_FACE = {
    "thin_margin": "тонкая маржа",
    "rent": "аренда",
    "slow_ramp": "медленный выход на поток",
    "client_concentration": "зависимость от одного клиента",
    "lumpy_revenue": "рваная выручка",
    "seasonality": "сезонность",
    "fixed_costs": "постоянные расходы",
    "location": "место",
    "negative_unit_economics": "отрицательная юнит-экономика",
    "subsidies": "зависимость от субсидий",
    "competition": "конкуренция",
    "rare_payment": "редкие платежи",
    "unclear_payer": "неясный плательщик",
    "small_market": "узкий рынок",
    "cold_start": "холодный старт",
    "fraud": "риск мошенничества",
    "late_monetization": "поздняя монетизация",
    "inventory": "склад",
    "customs": "таможня",
    "returns": "возвраты",
    "fx": "валюта",
}

BASIS_FACE = {
    "explicit": "цифра потока прямо написана в тексте",
    "inferred": "поток прикинут по покупателям, чеку и затратам",
    "unknown": "из текста поток не следует",
    "form": "поток взят из анкеты, не из текста",
}

FEATURE_FACE = {
    "inferred_monthly_flow_rub": "поток, ₽",
    "credit_rating": "рейтинг",
    "own_funds_rub": "свои деньги, ₽",
    "loan_amount_rub": "сумма запроса, ₽",
    "loan_term_months": "срок, месяцы",
    "income_confirmed": "доход подтверждён",
    "costs_confirmed": "расходы подтверждены",
    "capital_confirmed": "капитал подтверждён",
    "monthly_payment_rub": "платёж по запросу, ₽",
}


class PipelineError(Exception):
    """Тело запроса не разобрать."""


def money(value: int | None) -> str:
    if value is None:
        return "нет"
    return rub(value) + " ₽"


def risk_phrase(risks: list[str]) -> str:
    names = [RISK_FACE.get(name, name) for name in risks]
    return ", ".join(names)


def step(title: str, status: str, detail: str, rows: list[dict] | None = None, pre: str | None = None) -> dict:
    item = {"title": title, "status": status, "detail": detail}
    if rows:
        item["rows"] = rows
    if pre:
        item["pre"] = pre
    return item


def send_bytes(handler: BaseHTTPRequestHandler, status: int, body: bytes, content_type: str) -> None:
    handler.send_response(status)
    handler.send_header("Content-Type", content_type)
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()
    handler.wfile.write(body)


def send_json(handler: BaseHTTPRequestHandler, status: int, payload: dict) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    send_bytes(handler, status, body, "application/json; charset=utf-8")


def read_json(handler: BaseHTTPRequestHandler) -> dict:
    length = int(handler.headers.get("Content-Length", "0") or 0)
    if length <= 0 or length > 2_000_000:
        raise PipelineError("Пустой запрос.")
    raw = handler.rfile.read(length)
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise PipelineError("Запрос не JSON.") from exc
    if not isinstance(payload, dict):
        raise PipelineError("Запрос не JSON.")
    return payload


def whole_number(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PipelineError(label)
    if isinstance(value, float) and not value.is_integer():
        raise PipelineError(label)
    return int(value)


def parse_digits(value: object, label: str, empty: int | None) -> int | None:
    if value is None:
        return empty
    if isinstance(value, str):
        cleaned = value.strip().replace(" ", "").replace("\u00a0", "").replace("\u202f", "").replace("₽", "")
        if cleaned == "":
            return empty
        if not re.fullmatch(r"\d+", cleaned):
            raise PipelineError(label)
        return int(cleaned)
    return whole_number(value, label)


def form_fields(payload: dict) -> dict:
    text = payload.get("plan_text")
    if not isinstance(text, str) or not text.strip():
        raise PipelineError("Напишите, чем занимается бизнес. Без текста считать нечего.")
    text = text.strip()
    if len(text) > 100_000:
        raise PipelineError("Текст слишком длинный.")
    amount = parse_digits(payload.get("loan_amount_rub"), "Сумма — целое число рублей, например 800 000.", None)
    if amount is None or amount < 1 or amount > 100_000_000_000:
        raise PipelineError("Сумма — целое число рублей больше нуля, например 800 000.")
    term = parse_digits(payload.get("loan_term_months"), "Срок — целое число месяцев от 1 до 360.", None)
    if term is None or term < 1 or term > 360:
        raise PipelineError("Срок — целое число месяцев от 1 до 360.")
    rating = parse_digits(payload.get("credit_rating"), "Рейтинг — целое число от 0 до 1000 или пусто.", None)
    if rating is not None and (rating < 0 or rating > 1000):
        raise PipelineError("Рейтинг — целое число от 0 до 1000 или пусто.")
    own = parse_digits(payload.get("own_funds_rub"), "Свои деньги — целое число рублей или пусто.", None)
    if own is not None and own > 100_000_000_000:
        raise PipelineError("Свои деньги — целое число рублей или пусто.")
    if own is None:
        income = False
        capital = False
    else:
        income = bool(payload.get("income_confirmed"))
        capital = bool(payload.get("capital_confirmed"))
    return {
        "plan_text": text,
        "loan_amount_rub": amount,
        "loan_term_months": term,
        "credit_rating": rating,
        "own_funds_rub": own,
        "income_confirmed": income,
        "capital_confirmed": capital,
    }


def coverage_prompt(text: str, amount: int, term: int) -> str:
    return (
        encoder_run.PROMPT
        + "\n\nplan_text:\n"
        + text
        + f"\n\nloan_amount_rub: {amount}\nloan_term_months: {term}\n"
    )


def as_flow(value: object) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, str):
        cleaned = value.strip().replace(" ", "")
        if not re.fullmatch(r"-?\d+", cleaned):
            return None
        return int(cleaned)
    if isinstance(value, float):
        if not value.is_integer():
            return None
        return int(value)
    if isinstance(value, int):
        return value
    return None


def math_limit(flow: int | None, amount: int, term: int) -> tuple[int | None, list[dict]]:
    if flow is None:
        return None, [{"label": "поток", "value": "нет, ступень не выбирается"}]
    if flow <= 0:
        return 0, [{"label": "поток", "value": money(flow) + ", он не положительный, лимит 0"}]
    chosen = 0
    rows = []
    for tier in AMOUNTS:
        pay = annuity(tier, term)
        reasons = []
        if tier > amount:
            reasons.append("выше запроса")
        if flow < pay:
            reasons.append("платёж " + money(pay) + " выше потока")
        if reasons:
            rows.append({"label": money(tier), "value": "; ".join(reasons)})
        else:
            chosen = tier
            rows.append({"label": money(tier), "value": "платёж " + money(pay) + ", ступень подходит"})
    rows.append({"label": "итог формулы", "value": money(chosen)})
    return chosen, rows


def vector_rows(row: dict, features) -> list[dict]:
    raw = {
        "inferred_monthly_flow_rub": money(row["encoder"]["inferred_monthly_flow_rub"]),
        "credit_rating": "0, в анкете пусто" if row["credit_rating_missing"] else str(row["credit_rating"]),
        "own_funds_rub": "0, в анкете пусто" if row["own_funds_rub"] is None else money(row["own_funds_rub"]),
        "loan_amount_rub": money(row["loan_amount_rub"]),
        "loan_term_months": str(row["loan_term_months"]),
        "income_confirmed": "да" if row["income_confirmed"] else "нет",
        "costs_confirmed": "нет, отдельного поля расходов нет",
        "capital_confirmed": "да" if row["capital_confirmed"] else "нет",
        "monthly_payment_rub": money(row["monthly_payment_rub"]),
    }
    rows = []
    spec = feature_spec()
    values = features.tolist()
    for item, value in zip(spec, values):
        name = item["name"]
        if name.startswith("risk_"):
            code = name.removeprefix("risk_")
            label = "риск: " + RISK_FACE.get(code, code)
            entered = raw_risk(row, code)
        else:
            label = FEATURE_FACE.get(name, name)
            entered = raw.get(name, "")
        rows.append(
            {
                "label": f"{item['index']}. {label}",
                "value": f"в анкете {entered} → в сеть {value:.6g} ({item['transform']})",
            }
        )
    return rows


def raw_risk(row: dict, code: str) -> str:
    return "да" if code in row["encoder"]["risks"] else "нет"


def decision_of(limit: int | None, amount: int, flow_known: bool) -> str:
    if not flow_known or limit is None:
        return "unknown"
    if limit <= 0:
        return "reject"
    if limit == amount:
        return "approve"
    return "reduced"


DECISION_TITLE = {
    "approve": "Одобрено целиком",
    "reduced": "Сумма урезана",
    "reject": "Отказ",
    "unknown": "Лимит не поставлен",
}


def paragraphs(
    decision: str,
    fallback: bool,
    reason: str | None,
    amount: int,
    term: int,
    payment: int,
    limit: int | None,
    approved_payment: int | None,
    flow: int | None,
    basis: str | None,
    risks: list[str],
    quote_ok: bool,
    raw_limit: int | None,
) -> list[str]:
    lines: list[str] = []
    if reason == "form":
        return lines
    if fallback and reason == "json":
        lines.append(
            "Лимит не ставлю. Энкодер вернул не JSON, скорер из-за этого не запускался. "
            "Потока нет, отдельной цифры прибыли в анкете тоже нет, формуле не на что опереться."
        )
        lines.append(f"Запрос был {money(amount)} на {term} мес., платёж по нему был бы {money(payment)} в месяц.")
        return lines
    if fallback and reason == "flow":
        lines.append(
            "Лимит не ставлю. В ответе энкодера нет целого потока в рублях, скорер без этой цифры не запускается."
        )
        lines.append(f"Запрос {money(amount)} на {term} мес., платёж по нему был бы {money(payment)} в месяц.")
        return lines
    if fallback and reason == "quote":
        lines.append("Нейросеть лимита не запускалась: цитата энкодера не найдена в тексте дословно. Дальше считает формула.")
        lines.append(f"Запрос {money(amount)} на {term} мес. Платёж {money(payment)} в месяц.")
    elif fallback and reason == "risks":
        lines.append("Нейросеть лимита не запустилась: в ответе энкодера риск вне допустимого списка. Дальше считает формула.")
        lines.append(f"Запрос {money(amount)} на {term} мес. Платёж {money(payment)} в месяц.")
    elif fallback and reason == "scorer":
        lines.append("Энкодер текст разобрал, но скорер строку не принял. Дальше считает формула.")
        lines.append(f"Запрос {money(amount)} на {term} мес. Платёж {money(payment)} в месяц.")
    else:
        lines.append(f"Запрос {money(amount)} на {term} мес. Платёж {money(payment)} в месяц.")

    if flow is not None:
        basis_text = BASIS_FACE.get(basis or "", "основание потока не подписано")
        sentence = f"По описанию поток {money(flow)} в месяц: {basis_text}."
        if payment is not None:
            gap = flow - payment
            if gap >= 0:
                sentence += f" Это больше платежа по запросу на {money(gap)}."
            else:
                sentence += f" На платёж по запросу не хватает {money(-gap)} в месяц."
        if quote_ok and risks:
            sentence += f" Риски в тексте: {risk_phrase(risks)}."
        elif reason == "quote":
            sentence += " Цифру модель назвала, но дословной цитаты в тексте нет, поэтому на риски из этого ответа не опираюсь."
        lines.append(sentence)
    elif reason == "quote":
        lines.append("Числа потока в ответе нет, формула ступень не выбирает.")

    if not fallback and raw_limit is not None and raw_limit > amount:
        lines.append(
            f"Сеть выбрала класс {money(raw_limit)}. Он выше запроса, поэтому лимит обрезан до {money(limit)}. "
            "Это полное одобрение запрошенной суммы."
        )
    elif not fallback and decision == "approve":
        if flow is not None and flow >= payment:
            lines.append(
                f"Сеть выбрала {money(limit)} — ровно запрошенная сумма. Поток этот платёж закрывает, сумму можно выдать целиком."
            )
        else:
            lines.append(
                f"Сеть выбрала {money(limit)} — ровно запрошенная сумма. Потока на этот платёж не хватает: "
                "одобрение здесь — класс сети, а не проверка «платёж меньше потока»."
            )
    elif not fallback and decision == "reduced":
        tail = f"Сеть выбрала {money(limit)} из запрошенных {money(amount)}."
        if approved_payment is not None and flow is not None and flow >= approved_payment and flow < payment:
            tail += (
                f" Полный платёж поток не тянет, платёж по одобренным {money(limit)} — "
                f"{money(approved_payment)} в месяц — тянет. Сумма урезана."
            )
        elif flow is not None and flow >= payment:
            tail += (
                " Поток закрывает и полный платёж, но сеть всё равно урезала сумму: "
                "на выходе у неё только 0, 300 000, 800 000 и 2 000 000."
            )
        elif approved_payment is not None and flow is not None and flow >= approved_payment:
            tail += f" Платёж по одобренной сумме {money(approved_payment)} поток закрывает. Сумма урезана."
        elif approved_payment is not None:
            tail += (
                f" Поток не закрывает даже платёж {money(approved_payment)} по этой меньшей сумме. "
                f"Сеть всё равно оставила {money(limit)}, а не ноль."
            )
        lines.append(tail)
    elif not fallback and decision == "reject":
        if flow is not None and flow >= payment:
            lines.append(
                "Сеть выбрала 0 ₽. Поток этот платёж закрывает, так что отказ не потому, что платить нечем: "
                "у сети только классы 0, 300 000, 800 000 и 2 000 000, и на этих сумме и сроке она выбрала ноль."
            )
        else:
            lines.append("Сеть выбрала 0 ₽. Поток этот платёж не закрывает, отказ с этим согласуется.")
    elif fallback and limit is not None and reason not in {"json", "flow"}:
        lines.append(
            f"Формула берёт наибольшую ступень 300 000, 800 000 или 2 000 000, которая не выше запроса "
            f"и чей платёж не больше потока. Получилось {money(limit)}."
        )
        if decision == "reduced" and approved_payment is not None:
            lines.append(f"Платёж по этой сумме {money(approved_payment)} в месяц.")
        elif decision == "reject" and flow is not None and flow > 0 and amount < AMOUNTS[0]:
            lines.append("Запрос ниже ступени 300 000 ₽, подходящей ступени нет, поэтому лимит 0 ₽.")
        elif decision == "reject":
            lines.append("Положительного потока, который тянет хотя бы малую ступень, нет. Это отказ.")
        elif decision == "approve":
            lines.append("Ступень совпала с запросом, сумму можно выдать целиком.")
    return lines


def finish(
    decision: str,
    fallback: bool,
    amount: int | None,
    term: int | None,
    payment: int | None,
    limit: int | None,
    flow: int | None,
    quote: str | None,
    steps: list[dict],
    paragraphs_text: list[str],
) -> dict:
    approved = None
    if limit is not None and limit > 0 and term is not None:
        approved = annuity(limit, term)
    figures = []
    if amount is not None:
        figures = [
            {"label": "Поток", "value": money(flow) if flow is not None else "нет"},
            {"label": "Платёж по запросу", "value": money(payment) if payment is not None else "нет"},
            {"label": "Лимит", "value": money(limit) if limit is not None else "нет"},
        ]
        if approved is not None and payment is not None and approved != payment:
            figures.append({"label": "Платёж по лимиту", "value": money(approved)})
    print(
        f"pipeline={'math' if fallback else 'ai'} decision={decision} "
        f"поток={flow} платёж={payment} лимит={limit}",
        flush=True,
    )
    return {
        "decision": decision,
        "decision_title": DECISION_TITLE[decision],
        "pipeline": "math" if fallback else "ai",
        "fallback": fallback,
        "paragraphs": paragraphs_text,
        "quote": quote,
        "limit_rub": limit,
        "monthly_payment_rub": payment,
        "approved_payment_rub": approved,
        "flow_rub": flow,
        "figures": figures,
        "steps": steps,
    }


def encoder_call(text: str, amount: int, term: int) -> str:
    return GENERATE(
        ENCODER,
        TOKENIZER,
        prompt=TOKENIZER.apply_chat_template(
            [{"role": "user", "content": coverage_prompt(text, amount, term)}],
            add_generation_prompt=True,
            tokenize=False,
        ),
        max_tokens=1024,
        verbose=False,
    )


def pipeline(payload: dict) -> dict:
    steps: list[dict] = []
    try:
        fields = form_fields(payload)
    except PipelineError as exc:
        steps.append(step("Анкета", "fail", str(exc)))
        return finish("unknown", False, None, None, None, None, None, None, steps, [str(exc)])

    amount = fields["loan_amount_rub"]
    term = fields["loan_term_months"]
    text = fields["plan_text"]
    rating = fields["credit_rating"]
    own = fields["own_funds_rub"]
    steps.append(
        step(
            "Анкета",
            "ok",
            "Текст, сумма и срок взяты как есть. Рейтинг и свои деньги необязательны: пустое в скорер пойдёт нулём.",
            [
                {"label": "текст", "value": f"{len(text)} символов"},
                {"label": "сумма", "value": money(amount)},
                {"label": "срок", "value": f"{term} мес."},
                {"label": "рейтинг", "value": "не указан" if rating is None else str(rating)},
                {"label": "свои деньги", "value": "не указаны" if own is None else money(own)},
                {"label": "доход подтверждён", "value": "да" if fields["income_confirmed"] else "нет"},
                {"label": "капитал подтверждён", "value": "да" if fields["capital_confirmed"] else "нет"},
            ],
        )
    )
    payment = annuity(amount, term)

    try:
        raw = encoder_call(text, amount, term)
    except Exception as exc:
        steps.append(step("Энкодер", "fail", f"Модель не ответила: {exc}"))
        steps.append(step("Цитата", "skip", "Проверять нечего: ответа энкодера нет."))
        steps.append(payment_step(amount, term, payment))
        steps.append(step("Скорер", "skip", "Не вызывался: энкодер не ответил."))
        formula_limit, formula_rows = math_limit(None, amount, term)
        steps.append(step("Формула", "fallback", "Потока нет, ступень не выбирается.", formula_rows))
        return finish(
            "unknown",
            True,
            amount,
            term,
            payment,
            formula_limit,
            None,
            None,
            steps,
            paragraphs("unknown", True, "json", amount, term, payment, None, None, None, None, [], False, None),
        )

    parsed = encoder_run.parse_coverage(raw)
    if not parsed:
        steps.append(
            step(
                "Энкодер",
                "fail",
                "Ответ не разбирается как JSON. Поля coverage и monthly_payment_rub всё равно не используются.",
                pre=raw,
            )
        )
        steps.append(step("Цитата", "skip", "Проверять нечего: JSON нет."))
        steps.append(payment_step(amount, term, payment))
        steps.append(step("Скорер", "skip", "Не вызывался: энкодер вернул не JSON."))
        formula_limit, formula_rows = math_limit(None, amount, term)
        steps.append(step("Формула", "fallback", "Потока нет, ступень не выбирается.", formula_rows))
        return finish(
            "unknown",
            True,
            amount,
            term,
            payment,
            formula_limit,
            None,
            None,
            steps,
            paragraphs("unknown", True, "json", amount, term, payment, None, None, None, None, [], False, None),
        )

    quote = str(parsed.get("quote") or "")
    flow = as_flow(parsed.get("inferred_monthly_flow_rub"))
    basis = parsed.get("flow_basis")
    basis_text = basis if isinstance(basis, str) else ""
    risks = parsed.get("risks")
    risks_ok = isinstance(risks, list) and all(isinstance(item, str) for item in risks)
    risk_list = list(risks) if risks_ok else []
    unknown = [item for item in risk_list if item not in RISKS]
    steps.append(
        step(
            "Энкодер",
            "ok",
            "В промпт ушли текст, сумма и срок. Из JSON оставлены поток, основание, риски и цитата. "
            "Покрытие и платёж модели выброшены: платёж считается аннуитетом отдельно.",
            [
                {"label": "оставлено, поток", "value": "нет числа" if flow is None else money(flow)},
                {"label": "оставлено, основание", "value": BASIS_FACE.get(basis_text, basis_text or "пусто")},
                {"label": "оставлено, риски", "value": risk_phrase(risk_list) if risk_list else "нет"},
                {"label": "выброшено, coverage", "value": shown(parsed.get("coverage"))},
                {"label": "выброшено, monthly_payment_rub", "value": shown(parsed.get("monthly_payment_rub"))},
            ],
            pre=raw,
        )
    )
    quote_ok = bool(quote) and quote in text
    if quote_ok:
        steps.append(step("Цитата", "ok", "Фраза из ответа есть в тексте дословно, без правок.", [{"label": "цитата", "value": quote}]))
    else:
        detail = "Модель не привела цитату." if not quote else "Этой фразы нет в тексте как дословной подстроки. Скорер на таком ответе не запускается."
        steps.append(step("Цитата", "fail", detail, [{"label": "цитата модели", "value": quote or "пусто"}]))

    steps.append(payment_step(amount, term, payment))

    reason = None
    if not quote_ok:
        reason = "quote"
    elif flow is None:
        reason = "flow"
    elif not risks_ok or unknown:
        reason = "risks"
        if unknown:
            steps.append(
                step(
                    "Риски",
                    "fail",
                    "Эти коды не входят в список энкодера, в сеть их подставить нельзя: " + ", ".join(unknown) + ".",
                )
            )

    if reason is None:
        row = {
            "encoder": {"inferred_monthly_flow_rub": flow, "risks": risk_list},
            "own_funds_rub": own,
            "credit_rating": 0 if rating is None else rating,
            "credit_rating_missing": rating is None,
            "income_confirmed": fields["income_confirmed"],
            "costs_confirmed": False,
            "capital_confirmed": fields["capital_confirmed"],
            "loan_amount_rub": amount,
            "loan_term_months": term,
            "monthly_payment_rub": payment,
        }
        try:
            features, logits, raw_limit = predict(row)
        except (SystemExit, Exception) as exc:
            message = str(exc) or "скорер не принял строку"
            steps.append(step("Строка скорера", "fail", message))
            steps.append(step("Скорер", "skip", "Не вызывался из-за ошибки сборки строки."))
            return formula_finish(steps, "scorer", amount, term, payment, flow, basis_text, [], False)
        if raw_limit not in LIMITS:
            steps.append(step("Скорер", "fail", "Сеть вернула лимит вне шкалы 0, 300 000, 800 000, 2 000 000."))
            return formula_finish(steps, "scorer", amount, term, payment, flow, basis_text, risk_list, True)
        steps.append(
            step(
                "Строка скорера",
                "ok",
                "Порядок признаков тот же, что при обучении. Выручка и расходы анкеты в строку не входят. "
                f"Деньги делятся на {rub(int(MONEY_SCALE))}, рейтинг — на {rub(int(RATING_SCALE))}.",
                vector_rows(row, features),
            )
        )
        limit = raw_limit if raw_limit <= amount else amount
        steps.append(
            step(
                "Скорер",
                "ok",
                "Четыре логита, берётся класс с наибольшим. Классы только 0, 300 000, 800 000 и 2 000 000.",
                [{"label": money(LIMITS[index]), "value": f"логит {logits[index]:.3f}"} for index in range(len(LIMITS))]
                + [{"label": "класс", "value": money(raw_limit)}],
            )
        )
        if raw_limit > amount:
            steps.append(
                step(
                    "Обрезка",
                    "ok",
                    "Класс выше запроса, лимит срезан до запрошенной суммы.",
                    [{"label": "было", "value": money(raw_limit)}, {"label": "стало", "value": money(limit)}],
                )
            )
        else:
            steps.append(step("Обрезка", "ok", "Класс не выше запроса, лимит остаётся как выбрала сеть."))
        decision = decision_of(limit, amount, True)
        approved = annuity(limit, term) if limit > 0 else None
        return finish(
            decision,
            False,
            amount,
            term,
            payment,
            limit,
            flow,
            quote,
            steps,
            paragraphs(decision, False, None, amount, term, payment, limit, approved, flow, basis_text, risk_list, True, raw_limit),
        )

    steps.append(step("Скорер", "skip", "Не вызывался: " + skip_reason(reason)))
    report_risks = risk_list if reason == "scorer" else []
    quote_for_answer = quote if reason == "scorer" else None
    return formula_finish(
        steps,
        reason,
        amount,
        term,
        payment,
        flow,
        basis_text,
        report_risks,
        reason == "scorer",
        quote_for_answer,
    )


def skip_reason(reason: str) -> str:
    if reason == "quote":
        return "цитаты нет в тексте."
    if reason == "flow":
        return "в отчёте нет числового потока."
    if reason == "risks":
        return "список рисков нельзя подать в сеть."
    return "строка для сети не собралась."


def formula_finish(
    steps: list[dict],
    reason: str,
    amount: int,
    term: int,
    payment: int,
    flow: int | None,
    basis: str,
    risks: list[str],
    quote_ok: bool,
    quote: str | None = None,
) -> dict:
    limit, rows = math_limit(flow, amount, term)
    steps.append(
        step(
            "Формула",
            "fallback",
            "Наибольшая ступень 300 000, 800 000 или 2 000 000, которая не выше запроса и чей аннуитет не больше потока. "
            "Срок в аннуитете — тот, что написан в заявке.",
            rows,
        )
    )
    decision = decision_of(limit, amount, flow is not None)
    approved = annuity(limit, term) if limit is not None and limit > 0 else None
    return finish(
        decision,
        True,
        amount,
        term,
        payment,
        limit,
        flow,
        quote if quote_ok else None,
        steps,
        paragraphs(decision, True, reason, amount, term, payment, limit, approved, flow, basis, risks, quote_ok, None),
    )


def payment_step(amount: int, term: int, payment: int) -> dict:
    return step(
        "Платёж",
        "ok",
        "Аннуитет от запрошенной суммы. Ставка 20% годовых, месячная ставка 0,20 / 12, срок из заявки. "
        "Округление половины вверх до рубля. Платёж из ответа энкодера сюда не подставляется.",
        [
            {"label": "сумма", "value": money(amount)},
            {"label": "срок", "value": f"{term} мес."},
            {"label": "ставка", "value": "20% годовых"},
            {"label": "платёж", "value": money(payment) + " в месяц"},
        ],
    )


def shown(value: object) -> str:
    if value is None:
        return "пусто"
    return str(value)


def predict(row: dict) -> tuple:
    features = featurize(row)
    import torch

    with torch.no_grad():
        logits = SCORER(torch.from_numpy(features).unsqueeze(0)).squeeze(0)
    index = int(logits.argmax().item())
    return features, [float(item) for item in logits.tolist()], class_to_limit(index)


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        path = self.path.split("?", 1)[0]
        if path not in ("/", "/index.html"):
            self.send_error(404)
            return
        send_bytes(self, 200, INDEX.read_bytes(), "text/html; charset=utf-8")

    def do_POST(self) -> None:
        if self.path.split("?", 1)[0] != "/score":
            self.send_error(404)
            return
        try:
            payload = read_json(self)
        except PipelineError as exc:
            send_json(self, 400, {"error": str(exc)})
            return
        try:
            result = pipeline(payload)
        except Exception:
            traceback.print_exc()
            send_json(self, 500, {"error": "Сбой прогона."})
            return
        send_json(self, 200, result)

    def log_message(self, fmt: str, *args) -> None:
        print(f"{self.address_string()} {fmt % args}", flush=True)


def load_models() -> None:
    global ENCODER, TOKENIZER, GENERATE, SCORER
    from mlx_lm import generate, load

    GENERATE = generate
    print("загружаю Qwen2.5-1.5B", flush=True)
    ENCODER, TOKENIZER = load(str(encoder_run.BASE), adapter_path=str(encoder_run.ADAPTER))
    print("загружаю MLP", flush=True)
    probe = {
        "encoder": {"inferred_monthly_flow_rub": 0, "risks": []},
        "credit_rating": 0,
        "own_funds_rub": None,
        "loan_amount_rub": AMOUNTS[0],
        "loan_term_months": 12,
        "income_confirmed": False,
        "costs_confirmed": False,
        "capital_confirmed": False,
        "monthly_payment_rub": annuity(AMOUNTS[0], 12),
    }
    SCORER = load_model(int(featurize(probe).shape[0]))
    if not isinstance(SCORER, LimitMLP):
        raise SystemExit("скорер не LimitMLP")


def main() -> None:
    load_models()
    HTTPServer.allow_reuse_address = True
    server = HTTPServer((HOST, PORT), Handler)
    print(f"слушаю http://{HOST}:{PORT}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
