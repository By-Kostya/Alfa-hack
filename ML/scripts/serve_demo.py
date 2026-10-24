#!/usr/bin/env python3
"""Ручной прогон: страница, энкодер, аннуитет, скорер лимита.

Qwen и MLP читаются один раз при старте. Веса не пишутся, дообучения нет.
"""

from __future__ import annotations

import json
import sys
import traceback
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tmp"))
sys.path.insert(0, str(ROOT / "scripts"))

import run_encoder_reports as encoder_run
from train_scorer_limit import (
    AMOUNTS,
    LIMITS,
    RATINGS,
    RISKS,
    TERM,
    LimitMLP,
    annuity,
    class_to_limit,
    featurize,
    load_model,
)

HOST = "127.0.0.1"
PORT = 8765
INDEX = ROOT / "demo" / "index.html"
PLANS = {Path(name).stem: encoder_run.LONG / name for name in encoder_run.PLANS}

ENCODER = None
TOKENIZER = None
GENERATE = None
SCORER: LimitMLP | None = None


class PipelineError(Exception):
    """Запрос или отчёт энкодера не дошли до скорера."""


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


def form_fields(payload: dict) -> dict:
    text = payload.get("plan_text")
    if not isinstance(text, str) or not text.strip():
        raise PipelineError("Напишите бизнес-план.")
    text = text.strip()
    if len(text) > 100_000:
        raise PipelineError("План слишком длинный.")
    amount = whole_number(payload.get("loan_amount_rub"), "Сумма должна быть целым числом.")
    if amount < 1 or amount > 100_000_000_000:
        raise PipelineError("Сумма должна быть больше нуля.")
    term = whole_number(payload.get("loan_term_months"), "Срок должен быть целым числом месяцев.")
    if term < 1 or term > 360:
        raise PipelineError("Срок от 1 до 360 месяцев.")
    rating = whole_number(payload.get("credit_rating"), "Неизвестный рейтинг.")
    if rating not in RATINGS:
        raise PipelineError("Неизвестный рейтинг.")
    if "own_funds_rub" not in payload or payload["own_funds_rub"] is None:
        own = None
    else:
        own = whole_number(payload["own_funds_rub"], "Свои деньги — целое число или пусто.")
    if own is not None and (own < 0 or own > 100_000_000_000):
        raise PipelineError("Свои деньги не могут быть отрицательными.")
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


def encoder_report(text: str, amount: int, term: int) -> dict:
    raw = GENERATE(
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
    parsed = encoder_run.parse_coverage(raw)
    if not parsed:
        raise PipelineError("Энкодер вернул не JSON.")
    quote = str(parsed.get("quote") or "")
    if not quote or quote not in text:
        raise PipelineError("Цитаты нет в тексте плана.")
    risks = parsed.get("risks")
    if not isinstance(risks, list) or not all(isinstance(item, str) for item in risks):
        raise PipelineError("В отчёте нет списка рисков.")
    unknown = [item for item in risks if item not in RISKS]
    if unknown:
        raise PipelineError("Неизвестные риски: " + ", ".join(unknown) + ".")
    flow = parsed.get("inferred_monthly_flow_rub")
    return {
        "inferred_monthly_flow_rub": whole_number(flow, "В отчёте нет числового потока."),
        "flow_basis": parsed.get("flow_basis"),
        "risks": list(risks),
        "quote": quote,
    }


def score_payload(payload: dict) -> dict:
    fields = form_fields(payload)
    text = fields["plan_text"]
    report = encoder_report(text, fields["loan_amount_rub"], fields["loan_term_months"])
    payment = annuity(fields["loan_amount_rub"], fields["loan_term_months"])
    row = {
        "encoder": {
            "inferred_monthly_flow_rub": report["inferred_monthly_flow_rub"],
            "risks": report["risks"],
        },
        "own_funds_rub": fields["own_funds_rub"],
        "credit_rating": fields["credit_rating"],
        "income_confirmed": fields["income_confirmed"],
        "costs_confirmed": False,
        "capital_confirmed": fields["capital_confirmed"],
        "loan_amount_rub": fields["loan_amount_rub"],
        "loan_term_months": fields["loan_term_months"],
        "monthly_payment_rub": payment,
    }
    features = featurize(row)
    import torch

    with torch.no_grad():
        logits = SCORER(torch.from_numpy(features).unsqueeze(0))
        index = int(logits.argmax(dim=-1).item())
    limit = class_to_limit(index)
    if limit not in LIMITS:
        raise PipelineError("Скорер вернул лимит вне шкалы.")
    print(
        f"сумма {fields['loan_amount_rub']} срок {fields['loan_term_months']} "
        f"платёж {payment} лимит {limit}",
        flush=True,
    )
    return {
        "report": report,
        "monthly_payment_rub": payment,
        "limit_rub": limit,
    }


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/plan":
            name = parse_qs(parsed.query).get("name", [""])[0]
            path = PLANS.get(name)
            if path is None:
                send_json(self, 400, {"error": "Неизвестный план."})
                return
            send_json(self, 200, {"plan_text": encoder_run.plan_text_of(path)})
            return
        if parsed.path not in ("/", "/index.html"):
            self.send_error(404)
            return
        send_bytes(self, 200, INDEX.read_bytes(), "text/html; charset=utf-8")

    def do_POST(self) -> None:
        if self.path.split("?", 1)[0] != "/score":
            self.send_error(404)
            return
        try:
            payload = read_json(self)
            result = score_payload(payload)
        except PipelineError as exc:
            print(f"ошибка: {exc}", flush=True)
            send_json(self, 400, {"error": str(exc)})
            return
        except SystemExit as exc:
            message = str(exc) or "Скорер не принял строку."
            print(f"ошибка: {message}", flush=True)
            send_json(self, 400, {"error": message})
            return
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
        "credit_rating": RATINGS[0],
        "own_funds_rub": None,
        "loan_amount_rub": AMOUNTS[0],
        "loan_term_months": TERM,
        "income_confirmed": False,
        "costs_confirmed": False,
        "capital_confirmed": False,
        "monthly_payment_rub": annuity(AMOUNTS[0], TERM),
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
