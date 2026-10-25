from typing import Optional, List, Dict, Any, Union
from pydantic import BaseModel, Field, field_validator
import re


# --- Базовая ошибка ---
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
    phone: str = Field(..., example="79001111111")

    @field_validator("phone")
    def check_phone(cls, v):
        return validate_phone_str(v)


class SmsSendResponse(BaseModel):
    status: str = Field(..., example="ok")
    code: str = Field(..., example="1234")
    message: str = Field(..., example="СМС отправлено. Код: 1234")


class SessionCreateRequest(BaseModel):
    phone: str = Field(..., example="79001111111")
    code: Optional[str] = Field(None, example="1234")

    @field_validator("phone")
    def check_phone(cls, v):
        return validate_phone_str(v)


# --- Профиль пользователя и компании ---
class CompanyOut(BaseModel):
    inn: str = Field(..., example="7728168971")
    ogrn: str = Field(..., example="1027700067328")
    name: str = Field(..., example="ООО «Альфа Технологии»")
    short_name: str = Field(..., example="Альфа Тех")
    status: str = Field(..., example="Действующее предприятие")
    registration_date: str = Field(..., example="2020-03-15")
    okved: str = Field(..., example="62.01 Разработка компьютерного ПО")
    monthly_revenue_rub: int = Field(..., example=3500000)
    credit_rating: int = Field(..., example=820)
    rating_grade: str = Field(..., example="Высокая надежность (A+)")
    preapproved_limit_rub: int = Field(..., example=2000000)


class UserOut(BaseModel):
    id: str = Field(..., example="user-1")
    phone: str = Field(..., example="79001111111")
    full_name: str = Field(..., example="Иванов Алексей Сергеевич")
    role: str = Field(..., example="Генеральный директор")
    email: str = Field(..., example="alex.ivanov@alfa-tech.ru")


class UserProfileOut(UserOut):
    company: Optional[CompanyOut] = None


class SessionResponse(BaseModel):
    token: str = Field(..., example="tok_123456789abc")
    user: UserOut


# --- Продукты (Расширенные!) ---
class ProductItem(BaseModel):
    code: str = Field(..., example="working_capital")
    title: str = Field(..., example="Оборотный Экспресс")
    description: str = Field(..., example="Быстрое пополнение оборотных средств без залога")
    badge: str = Field(..., example="Без залога")
    rate_pct: float = Field(..., example=20.0)
    min_amount_rub: int = Field(..., example=300000)
    max_amount_rub: int = Field(..., example=2000000)
    min_term_months: int = Field(..., example=3)
    max_term_months: int = Field(..., example=36)


class ProductsListResponse(BaseModel):
    products: List[ProductItem]


class ProductDetail(ProductItem):
    fields: List[str] = Field(..., example=["loan_amount_rub", "loan_term_months", "purpose"])


# --- Заявка (Создание) ---
class ApplicationCreateRequest(BaseModel):
    product: str = Field(..., pattern="^(working_capital|startup|contract_execution)$", example="working_capital")
    loan_amount_rub: int = Field(..., gt=0, example=800000)
    loan_term_months: int = Field(..., ge=1, le=360, example=12)
    phone: Optional[str] = Field(None, example="79001111111")
    purpose: Optional[str] = Field("", example="пополнение оборота")
    profitability_rub: Optional[int] = Field(None, example=160000)
    profitability_confirmed: Optional[bool] = Field(False, example=True)
    collateral: Optional[bool] = Field(False, example=False)
    business_plan: Optional[str] = Field("", example="")
    own_funds_rub: Optional[int] = Field(None, example=100000)
    credit_rating: Optional[int] = Field(None, example=500)

    @field_validator("phone")
    def check_phone(cls, v):
        return validate_phone_str(v)


class ApplicationConfirmRequest(BaseModel):
    phone: str = Field(..., example="79001111111")
    code: Optional[str] = Field(None, example="1234")

    @field_validator("phone")
    def check_phone(cls, v):
        return validate_phone_str(v)


# --- Отчет скоринга ---
class ScoringReport(BaseModel):
    flow_basis: str = Field(..., example="form")
    risks: List[str] = Field(default_factory=list, example=[])
    quote: str = Field("", example="")


# --- Заявка (Полная) ---
class ApplicationFullOut(BaseModel):
    id: str = Field(..., example="app-1")
    status: str = Field(..., example="scored")
    product: str = Field(..., example="working_capital")
    phone: str = Field(..., example="79001111111")
    purpose: str = Field("", example="пополнение оборота")
    loan_amount_rub: int = Field(..., example=800000)
    loan_term_months: int = Field(..., example=12)
    profitability_rub: Optional[int] = Field(None, example=160000)
    profitability_confirmed: bool = Field(False, example=True)
    collateral: bool = Field(False, example=False)
    business_plan: str = Field("", example="")
    own_funds_rub: Optional[int] = Field(None, example=100000)
    credit_rating: Optional[int] = Field(None, example=500)
    created_at: str = Field(..., example="2026-10-24T15:00:00+00:00")
    pipeline: Optional[str] = Field(None, example="math")
    fallback: bool = Field(False, example=True)
    monthly_payment_rub: Optional[int] = Field(None, example=74108)
    flow_rub: Optional[int] = Field(None, example=160000)
    limit_rub: Optional[int] = Field(None, example=800000)
    decision: Optional[str] = Field(None, example="approve")
    credit_id: Optional[str] = Field(None, example="credit-1")
    report: Optional[ScoringReport] = None


# --- Заявка (Короткая карточка) ---
class ApplicationShortOut(BaseModel):
    id: str = Field(..., example="app-1")
    status: str = Field(..., example="scored")
    product: str = Field(..., example="working_capital")
    phone: str = Field(..., example="79001111111")
    purpose: str = Field("", example="пополнение оборота")
    loan_amount_rub: int = Field(..., example=800000)
    loan_term_months: int = Field(..., example=12)
    profitability_rub: Optional[int] = Field(None, example=160000)
    profitability_confirmed: bool = Field(False, example=True)
    collateral: bool = Field(False, example=False)
    own_funds_rub: Optional[int] = Field(None, example=100000)
    credit_rating: Optional[int] = Field(None, example=500)
    created_at: str = Field(..., example="2026-10-24T15:00:00+00:00")
    pipeline: Optional[str] = Field(None, example="math")
    fallback: bool = Field(False, example=True)
    monthly_payment_rub: Optional[int] = Field(None, example=74108)
    flow_rub: Optional[int] = Field(None, example=160000)
    limit_rub: Optional[int] = Field(None, example=800000)
    decision: Optional[str] = Field(None, example="approve")
    credit_id: Optional[str] = Field(None, example="credit-1")


class ApplicationsListResponse(BaseModel):
    applications: List[ApplicationShortOut]


class ApplicationAnonymousCreateResponse(BaseModel):
    token: str
    user: UserOut
    application: ApplicationFullOut


# --- Кредиты ---
class ScheduleItem(BaseModel):
    month: int = Field(..., example=1)
    payment_rub: int = Field(..., example=74108)


class CreditShortOut(BaseModel):
    id: str = Field(..., example="credit-1")
    application_id: str = Field(..., example="app-1")
    product: str = Field(..., example="working_capital")
    status: str = Field(..., example="active")
    amount_rub: int = Field(..., example=800000)
    loan_term_months: int = Field(..., example=12)
    monthly_payment_rub: int = Field(..., example=74108)
    purpose: str = Field("", example="пополнение оборота")
    created_at: str = Field(..., example="2026-10-24T15:00:00+00:00")


class CreditsListResponse(BaseModel):
    credits: List[CreditShortOut]


class CreditDetailOut(CreditShortOut):
    schedule: List[ScheduleItem]


# --- Кабинет ---
class CabinetResponse(BaseModel):
    user: UserOut
    company: Optional[CompanyOut] = None
    products: List[ProductItem]
    applications: List[ApplicationShortOut]
    credits: List[CreditShortOut]