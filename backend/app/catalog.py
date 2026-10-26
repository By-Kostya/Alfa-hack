from decimal import Decimal

PRODUCTS = [
    {
        "code": "working_capital",
        "title": "Оборотный кредит",
        "annual_rate": Decimal("0.18"),
        "annual_rate_pct": 18,
        "min_amount_rub": 300_000,
        "max_amount_rub": 3_000_000,
        "min_term_months": 3,
        "max_term_months": 24,
        "limit_steps": [3_000_000, 1_500_000, 800_000, 300_000],
        "fields": [
            "loan_amount_rub",
            "loan_term_months",
            "purpose",
            "profitability_rub",
            "profitability_confirmed",
            "collateral",
        ],
    },
    {
        "code": "startup",
        "title": "Кредит на старт",
        "annual_rate": Decimal("0.24"),
        "annual_rate_pct": 24,
        "min_amount_rub": 200_000,
        "max_amount_rub": 1_000_000,
        "min_term_months": 6,
        "max_term_months": 36,
        "limit_steps": [1_000_000, 500_000, 200_000],
        "fields": ["loan_amount_rub", "loan_term_months", "business_plan"],
    },
    {
        "code": "equipment",
        "title": "Кредит на оборудование",
        "annual_rate": Decimal("0.16"),
        "annual_rate_pct": 16,
        "min_amount_rub": 500_000,
        "max_amount_rub": 5_000_000,
        "min_term_months": 12,
        "max_term_months": 60,
        "limit_steps": [5_000_000, 2_000_000, 1_000_000, 500_000],
        "fields": ["loan_amount_rub", "loan_term_months", "purpose", "profitability_rub"],
    },
    {
        "code": "contract",
        "title": "Кредит под контракт",
        "annual_rate": Decimal("0.19"),
        "annual_rate_pct": 19,
        "min_amount_rub": 400_000,
        "max_amount_rub": 2_000_000,
        "min_term_months": 3,
        "max_term_months": 18,
        "limit_steps": [2_000_000, 1_000_000, 400_000],
        "fields": ["loan_amount_rub", "loan_term_months", "purpose", "profitability_rub"],
    },
    {
        "code": "overdraft",
        "title": "Овердрафт",
        "annual_rate": Decimal("0.22"),
        "annual_rate_pct": 22,
        "min_amount_rub": 100_000,
        "max_amount_rub": 1_500_000,
        "min_term_months": 1,
        "max_term_months": 12,
        "limit_steps": [1_500_000, 500_000, 100_000],
        "fields": ["loan_amount_rub", "loan_term_months", "profitability_rub"],
    },
    {
        "code": "refinance",
        "title": "Рефинансирование",
        "annual_rate": Decimal("0.14"),
        "annual_rate_pct": 14,
        "min_amount_rub": 300_000,
        "max_amount_rub": 4_000_000,
        "min_term_months": 6,
        "max_term_months": 60,
        "limit_steps": [4_000_000, 2_000_000, 800_000, 300_000],
        "fields": ["loan_amount_rub", "loan_term_months", "purpose", "profitability_rub"],
    },
]

PRODUCT_CODES = {item["code"] for item in PRODUCTS}


def product_by_code(code: str):
    for item in PRODUCTS:
        if item["code"] == code:
            return item
    return None


def _rub(amount: int) -> str:
    return f"{amount:,}".replace(",", " ") + " ₽"


def offer_error(code: str, amount_rub: int, term_months: int):
    spec = product_by_code(code)
    if spec is None:
        return "Неизвестный продукт."
    if amount_rub < spec["min_amount_rub"] or amount_rub > spec["max_amount_rub"]:
        return (
            f"Сумма для этого продукта — от {_rub(spec['min_amount_rub'])} "
            f"до {_rub(spec['max_amount_rub'])}."
        )
    if term_months < spec["min_term_months"] or term_months > spec["max_term_months"]:
        return (
            f"Срок для этого продукта — от {spec['min_term_months']} "
            f"до {spec['max_term_months']} месяцев."
        )
    return None


def public_product(item: dict, with_fields: bool = False) -> dict:
    payload = {
        "code": item["code"],
        "title": item["title"],
        "annual_rate_pct": item["annual_rate_pct"],
        "min_amount_rub": item["min_amount_rub"],
        "max_amount_rub": item["max_amount_rub"],
        "min_term_months": item["min_term_months"],
        "max_term_months": item["max_term_months"],
    }
    if with_fields:
        payload["fields"] = item["fields"]
    return payload


PRODUCT_LIST = [public_product(item) for item in PRODUCTS]
