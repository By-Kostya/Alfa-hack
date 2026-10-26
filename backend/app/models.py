import re
from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, Field, field_validator, model_validator

from app.catalog import PRODUCT_CODES, offer_error


# --- Базовая ошибка по контракту ---
class ErrorResponse(BaseModel):
    error: str


# --- Валидация телефона ---
def validate_phone_str(phone: Optional[str]) -> Optional[str]:
    if phone is None:
        return None
    if not isinstance(phone, str) or not re.fullmatch(r"^7\d{10}$", phone):
        raise ValueError("Номер должен состоять из 11 цифр и начинаться с 7.")
    return phone


def require_whole_number(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("Укажите целое число без букв и пробелов.")
    return value


# --- Авторизация ---
class SessionCreateRequest(BaseModel):
    phone: str

    @field_validator("phone")
    def check_phone(cls, v):
        return validate_phone_str(v)


class UserOut(BaseModel):
    id: str
    phone: str


class SessionResponse(BaseModel):
    token: str
    user: UserOut


# --- Продукты ---
class ProductItem(BaseModel):
    code: str
    title: str
    annual_rate_pct: int
    min_amount_rub: int
    max_amount_rub: int
    min_term_months: int
    max_term_months: int


class ProductDetail(ProductItem):
    fields: List[str]


# --- Заявка (Создание) ---
class ApplicationCreateRequest(BaseModel):
    product: str
    loan_amount_rub: int = Field(..., gt=0)
    loan_term_months: int = Field(..., ge=1)
    phone: Optional[str] = None
    purpose: Optional[str] = ""
    profitability_rub: Optional[int] = None
    profitability_confirmed: Optional[bool] = False
    collateral: Optional[bool] = False
    business_plan: Optional[str] = ""
    own_funds_rub: Optional[int] = None
    credit_rating: Optional[int] = None

    @field_validator("phone")
    def check_phone(cls, v):
        return validate_phone_str(v)

    @field_validator(
        "loan_amount_rub",
        "loan_term_months",
        "profitability_rub",
        "own_funds_rub",
        "credit_rating",
        mode="before",
    )
    def check_whole_number(cls, v):
        return require_whole_number(v)

    @field_validator("product")
    def check_product(cls, v):
        if v not in PRODUCT_CODES:
            raise ValueError("Неизвестный продукт.")
        return v

    @field_validator("own_funds_rub")
    def check_own_funds(cls, v):
        if v is not None and v < 0:
            raise ValueError("Собственные средства не могут быть отрицательными.")
        return v

    @field_validator("credit_rating")
    def check_rating(cls, v):
        if v is not None and not 0 <= v <= 1000:
            raise ValueError("Рейтинг должен быть от 0 до 1000.")
        return v

    @model_validator(mode="after")
    def check_offer(self):
        message = offer_error(self.product, self.loan_amount_rub, self.loan_term_months)
        if message:
            raise ValueError(message)
        return self


class ApplicationConfirmRequest(BaseModel):
    phone: str

    @field_validator("phone")
    def check_phone(cls, v):
        return validate_phone_str(v)


# --- Отчет скоринга ---
class ScoringReport(BaseModel):
    flow_basis: str
    risks: List[str]
    quote: str


# --- Заявка (Полная) ---
class ApplicationFullOut(BaseModel):
    id: str
    status: str
    product: str
    phone: str
    purpose: str
    loan_amount_rub: int
    loan_term_months: int
    profitability_rub: Optional[int]
    profitability_confirmed: bool
    collateral: bool
    business_plan: str
    own_funds_rub: Optional[int]
    credit_rating: Optional[int]
    created_at: str
    pipeline: Optional[str]
    fallback: bool
    monthly_payment_rub: Optional[int]
    flow_rub: Optional[int]
    limit_rub: Optional[int]
    decision: Optional[str]
    credit_id: Optional[str]
    report: Optional[ScoringReport]


# --- Заявка (Короткая карточка без business_plan и report) ---
class ApplicationShortOut(BaseModel):
    id: str
    status: str
    product: str
    phone: str
    purpose: str
    loan_amount_rub: int
    loan_term_months: int
    profitability_rub: Optional[int]
    profitability_confirmed: bool
    collateral: bool
    own_funds_rub: Optional[int]
    credit_rating: Optional[int]
    created_at: str
    pipeline: Optional[str]
    fallback: bool
    monthly_payment_rub: Optional[int]
    flow_rub: Optional[int]
    limit_rub: Optional[int]
    decision: Optional[str]
    credit_id: Optional[str]


# --- Кредиты ---
class ScheduleItem(BaseModel):
    month: int
    payment_rub: int


class CreditShortOut(BaseModel):
    id: str
    application_id: str
    product: str
    status: str
    amount_rub: int
    loan_term_months: int
    monthly_payment_rub: int
    purpose: str
    created_at: str


class CreditDetailOut(CreditShortOut):
    schedule: List[ScheduleItem]


# --- Кабинет ---
class CabinetResponse(BaseModel):
    user: UserOut
    products: List[ProductItem]
    applications: List[ApplicationShortOut]
    credits: List[CreditShortOut]


class AdvisorTurnRequest(BaseModel):
    goal: Optional[str] = None
    amount_rub: Optional[int] = None
    term_months: Optional[int] = None
    profitability_rub: Optional[int] = None
    purpose: Optional[str] = None
    business_plan: Optional[str] = None
    phone: Optional[str] = None
    text: str = ""

    @field_validator("amount_rub", "term_months", "profitability_rub", mode="before")
    def check_whole_number(cls, value):
        return require_whole_number(value)

    @field_validator("text", "purpose", "business_plan")
    def check_text(cls, value):
        if value is None:
            return None
        if not isinstance(value, str):
            raise ValueError("Напишите сообщение текстом.")
        return value.strip()[:500]

    @field_validator("phone")
    def check_phone(cls, value):
        return validate_phone_str(value)