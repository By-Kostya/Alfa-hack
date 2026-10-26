PRODUCTS = [
    {
        "code": "working_capital",
        "title": "Оборотный кредит",
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
        "fields": ["loan_amount_rub", "loan_term_months", "business_plan"],
    },
    {
        "code": "equipment",
        "title": "Кредит на оборудование",
        "fields": ["loan_amount_rub", "loan_term_months", "purpose", "profitability_rub"],
    },
    {
        "code": "contract",
        "title": "Кредит под контракт",
        "fields": ["loan_amount_rub", "loan_term_months", "purpose", "profitability_rub"],
    },
    {
        "code": "overdraft",
        "title": "Овердрафт",
        "fields": ["loan_amount_rub", "loan_term_months", "profitability_rub"],
    },
    {
        "code": "refinance",
        "title": "Рефинансирование",
        "fields": ["loan_amount_rub", "loan_term_months", "purpose", "profitability_rub"],
    },
]

PRODUCT_CODES = {item["code"] for item in PRODUCTS}
PRODUCT_LIST = [{"code": item["code"], "title": item["title"]} for item in PRODUCTS]


def product_by_code(code: str):
    for item in PRODUCTS:
        if item["code"] == code:
            return item
    return None
