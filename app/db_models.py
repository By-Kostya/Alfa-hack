import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, Integer, Boolean, ForeignKey, JSON
from app.database import Base


def generate_uuid(prefix: str = "") -> str:
    return f"{prefix}{uuid.uuid4().hex[:8]}"


def get_current_iso_time() -> str:
    # ISO-8601 со смещением (требование контракта)
    return datetime.now(timezone.utc).isoformat()


class User(Base):
    __tablename__ = "users"

    id = Column(String, primary_key=True, default=lambda: generate_uuid("user-"))
    phone = Column(String, unique=True, index=True, nullable=False)
    token = Column(String, unique=True, index=True, nullable=False)
    created_at = Column(String, default=get_current_iso_time)


class Application(Base):
    __tablename__ = "applications"

    id = Column(String, primary_key=True, default=lambda: generate_uuid("app-"))
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    status = Column(String, default="draft")  # draft / scored
    product = Column(String, nullable=False)  # working_capital / startup
    phone = Column(String, nullable=False)
    purpose = Column(String, default="")
    loan_amount_rub = Column(Integer, nullable=False)
    loan_term_months = Column(Integer, nullable=False)
    profitability_rub = Column(Integer, nullable=True)
    profitability_confirmed = Column(Boolean, default=False)
    collateral = Column(Boolean, default=False)
    business_plan = Column(String, default="")
    own_funds_rub = Column(Integer, nullable=True)
    credit_rating = Column(Integer, nullable=True)
    created_at = Column(String, default=get_current_iso_time)

    # Результаты скоринга (до скоринга null)
    pipeline = Column(String, nullable=True)
    fallback = Column(Boolean, default=False)
    monthly_payment_rub = Column(Integer, nullable=True)
    flow_rub = Column(Integer, nullable=True)
    limit_rub = Column(Integer, nullable=True)
    decision = Column(String, nullable=True)  # approve / reduced / reject / unknown
    credit_id = Column(String, nullable=True)
    report = Column(JSON, nullable=True)


class Credit(Base):
    __tablename__ = "credits"

    id = Column(String, primary_key=True, default=lambda: generate_uuid("credit-"))
    application_id = Column(String, ForeignKey("applications.id"), nullable=False)
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    product = Column(String, nullable=False)
    status = Column(String, default="active")
    amount_rub = Column(Integer, nullable=False)
    loan_term_months = Column(Integer, nullable=False)
    monthly_payment_rub = Column(Integer, nullable=False)
    purpose = Column(String, default="")
    created_at = Column(String, default=get_current_iso_time)