from typing import Optional, List, Dict, Any, Union
from pydantic import BaseModel, Field, field_validator
import re


# --- Базовая ошибка по контракту ---
class ErrorResponse(BaseModel):
    error: str


# --- Валидация телефона ---
def validate_phone_str(phone: Optional[str]) -> Optional[str]:
    if phone is None:
        return None
    if not re.fullmatch(r"^\d{10,15}$", phone):
        raise ValueError("Номер должен состоять из 10–15 цифр без знака + и пробелов")
    return phone


# --- Авторизация и SMS ---
class SmsSendRequest(BaseModel):
    phone: str

    @field_validator("phone")
    def check_phone(cls, v):
        return validate_phone_str(v)


class SmsSendResponse(BaseModel):
    status: str
    code: str
    message: str


class SessionCreateRequest(BaseModel):
    phone: str
    code: Optional[str] = None

    @field_validator("phone")
    def check_phone(cls, v):
        return validate_phone_str(v)


# --- Профиль пользователя и компании ---
class CompanyOut(BaseModel):
    inn: str
    ogrn: str
    name: str
    short_name: str
    status: str
    registration_date: str
    okved: str
    monthly_revenue_rub: int
    credit_rating: int
    rating_grade: str
    preapproved_limit_rub: int


class UserOut(BaseModel):
    id: str
    phone: str
    full_name: Optional[str] = "Предприниматель"
    role: Optional[str] = "Руководитель"
    email: Optional[str] = ""


class SessionResponse(BaseModel):
    token: str
    user: UserOut


# --- Продукты ---
class ProductItem(BaseModel):
    code: str
    title: str


class ProductDetail(BaseModel):
    code: str
    title: str
    fields: List[str]


# --- Заявка (Создание) ---
class ApplicationCreateRequest(BaseModel):
    product: str = Field(..., pattern="^(working_capital|startup)$")
    loan_amount_rub: int = Field(..., gt=0)
    loan_term_months: int = Field(..., ge=1, le=360)
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


class ApplicationConfirmRequest(BaseModel):
    phone: str
    code: Optional[str] = None

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


# --- Заявка (Короткая карточка) ---
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


# --- Кабинет (С компанией!) ---
class CabinetResponse(BaseModel):
    user: UserOut
    company: Optional[CompanyOut] = None
    products: List[ProductItem]
    applications: List[ApplicationShortOut]
    credits: List[CreditShortOut]