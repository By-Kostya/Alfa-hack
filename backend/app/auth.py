from typing import Optional

from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.db_models import User


def _bearer_token(authorization: Optional[str]) -> Optional[str]:
    if authorization is None:
        return None
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail={"error": "Требуется авторизация."})
    token = authorization[7:].strip()
    if not token:
        raise HTTPException(status_code=401, detail={"error": "Требуется авторизация."})
    return token


def _user_for_token(token: str, db: Session) -> User:
    user = db.query(User).filter(User.token == token).first()
    if not user:
        raise HTTPException(status_code=401, detail={"error": "Недействительный или просроченный токен."})
    return user


def get_current_user_required(
    authorization: Optional[str] = Header(default=None),
    db: Session = Depends(get_db),
) -> User:
    token = _bearer_token(authorization)
    if token is None:
        raise HTTPException(status_code=401, detail={"error": "Требуется авторизация."})
    return _user_for_token(token, db)


def get_current_user_optional(
    authorization: Optional[str] = Header(default=None),
    db: Session = Depends(get_db),
) -> Optional[User]:
    token = _bearer_token(authorization)
    if token is None:
        return None
    return _user_for_token(token, db)
