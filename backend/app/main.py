import logging
import uuid
from contextlib import asynccontextmanager
from typing import Any, Dict, Optional

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app import db_models, models
from app.auth import get_current_user_optional, get_current_user_required
from app.cache import cache_get, cache_set, redis_ready
from app.catalog import PRODUCT_LIST, product_by_code, public_product
from app.config import settings
from app.database import Base, SessionLocal, engine, ensure_user_columns, get_db, ping_db
from app.demo import DEMO_PHONES, public_profiles, seed_demo
from app.scoring.calculator import ANNUAL_RATE, calculate_annuity_payment
from app.scoring.pipeline import run_scoring_pipeline

logger = logging.getLogger("credit-cabinet")


@asynccontextmanager
async def lifespan(_: FastAPI):
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s %(message)s")
    ping_db()
    Base.metadata.create_all(bind=engine)
    ensure_user_columns()
    db = SessionLocal()
    try:
        seed_demo(db)
    finally:
        db.close()
    logger.warning(
        "%s env=%s db_host=%s redis=%s",
        settings.service_name,
        settings.app_env,
        settings.database_host,
        "ok" if redis_ready() else "down",
    )
    yield


app = FastAPI(title="Alfa Credit Core API", version="1.0.0", lifespan=lifespan)

if settings.cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["Authorization", "Content-Type"],
    )


_FIELD_LABELS = {
    "phone": "Номер",
    "loan_amount_rub": "Сумма",
    "loan_term_months": "Срок",
    "profitability_rub": "Доходность",
    "purpose": "Цель",
    "business_plan": "Бизнес-план",
    "own_funds_rub": "Собственные средства",
    "credit_rating": "Рейтинг",
}


def _validation_message(error: Dict[str, Any]) -> str:
    msg = str(error.get("msg") or "Проверьте введённые данные.")
    if msg.startswith("Value error, "):
        msg = msg[len("Value error, "):]
    kind = str(error.get("type") or "")
    loc = error.get("loc") or ()
    field = loc[-1] if loc else ""
    label = _FIELD_LABELS.get(str(field), "Поле")
    if kind in {"json_invalid", "json_type"} or "JSON decode" in msg:
        return "Не удалось прочитать запрос."
    if kind in {"int_parsing", "int_type", "int_from_float", "float_parsing"} or "valid integer" in msg:
        return f"{label}: укажите целое число."
    if kind == "greater_than":
        return f"{label}: укажите число больше нуля."
    if kind == "greater_than_equal":
        return f"{label}: укажите срок от 1 месяца."
    if kind == "missing" or msg == "Field required":
        return "Заполните обязательные поля."
    return msg


# --- Единый формат ошибок: {"error": "..."} по контракту ---
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    errors = exc.errors()
    return JSONResponse(status_code=400, content={"error": _validation_message(errors[0] if errors else {})})


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


def serialize_user(user: db_models.User) -> Dict[str, Any]:
    return {
        "id": user.id,
        "phone": user.phone,
        "full_name": user.full_name,
        "role": user.role,
        "email": user.email,
        "company": user.company,
    }


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
    user = _demo_user(db, data.phone)
    user.token = f"tok_{uuid.uuid4().hex[:12]}"
    db.commit()
    db.refresh(user)
    return {"token": user.token, "user": serialize_user(user)}


@app.delete("/api/auth/session", status_code=204)
def delete_session(user: db_models.User = Depends(get_current_user_required), db: Session = Depends(get_db)):
    user.token = f"revoked_{uuid.uuid4().hex[:8]}"
    db.commit()
    return None


@app.get("/api/me")
def get_me(user: db_models.User = Depends(get_current_user_required)):
    return serialize_user(user)


# ==========================================
# 2. ПРОДУКТЫ
# ==========================================

def _demo_user(db: Session, phone: str) -> db_models.User:
    if phone not in DEMO_PHONES:
        raise HTTPException(status_code=401, detail={"error": "Номер не найден."})
    user = db.query(db_models.User).filter(db_models.User.phone == phone).first()
    if user is None:
        raise HTTPException(status_code=401, detail={"error": "Номер не найден."})
    return user


@app.get("/api/demo-profiles")
def get_demo_profiles():
    return {"profiles": public_profiles()}


@app.get("/health")
def health():
    try:
        ping_db()
    except Exception:
        logger.warning("health db probe failed")
        return JSONResponse(status_code=503, content={"status": "error", "reason": "db"})
    return {"status": "ok"}


@app.get("/api/products")
def get_products():
    cached = cache_get("products:v3:list")
    if cached is not None:
        return cached
    payload = {"products": PRODUCT_LIST}
    cache_set("products:v3:list", payload)
    return payload


@app.get("/api/products/{code}")
def get_product_by_code(code: str):
    cache_key = f"products:v3:{code}"
    cached = cache_get(cache_key)
    if cached is not None:
        return cached
    spec = product_by_code(code)
    payload = None if spec is None else public_product(spec, with_fields=True)
    if payload is None:
        raise HTTPException(status_code=404, detail={"error": "Неизвестный продукт."})
    cache_set(cache_key, payload)
    return payload


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
        spec = product_by_code(app_obj.product)
        credit_payment = calculate_annuity_payment(
            app_obj.limit_rub,
            app_obj.loan_term_months,
            spec["annual_rate"] if spec else ANNUAL_RATE,
        )
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


def _require_complete_application(
    product: str,
    purpose: Optional[str],
    profitability_rub: Optional[int],
    business_plan: Optional[str],
) -> None:
    spec = product_by_code(product)
    if spec is None:
        raise HTTPException(status_code=400, detail={"error": "Неизвестный продукт."})
    fields = spec["fields"]
    if "purpose" in fields and not (purpose or "").strip():
        raise HTTPException(status_code=400, detail={"error": "Укажите цель кредита."})
    if "profitability_rub" in fields and profitability_rub is None:
        raise HTTPException(status_code=400, detail={"error": "Укажите доходность."})
    if "business_plan" in fields and not (business_plan or "").strip():
        raise HTTPException(status_code=400, detail={"error": "Добавьте бизнес-план."})


# ==========================================
# 3. ЗАЯВКИ
# ==========================================

@app.post("/api/applications", status_code=201)
def create_application(
    req: models.ApplicationCreateRequest,
    user: Optional[db_models.User] = Depends(get_current_user_optional),
    db: Session = Depends(get_db)
):
    _require_complete_application(
        product=req.product,
        purpose=req.purpose,
        profitability_rub=req.profitability_rub,
        business_plan=req.business_plan,
    )

    # СЦЕНАРИЙ А: Со ссылки (в теле номер)
    if not user:
        if not req.phone:
            raise HTTPException(status_code=401, detail={"error": "Требуется авторизация или номер телефона в заявке."})

        user = _demo_user(db, req.phone)
        user.token = f"tok_{uuid.uuid4().hex[:12]}"
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

    _require_complete_application(
        product=app_obj.product,
        purpose=app_obj.purpose,
        profitability_rub=app_obj.profitability_rub,
        business_plan=app_obj.business_plan,
    )
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
        "user": serialize_user(user),
        "products": PRODUCT_LIST,
        "applications": [serialize_application_short(a) for a in apps],
        "credits": [serialize_credit(c) for c in credits]
    }