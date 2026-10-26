from app.catalog import PRODUCT_CODES, product_by_code
from app.db_models import Application, Credit, User
from app.scoring.calculator import calculate_annuity_payment

DEMO_PROFILES = [
    {
        "id": "user-demo-anna",
        "phone": "79001000001",
        "full_name": "Анна Соколова",
        "role": "Директор",
        "email": "anna.sokolova@severnaya.example",
        "company": {
            "inn": "7701234567",
            "ogrn": "1027700132195",
            "name": "Общество с ограниченной ответственностью «Северная линия»",
            "short_name": "ООО «Северная линия»",
            "status": "Действующая",
            "registration_date": "2016-04-12",
            "okved": "46.90 Торговля оптовая",
            "monthly_revenue_rub": 2_400_000,
            "credit_rating": 742,
            "rating_grade": "A",
            "preapproved_limit_rub": 2_000_000,
        },
    },
    {
        "id": "user-demo-ilya",
        "phone": "79001000002",
        "full_name": "Илья Морозов",
        "role": "Индивидуальный предприниматель",
        "email": "ilya.morozov@zerno.example",
        "company": {
            "inn": "780245678901",
            "ogrn": "321784700012345",
            "name": "Индивидуальный предприниматель Морозов Илья Сергеевич",
            "short_name": "ИП Морозов И. С.",
            "status": "Действующий",
            "registration_date": "2021-09-03",
            "okved": "56.10 Рестораны и кафе",
            "monthly_revenue_rub": 420_000,
            "credit_rating": 510,
            "rating_grade": "B",
            "preapproved_limit_rub": 800_000,
        },
    },
    {
        "id": "user-demo-maria",
        "phone": "79001000003",
        "full_name": "Мария Белова",
        "role": "Финансовый директор",
        "email": "maria.belova@kontur.example",
        "company": {
            "inn": "5403123456",
            "ogrn": "1145476001234",
            "name": "Общество с ограниченной ответственностью «Контур Снаб»",
            "short_name": "ООО «Контур Снаб»",
            "status": "Действующая",
            "registration_date": "2014-11-20",
            "okved": "46.69 Торговля оптовая прочими машинами",
            "monthly_revenue_rub": 5_100_000,
            "credit_rating": 810,
            "rating_grade": "A",
            "preapproved_limit_rub": 2_000_000,
        },
    },
]

DEMO_PHONES = {item["phone"] for item in DEMO_PROFILES}


def public_profiles():
    return [
        {
            "phone": item["phone"],
            "full_name": item["full_name"],
            "role": item["role"],
            "company_name": item["company"]["short_name"],
        }
        for item in DEMO_PROFILES
    ]


def _report(basis: str, quote: str):
    return {"flow_basis": basis, "risks": [], "quote": quote}


def seed_demo(db) -> None:
    profiles = {item["id"]: item for item in DEMO_PROFILES}
    for item in DEMO_PROFILES:
        user = db.query(User).filter(User.phone == item["phone"]).first()
        if user is None:
            user = User(
                id=item["id"],
                phone=item["phone"],
                token=f"seed-{item['phone']}",
                full_name=item["full_name"],
                role=item["role"],
                email=item["email"],
                company=item["company"],
            )
            db.add(user)
        else:
            user.full_name = user.full_name or item["full_name"]
            user.role = user.role or item["role"]
            user.email = user.email or item["email"]
            user.company = user.company or item["company"]
    db.flush()

    def user_id(profile_id: str) -> str:
        phone = profiles[profile_id]["phone"]
        return db.query(User).filter(User.phone == phone).one().id

    records = _history(user_id)
    for application, credit in records:
        if application["product"] not in PRODUCT_CODES:
            continue
        _upsert(db, Application, application)
        if credit is not None:
            _upsert(db, Credit, credit)
    db.commit()


def _upsert(db, model, payload: dict) -> None:
    row = db.get(model, payload["id"])
    if row is None:
        db.add(model(**payload))
        return
    for key, value in payload.items():
        if key != "id":
            setattr(row, key, value)


def _payment(product: str, amount_rub: int, term_months: int) -> int:
    return calculate_annuity_payment(amount_rub, term_months, product_by_code(product)["annual_rate"])


def _history(user_id):
    anna = user_id("user-demo-anna")
    ilya = user_id("user-demo-ilya")
    maria = user_id("user-demo-maria")
    anna_payment = _payment("working_capital", 800_000, 12)
    ilya_request_payment = _payment("startup", 800_000, 18)
    ilya_credit_payment = _payment("startup", 500_000, 18)
    ilya_reject_payment = _payment("equipment", 2_000_000, 12)
    maria_overdraft_payment = _payment("overdraft", 1_500_000, 12)
    maria_contract_payment = _payment("contract", 1_000_000, 12)

    return [
        (
            {
                "id": "app-demo-anna-wc",
                "user_id": anna,
                "status": "scored",
                "product": "working_capital",
                "phone": "79001000001",
                "purpose": "Закупка товара",
                "loan_amount_rub": 800_000,
                "loan_term_months": 12,
                "profitability_rub": 240_000,
                "profitability_confirmed": True,
                "collateral": False,
                "business_plan": "",
                "created_at": "2026-09-02T10:00:00+00:00",
                "pipeline": "math",
                "fallback": True,
                "monthly_payment_rub": anna_payment,
                "flow_rub": 240_000,
                "limit_rub": 800_000,
                "decision": "approve",
                "credit_id": "credit-demo-anna-wc",
                "report": _report("form", ""),
            },
            {
                "id": "credit-demo-anna-wc",
                "application_id": "app-demo-anna-wc",
                "user_id": anna,
                "product": "working_capital",
                "status": "active",
                "amount_rub": 800_000,
                "loan_term_months": 12,
                "monthly_payment_rub": anna_payment,
                "purpose": "Закупка товара",
                "created_at": "2026-09-02T10:00:00+00:00",
            },
        ),
        (
            {
                "id": "app-demo-ilya-start",
                "user_id": ilya,
                "status": "scored",
                "product": "startup",
                "phone": "79001000002",
                "purpose": "",
                "loan_amount_rub": 800_000,
                "loan_term_months": 18,
                "profitability_rub": None,
                "profitability_confirmed": False,
                "collateral": False,
                "business_plan": "Кофейня у метро. Выручка 40000 руб. в месяц.",
                "created_at": "2026-08-15T12:00:00+00:00",
                "pipeline": "math",
                "fallback": True,
                "monthly_payment_rub": ilya_request_payment,
                "flow_rub": 40_000,
                "limit_rub": 500_000,
                "decision": "reduced",
                "credit_id": "credit-demo-ilya-start",
                "report": _report("inferred", ""),
            },
            {
                "id": "credit-demo-ilya-start",
                "application_id": "app-demo-ilya-start",
                "user_id": ilya,
                "product": "startup",
                "status": "active",
                "amount_rub": 500_000,
                "loan_term_months": 18,
                "monthly_payment_rub": ilya_credit_payment,
                "purpose": "",
                "created_at": "2026-08-15T12:00:00+00:00",
            },
        ),
        (
            {
                "id": "app-demo-ilya-equip",
                "user_id": ilya,
                "status": "scored",
                "product": "equipment",
                "phone": "79001000002",
                "purpose": "Кофемашина",
                "loan_amount_rub": 2_000_000,
                "loan_term_months": 12,
                "profitability_rub": 5_000,
                "profitability_confirmed": False,
                "collateral": False,
                "business_plan": "",
                "created_at": "2026-10-01T09:30:00+00:00",
                "pipeline": "math",
                "fallback": True,
                "monthly_payment_rub": ilya_reject_payment,
                "flow_rub": 5_000,
                "limit_rub": 0,
                "decision": "reject",
                "credit_id": None,
                "report": _report("form", ""),
            },
            None,
        ),
        (
            {
                "id": "app-demo-maria-over",
                "user_id": maria,
                "status": "scored",
                "product": "overdraft",
                "phone": "79001000003",
                "purpose": "",
                "loan_amount_rub": 1_500_000,
                "loan_term_months": 12,
                "profitability_rub": 900_000,
                "profitability_confirmed": True,
                "collateral": False,
                "business_plan": "",
                "created_at": "2026-07-01T08:00:00+00:00",
                "pipeline": "math",
                "fallback": True,
                "monthly_payment_rub": maria_overdraft_payment,
                "flow_rub": 900_000,
                "limit_rub": 1_500_000,
                "decision": "approve",
                "credit_id": "credit-demo-maria-over",
                "report": _report("form", ""),
            },
            {
                "id": "credit-demo-maria-over",
                "application_id": "app-demo-maria-over",
                "user_id": maria,
                "product": "overdraft",
                "status": "active",
                "amount_rub": 1_500_000,
                "loan_term_months": 12,
                "monthly_payment_rub": maria_overdraft_payment,
                "purpose": "",
                "created_at": "2026-07-01T08:00:00+00:00",
            },
        ),
        (
            {
                "id": "app-demo-maria-contract",
                "user_id": maria,
                "status": "scored",
                "product": "contract",
                "phone": "79001000003",
                "purpose": "Поставка оборудования",
                "loan_amount_rub": 1_000_000,
                "loan_term_months": 12,
                "profitability_rub": 500_000,
                "profitability_confirmed": True,
                "collateral": False,
                "business_plan": "",
                "created_at": "2026-10-10T11:20:00+00:00",
                "pipeline": "math",
                "fallback": True,
                "monthly_payment_rub": maria_contract_payment,
                "flow_rub": 500_000,
                "limit_rub": 1_000_000,
                "decision": "approve",
                "credit_id": "credit-demo-maria-contract",
                "report": _report("form", ""),
            },
            {
                "id": "credit-demo-maria-contract",
                "application_id": "app-demo-maria-contract",
                "user_id": maria,
                "product": "contract",
                "status": "active",
                "amount_rub": 1_000_000,
                "loan_term_months": 12,
                "monthly_payment_rub": maria_contract_payment,
                "purpose": "Поставка оборудования",
                "created_at": "2026-10-10T11:20:00+00:00",
            },
        ),
    ]
