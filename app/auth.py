from typing import Optional
from fastapi import Header, HTTPException, Depends
from sqlalchemy.orm import Session
from app.database import get_db
from app.db_models import User


def get_current_user_required(
    authorization: Optional[str] = Header(default=None),
    db: Session = Depends(get_db)
) -> User:
    """Обязательная авторизация (для защищенных эндпоинтов)"""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=401,
            detail={"error": "Требуется авторизация (Bearer токен)."}
        )

    token = authorization.split(" ")[1]
    user = db.query(User).filter(User.token == token).first()
    if not user:
        raise HTTPException(
            status_code=401,
            detail={"error": "Недействительный или просроченный токен."}
        )
    return user


def get_current_user_optional(
    authorization: Optional[str] = Header(default=None),
    db: Session = Depends(get_db)
) -> Optional[User]:
    """Опциональная авторизация"""
    if not authorization or not authorization.startswith("Bearer "):
        return None

    token = authorization.split(" ")[1]
    return db.query(User).filter(User.token == token).first()