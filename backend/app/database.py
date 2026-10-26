from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import declarative_base, sessionmaker

from app.config import settings

connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def ping_db() -> None:
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))


def ensure_user_columns() -> None:
    inspector = inspect(engine)
    if "users" not in inspector.get_table_names():
        return
    existing = {column["name"] for column in inspector.get_columns("users")}
    json_type = "JSON" if engine.dialect.name == "postgresql" else "TEXT"
    additions = {
        "full_name": "VARCHAR",
        "role": "VARCHAR",
        "email": "VARCHAR",
        "company": json_type,
    }
    missing = [name for name in additions if name not in existing]
    if not missing:
        return
    with engine.begin() as connection:
        for name in missing:
            connection.execute(text(f"ALTER TABLE users ADD COLUMN {name} {additions[name]}"))
