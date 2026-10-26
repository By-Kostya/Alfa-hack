import re
from decimal import Decimal
from typing import Any, Dict, Optional

from app.catalog import product_by_code
from app.scoring.calculator import ANNUAL_RATE, calculate_annuity_payment

LIMIT_STEPS = [2_000_000, 800_000, 300_000]


def evaluate_math_pipeline(
    loan_amount_rub: int,
    loan_term_months: int,
    flow_rub: Optional[int],
    flow_basis: str = "form",
    annual_rate: Decimal = ANNUAL_RATE,
    limit_steps: Optional[list] = None,
) -> Dict[str, Any]:
    """
    Математический фолбек по правилам контракта.
    """
    # 1. Аннуитет запрошенной суммы
    steps = LIMIT_STEPS if limit_steps is None else limit_steps
    monthly_payment = calculate_annuity_payment(loan_amount_rub, loan_term_months, annual_rate)

    # 2. Если потока нет вообще
    if flow_rub is None:
        return {
            "pipeline": "math",
            "fallback": True,
            "monthly_payment_rub": monthly_payment,
            "flow_rub": None,
            "limit_rub": None,
            "decision": "unknown",
            "report": {
                "flow_basis": flow_basis,
                "risks": [],
                "quote": "",
            },
        }

    # 3. Если поток не положительный
    if flow_rub <= 0:
        return {
            "pipeline": "math",
            "fallback": True,
            "monthly_payment_rub": monthly_payment,
            "flow_rub": flow_rub,
            "limit_rub": 0,
            "decision": "reject",
            "report": {
                "flow_basis": flow_basis,
                "risks": [],
                "quote": "",
            },
        }

    # 4. Поиск наибольшей подходящей ступени
    limit_rub = 0
    for step in steps:
        if step <= loan_amount_rub:
            step_payment = calculate_annuity_payment(step, loan_term_months, annual_rate)
            if step_payment <= flow_rub:
                limit_rub = step
                break

    # 5. Определение решения
    if limit_rub == loan_amount_rub:
        decision = "approve"
    elif 0 < limit_rub < loan_amount_rub:
        decision = "reduced"
    else:
        decision = "reject"

    return {
        "pipeline": "math",
        "fallback": True,
        "monthly_payment_rub": monthly_payment,
        "flow_rub": flow_rub,
        "limit_rub": limit_rub,
        "decision": decision,
        "report": {
            "flow_basis": flow_basis,
            "risks": [],
            "quote": "",
        },
    }


def flow_from_plan(text: Optional[str]) -> Optional[int]:
    """Демо-поток из текста плана, пока энкодер не подключён."""
    if not text or not text.strip():
        return None
    found = []
    for match in re.finditer(r"\d[\d\s]{2,}", text):
        digits = re.sub(r"\s+", "", match.group())
        if digits.isdigit():
            found.append(int(digits))
    monthly = [value for value in found if 10_000 <= value <= 5_000_000]
    if monthly:
        return max(monthly)
    return None


def run_scoring_pipeline(
    product: str,
    loan_amount_rub: int,
    loan_term_months: int,
    profitability_rub: Optional[int] = None,
    business_plan: Optional[str] = None,
    own_funds_rub: Optional[int] = None,
    credit_rating: Optional[int] = None,
    profitability_confirmed: bool = False,
) -> Dict[str, Any]:
    """
    Главный вход в скоринг.
    Сначала пытается запустить AI.
    При любой ошибке или отсутствии модели — гарантированный математический фолбек.
    """
    try:
        # TODO: Здесь будет вызов реального AI энкодера/модели
        # Если модель пока не подключена — выбрасываем исключение для срабатывания фолбека
        raise NotImplementedError("AI pipeline pending integration")

    except Exception:
        # Безопасный переход на математику (fallback: True)
        flow = profitability_rub
        basis = "form" if flow is not None else "unknown"
        if flow is None and business_plan and business_plan.strip():
            inferred = flow_from_plan(business_plan)
            if inferred is not None:
                flow = inferred
                basis = "inferred"
        spec = product_by_code(product)
        return evaluate_math_pipeline(
            loan_amount_rub=loan_amount_rub,
            loan_term_months=loan_term_months,
            flow_rub=flow,
            flow_basis=basis,
            annual_rate=spec["annual_rate"] if spec else ANNUAL_RATE,
            limit_steps=spec["limit_steps"] if spec else LIMIT_STEPS,
        )