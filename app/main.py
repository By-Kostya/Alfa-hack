import uuid
from typing import Optional, List, Dict, Any
from fastapi import FastAPI, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from sqlalchemy.orm import Session

from app.database import engine, get_db, Base
from app import db_models
from app import models
from app.auth import get_current_user_required, get_current_user_optional
from app.scoring.pipeline import run_scoring_pipeline
from app.scoring.calculator import calculate_annuity_payment

# Создаем таблицы в БД при старте
Base.metadata.create_all(bind=engine)

app = FastAPI(title="Alfa Credit Core API", version="1.0.0")


# --- Единый формат ошибок: {"error": "..."} по контракту ---
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


# --- Сериализаторы SQLAlchemy в dict ---
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
# 1. АВТОРИЗАЦИЯ И СЕССИИ
# ==========================================

@app.post("/api/auth/session")
def create_session(data: models.SessionCreateRequest, db: Session = Depends(get_db)):
    user = db.query(db_models.User).filter(db_models.User.phone == data.phone).first()
    new_token = f"tok_{uuid.uuid4().hex[:12]}"

    if not user:
        user = db_models.User(phone=data.phone, token=new_token)
        db.add(user)
    else:
        user.token = new_token

    db.commit()
    db.refresh(user)
    return {"token": user.token, "user": {"id": user.id, "phone": user.phone}}


@app.delete("/api/auth/session", status_code=204)
def delete_session(user: db_models.User = Depends(get_current_user_required), db: Session = Depends(get_db)):
    user.token = f"revoked_{uuid.uuid4().hex[:8]}"
    db.commit()
    return None


@app.get("/api/me")
def get_me(user: db_models.User = Depends(get_current_user_required)):
    return {"id": user.id, "phone": user.phone}


# ==========================================
# 2. ПРОДУКТЫ
# ==========================================

PRODUCTS_INFO = [
    {"code": "working_capital", "title": "Оборотный кредит"},
    {"code": "startup", "title": "Кредит на старт"}
]


@app.get("/api/products")
def get_products():
    return {"products": PRODUCTS_INFO}


@app.get("/api/products/{code}")
def get_product_by_code(code: str):
    if code == "working_capital":
        return {
            "code": "working_capital",
            "title": "Оборотный кредит",
            "fields": [
                "loan_amount_rub", "loan_term_months", "purpose",
                "profitability_rub", "profitability_confirmed", "collateral"
            ]
        }
    elif code == "startup":
        return {
            "code": "startup",
            "title": "Кредит на старт",
            "fields": ["loan_amount_rub", "loan_term_months", "business_plan"]
        }
    raise HTTPException(status_code=404, detail={"error": "Неизвестный продукт."})


# ==========================================
# ЛОГИКА СКОРИНГА И СОЗДАНИЯ КРЕДИТА
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

@app.post("/api/applications", status_code=201)
def create_application(
    req: models.ApplicationCreateRequest,
    user: Optional[db_models.User] = Depends(get_current_user_optional),
    db: Session = Depends(get_db)
):
    if req.product == "working_capital":
        if not req.purpose:
            raise HTTPException(status_code=400, detail={"error": "Для оборотного кредита укажите цель."})
        if req.profitability_rub is None:
            raise HTTPException(status_code=400, detail={"error": "Для оборотного кредита укажите доходность."})
    elif req.product == "startup":
        if not req.business_plan or not req.business_plan.strip():
            raise HTTPException(status_code=400, detail={"error": "Для кредита на старт нужен бизнес-план."})

    # СЦЕНАРИЙ А: Со ссылки (в теле номер)
    if not user:
        if not req.phone:
            raise HTTPException(status_code=401, detail={"error": "Требуется авторизация или номер телефона в заявке."})

        user = db.query(db_models.User).filter(db_models.User.phone == req.phone).first()
        new_token = f"tok_{uuid.uuid4().hex[:12]}"
        if not user:
            user = db_models.User(phone=req.phone, token=new_token)
            db.add(user)
        else:
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
            "user": {"id": user.id, "phone": user.phone},
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


@app.post("/api/applications/{app_id}/confirm")
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


@app.get("/api/applications")
def get_user_applications(
    user: db_models.User = Depends(get_current_user_required),
    db: Session = Depends(get_db)
):
    apps = db.query(db_models.Application).filter(
        db_models.Application.user_id == user.id
    ).order_by(db_models.Application.created_at.desc()).all()
    return {"applications": [serialize_application_short(a) for a in apps]}


@app.get("/api/applications/{app_id}")
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

@app.get("/api/credits")
def get_user_credits(
    user: db_models.User = Depends(get_current_user_required),
    db: Session = Depends(get_db)
):
    credits = db.query(db_models.Credit).filter(
        db_models.Credit.user_id == user.id
    ).order_by(db_models.Credit.created_at.desc()).all()
    return {"credits": [serialize_credit(c) for c in credits]}


@app.get("/api/credits/{credit_id}")
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

@app.get("/api/cabinet")
def get_cabinet(
    user: db_models.User = Depends(get_current_user_required),
    db: Session = Depends(get_db)
):
    apps = db.query(db_models.Application).filter(
        db_models.Application.user_id == user.id
    ).order_by(db_models.Application.created_at.desc()).all()

    credits = db.query(db_models.Credit).filter(
        db_models.Credit.user_id == user.id
    ).order_by(db_models.Credit.created_at.desc()).all()

    return {
        "user": {"id": user.id, "phone": user.phone},
        "products": PRODUCTS_INFO,
        "applications": [serialize_application_short(a) for a in apps],
        "credits": [serialize_credit(c) for c in credits]
    }