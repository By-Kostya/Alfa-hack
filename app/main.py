import os
import json
import uuid
from typing import Optional, List, Dict, Any, Union
from fastapi import FastAPI, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from app.database import engine, get_db, Base, SessionLocal
from app import db_models
from app import models
from app.auth import get_current_user_required, get_current_user_optional
from app.scoring.pipeline import run_scoring_pipeline
from app.scoring.calculator import calculate_annuity_payment

Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="Alfa Credit Core API",
    version="1.0.0",
    description="Цифровой кредитный конвейер малого бизнеса: база продуктов, ИИ-скоринг, личный кабинет."
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

ALLOWED_PHONES = {"79001111111", "79002222222", "79003333333"}
PHONE_ERROR_MSG = "Пользователь не найден. Доступны тестовые номера: 79001111111, 79002222222, 79003333333"


# --- Автоматический сид профилей И продуктов в БД ---
def seed_initial_data():
    db = SessionLocal()
    try:
        # 1. Сидирование профилей пользователей и компаний
        profiles_path = "data/synthetic_profiles.json"
        if os.path.exists(profiles_path):
            with open(profiles_path, "r", encoding="utf-8") as f:
                profiles = json.load(f)
            for p in profiles:
                user = db.query(db_models.User).filter(db_models.User.phone == p["phone"]).first()
                if not user:
                    user = db_models.User(
                        phone=p["phone"],
                        token=f"tok_{uuid.uuid4().hex[:12]}",
                        full_name=p.get("full_name", "Предприниматель"),
                        role=p.get("role", "Руководитель"),
                        email=p.get("email", "")
                    )
                    db.add(user)
                    db.flush()

                company = db.query(db_models.Company).filter(db_models.Company.user_id == user.id).first()
                if not company and "company" in p:
                    c = p["company"]
                    company = db_models.Company(
                        user_id=user.id,
                        inn=c["inn"],
                        ogrn=c.get("ogrn", ""),
                        name=c["name"],
                        short_name=c.get("short_name", ""),
                        status=c.get("status", "Действующее предприятие"),
                        registration_date=c.get("registration_date", "2022-01-01"),
                        okved=c.get("okved", ""),
                        monthly_revenue_rub=c.get("monthly_revenue_rub", 0),
                        credit_rating=c.get("credit_rating", 500),
                        rating_grade=c.get("rating_grade", "Средняя надежность"),
                        preapproved_limit_rub=c.get("preapproved_limit_rub", 0)
                    )
                    db.add(company)

        # 2. Сидирование продуктов из JSON в БД
        products_path = "data/credit_products.json"
        if os.path.exists(products_path):
            with open(products_path, "r", encoding="utf-8") as f:
                products_list = json.load(f)
            for prod in products_list:
                existing = db.query(db_models.Product).filter(db_models.Product.code == prod["code"]).first()
                if not existing:
                    db_prod = db_models.Product(
                        code=prod["code"],
                        title=prod["title"],
                        description=prod.get("description", ""),
                        badge=prod.get("badge", ""),
                        rate_pct=prod.get("rate_pct", 20.0),
                        min_amount_rub=prod.get("min_amount_rub", 300000),
                        max_amount_rub=prod.get("max_amount_rub", 2000000),
                        min_term_months=prod.get("min_term_months", 3),
                        max_term_months=prod.get("max_term_months", 36),
                        fields=prod.get("fields", [])
                    )
                    db.add(db_prod)

        db.commit()
    except Exception as e:
        print(f"Error seeding data: {e}")
        db.rollback()
    finally:
        db.close()


@app.on_event("startup")
def on_startup():
    seed_initial_data()


# --- Обработчики ошибок ---
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    errors = exc.errors()
    msg = errors[0].get("msg", "Ошибка валидации входных данных.") if errors else "Некорректные данные."
    return JSONResponse(status_code=400, content={"error": msg})


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    if isinstance(exc.detail, dict) and "error" in exc.detail:
        return JSONResponse(status_code=exc.status_code, content=exc.detail)
    return JSONResponse(status_code=exc.status_code, content={"error": str(exc.detail)})


# --- Сериализаторы ---
def serialize_product_item(p: db_models.Product) -> Dict[str, Any]:
    return {
        "code": p.code,
        "title": p.title,
        "description": p.description,
        "badge": p.badge,
        "rate_pct": p.rate_pct,
        "min_amount_rub": p.min_amount_rub,
        "max_amount_rub": p.max_amount_rub,
        "min_term_months": p.min_term_months,
        "max_term_months": p.max_term_months,
    }


def serialize_product_detail(p: db_models.Product) -> Dict[str, Any]:
    res = serialize_product_item(p)
    res["fields"] = p.fields or []
    return res


def serialize_company(comp: Optional[db_models.Company]) -> Optional[Dict[str, Any]]:
    if not comp:
        return None
    return {
        "inn": comp.inn,
        "ogrn": comp.ogrn,
        "name": comp.name,
        "short_name": comp.short_name,
        "status": comp.status,
        "registration_date": comp.registration_date,
        "okved": comp.okved,
        "monthly_revenue_rub": comp.monthly_revenue_rub,
        "credit_rating": comp.credit_rating,
        "rating_grade": comp.rating_grade,
        "preapproved_limit_rub": comp.preapproved_limit_rub
    }


def serialize_user(user: db_models.User) -> Dict[str, Any]:
    return {
        "id": user.id,
        "phone": user.phone,
        "full_name": user.full_name,
        "role": user.role,
        "email": user.email
    }


def serialize_application(app_obj: db_models.Application) -> Dict[str, Any]:
    return {
        "id": app_obj.id,
        "status": app_obj.status,
        "product": app_obj.product,
        "phone": app_obj.phone,
        "purpose": app_obj.purpose,
        "loan_amount_rub": app_obj.loan_amount_rub,
        "loan_term_months": app_obj.loan_term_months,
        "profitability_rub": app_obj.profitability_rub,
        "profitability_confirmed": app_obj.profitability_confirmed,
        "collateral": app_obj.collateral,
        "business_plan": app_obj.business_plan,
        "own_funds_rub": app_obj.own_funds_rub,
        "credit_rating": app_obj.credit_rating,
        "created_at": app_obj.created_at,
        "pipeline": app_obj.pipeline,
        "fallback": app_obj.fallback,
        "monthly_payment_rub": app_obj.monthly_payment_rub,
        "flow_rub": app_obj.flow_rub,
        "limit_rub": app_obj.limit_rub,
        "decision": app_obj.decision,
        "credit_id": app_obj.credit_id,
        "report": app_obj.report,
    }


def serialize_application_short(app_obj: db_models.Application) -> Dict[str, Any]:
    full = serialize_application(app_obj)
    full.pop("business_plan", None)
    full.pop("report", None)
    return full


def serialize_credit(credit_obj: db_models.Credit) -> Dict[str, Any]:
    return {
        "id": credit_obj.id,
        "application_id": credit_obj.application_id,
        "product": credit_obj.product,
        "status": credit_obj.status,
        "amount_rub": credit_obj.amount_rub,
        "loan_term_months": credit_obj.loan_term_months,
        "monthly_payment_rub": credit_obj.monthly_payment_rub,
        "purpose": credit_obj.purpose,
        "created_at": credit_obj.created_at,
    }


# ==========================================
# 1. АВТОРИЗАЦИЯ, SMS И ПРОФИЛЬ
# ==========================================

@app.post("/api/auth/sms/send", response_model=models.SmsSendResponse, tags=["Auth"])
def send_sms_code(data: models.SmsSendRequest):
    if data.phone not in ALLOWED_PHONES:
        raise HTTPException(status_code=400, detail={"error": PHONE_ERROR_MSG})

    return {
        "status": "ok",
        "code": "1234",
        "message": f"СМС с кодом отправлено на номер {data.phone}. Тестовый код: 1234"
    }


@app.post("/api/auth/session", response_model=models.SessionResponse, tags=["Auth"])
def create_session(data: models.SessionCreateRequest, db: Session = Depends(get_db)):
    if data.phone not in ALLOWED_PHONES:
        raise HTTPException(status_code=400, detail={"error": PHONE_ERROR_MSG})

    if data.code and data.code not in ["1234", "0000"]:
        raise HTTPException(status_code=400, detail={"error": "Неверный код из СМС."})

    user = db.query(db_models.User).filter(db_models.User.phone == data.phone).first()
    if not user:
        raise HTTPException(status_code=400, detail={"error": PHONE_ERROR_MSG})

    new_token = f"tok_{uuid.uuid4().hex[:12]}"
    user.token = new_token
    db.commit()
    db.refresh(user)

    return {"token": user.token, "user": serialize_user(user)}


@app.delete("/api/auth/session", status_code=204, tags=["Auth"])
def delete_session(user: db_models.User = Depends(get_current_user_required), db: Session = Depends(get_db)):
    user.token = f"revoked_{uuid.uuid4().hex[:8]}"
    db.commit()
    return None


@app.get("/api/me", response_model=models.UserProfileOut, tags=["Auth"])
def get_me(user: db_models.User = Depends(get_current_user_required), db: Session = Depends(get_db)):
    comp = db.query(db_models.Company).filter(db_models.Company.user_id == user.id).first()
    res = serialize_user(user)
    res["company"] = serialize_company(comp)
    return res


# ==========================================
# 2. ПРОДУКТЫ (ИЗ БАЗЫ ДАННЫХ)
# ==========================================

@app.get("/api/products", response_model=models.ProductsListResponse, tags=["Products"])
def get_products(db: Session = Depends(get_db)):
    # Читаем продукты напрямую из таблицы БД!
    db_products = db.query(db_models.Product).all()
    return {"products": [serialize_product_item(p) for p in db_products]}


@app.get("/api/products/{code}", response_model=models.ProductDetail, tags=["Products"])
def get_product_by_code(code: str, db: Session = Depends(get_db)):
    prod = db.query(db_models.Product).filter(db_models.Product.code == code).first()
    if not prod:
        raise HTTPException(status_code=404, detail={"error": "Неизвестный продукт."})
    return serialize_product_detail(prod)


# ==========================================
# СКОРИНГ И КРЕДИТЫ
# ==========================================

def execute_scoring_and_create_credit(app_obj: db_models.Application, db: Session):
    scoring_res = run_scoring_pipeline(
        product=app_obj.product,
        loan_amount_rub=app_obj.loan_amount_rub,
        loan_term_months=app_obj.loan_term_months,
        profitability_rub=app_obj.profitability_rub,
        business_plan=app_obj.business_plan,
        own_funds_rub=app_obj.own_funds_rub,
        credit_rating=app_obj.credit_rating,
        profitability_confirmed=app_obj.profitability_confirmed
    )

    app_obj.status = "scored"
    app_obj.pipeline = scoring_res["pipeline"]
    app_obj.fallback = scoring_res["fallback"]
    app_obj.monthly_payment_rub = scoring_res["monthly_payment_rub"]
    app_obj.flow_rub = scoring_res["flow_rub"]
    app_obj.limit_rub = scoring_res["limit_rub"]
    app_obj.decision = scoring_res["decision"]
    app_obj.report = scoring_res["report"]

    if app_obj.decision in ["approve", "reduced"] and app_obj.limit_rub and app_obj.limit_rub > 0:
        credit_payment = calculate_annuity_payment(app_obj.limit_rub, app_obj.loan_term_months)
        new_credit = db_models.Credit(
            application_id=app_obj.id,
            user_id=app_obj.user_id,
            product=app_obj.product,
            status="active",
            amount_rub=app_obj.limit_rub,
            loan_term_months=app_obj.loan_term_months,
            monthly_payment_rub=credit_payment,
            purpose=app_obj.purpose or ""
        )
        db.add(new_credit)
        db.flush()
        app_obj.credit_id = new_credit.id

    db.commit()
    db.refresh(app_obj)


# ==========================================
# 3. ЗАЯВКИ
# ==========================================

@app.post("/api/applications", status_code=201, response_model=Union[models.ApplicationAnonymousCreateResponse, models.ApplicationFullOut], tags=["Applications"])
def create_application(
    req: models.ApplicationCreateRequest,
    user: Optional[db_models.User] = Depends(get_current_user_optional),
    db: Session = Depends(get_db)
):
    if req.product in ["working_capital", "contract_execution"]:
        if not req.purpose:
            raise HTTPException(status_code=400, detail={"error": "Укажите цель финансирования."})
        if req.profitability_rub is None:
            raise HTTPException(status_code=400, detail={"error": "Укажите среднемесячную доходность."})
    elif req.product == "startup":
        if not req.business_plan or not req.business_plan.strip():
            raise HTTPException(status_code=400, detail={"error": "Для кредита на старт нужен бизнес-план."})

    # СЦЕНАРИЙ А: Со ссылки (в теле номер)
    if not user:
        if not req.phone:
            raise HTTPException(status_code=401, detail={"error": "Требуется авторизация или номер телефона в заявке."})

        if req.phone not in ALLOWED_PHONES:
            raise HTTPException(status_code=400, detail={"error": PHONE_ERROR_MSG})

        user = db.query(db_models.User).filter(db_models.User.phone == req.phone).first()
        if not user:
            raise HTTPException(status_code=400, detail={"error": PHONE_ERROR_MSG})

        new_token = f"tok_{uuid.uuid4().hex[:12]}"
        user.token = new_token
        db.commit()
        db.refresh(user)

        app_obj = db_models.Application(
            user_id=user.id,
            product=req.product,
            phone=req.phone,
            purpose=req.purpose or "",
            loan_amount_rub=req.loan_amount_rub,
            loan_term_months=req.loan_term_months,
            profitability_rub=req.profitability_rub,
            profitability_confirmed=req.profitability_confirmed or False,
            collateral=req.collateral or False,
            business_plan=req.business_plan or "",
            own_funds_rub=req.own_funds_rub,
            credit_rating=req.credit_rating
        )
        db.add(app_obj)
        db.flush()

        execute_scoring_and_create_credit(app_obj, db)

        return {
            "token": user.token,
            "user": serialize_user(user),
            "application": serialize_application(app_obj)
        }

    # СЦЕНАРИЙ Б: Из кабинета (черновик)
    app_obj = db_models.Application(
        user_id=user.id,
        product=req.product,
        phone=user.phone,
        purpose=req.purpose or "",
        loan_amount_rub=req.loan_amount_rub,
        loan_term_months=req.loan_term_months,
        profitability_rub=req.profitability_rub,
        profitability_confirmed=req.profitability_confirmed or False,
        collateral=req.collateral or False,
        business_plan=req.business_plan or "",
        own_funds_rub=req.own_funds_rub,
        credit_rating=req.credit_rating,
        status="draft"
    )
    db.add(app_obj)
    db.commit()
    db.refresh(app_obj)
    return serialize_application(app_obj)


@app.post("/api/applications/{app_id}/confirm", response_model=models.ApplicationFullOut, tags=["Applications"])
def confirm_application(
    app_id: str,
    req: models.ApplicationConfirmRequest,
    user: db_models.User = Depends(get_current_user_required),
    db: Session = Depends(get_db)
):
    app_obj = db.query(db_models.Application).filter(
        db_models.Application.id == app_id,
        db_models.Application.user_id == user.id
    ).first()

    if not app_obj:
        raise HTTPException(status_code=404, detail={"error": "Заявка не найдена."})

    if req.phone != user.phone:
        raise HTTPException(status_code=400, detail={"error": "Номер не совпал с номером сессии."})

    if app_obj.status == "scored":
        return serialize_application(app_obj)

    execute_scoring_and_create_credit(app_obj, db)
    return serialize_application(app_obj)


@app.get("/api/applications", response_model=models.ApplicationsListResponse, tags=["Applications"])
def get_user_applications(
    user: db_models.User = Depends(get_current_user_required),
    db: Session = Depends(get_db)
):
    apps = db.query(db_models.Application).filter(
        db_models.Application.user_id == user.id
    ).order_by(db_models.Application.created_at.desc()).all()
    return {"applications": [serialize_application_short(a) for a in apps]}


@app.get("/api/applications/{app_id}", response_model=models.ApplicationFullOut, tags=["Applications"])
def get_application_detail(
    app_id: str,
    user: db_models.User = Depends(get_current_user_required),
    db: Session = Depends(get_db)
):
    app_obj = db.query(db_models.Application).filter(
        db_models.Application.id == app_id,
        db_models.Application.user_id == user.id
    ).first()

    if not app_obj:
        raise HTTPException(status_code=404, detail={"error": "Заявка не найдена."})

    return serialize_application(app_obj)


# ==========================================
# 4. КРЕДИТЫ
# ==========================================

@app.get("/api/credits", response_model=models.CreditsListResponse, tags=["Credits"])
def get_user_credits(
    user: db_models.User = Depends(get_current_user_required),
    db: Session = Depends(get_db)
):
    credits = db.query(db_models.Credit).filter(
        db_models.Credit.user_id == user.id
    ).order_by(db_models.Credit.created_at.desc()).all()
    return {"credits": [serialize_credit(c) for c in credits]}


@app.get("/api/credits/{credit_id}", response_model=models.CreditDetailOut, tags=["Credits"])
def get_credit_detail(
    credit_id: str,
    user: db_models.User = Depends(get_current_user_required),
    db: Session = Depends(get_db)
):
    credit_obj = db.query(db_models.Credit).filter(
        db_models.Credit.id == credit_id,
        db_models.Credit.user_id == user.id
    ).first()

    if not credit_obj:
        raise HTTPException(status_code=404, detail={"error": "Кредит не найден."})

    schedule = [
        {"month": m, "payment_rub": credit_obj.monthly_payment_rub}
        for m in range(1, credit_obj.loan_term_months + 1)
    ]

    res = serialize_credit(credit_obj)
    res["schedule"] = schedule
    return res


# ==========================================
# 5. КАБИНЕТ
# ==========================================

@app.get("/api/cabinet", response_model=models.CabinetResponse, tags=["Cabinet"])
def get_cabinet(
    user: db_models.User = Depends(get_current_user_required),
    db: Session = Depends(get_db)
):
    company = db.query(db_models.Company).filter(db_models.Company.user_id == user.id).first()

    apps = db.query(db_models.Application).filter(
        db_models.Application.user_id == user.id
    ).order_by(db_models.Application.created_at.desc()).all()

    credits = db.query(db_models.Credit).filter(
        db_models.Credit.user_id == user.id
    ).order_by(db_models.Credit.created_at.desc()).all()

    # Берем продукты из базы данных
    db_products = db.query(db_models.Product).all()
    products_items = [serialize_product_item(p) for p in db_products]

    return {
        "user": serialize_user(user),
        "company": serialize_company(company),
        "products": products_items,
        "applications": [serialize_application_short(a) for a in apps],
        "credits": [serialize_credit(c) for c in credits]
    }