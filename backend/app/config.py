import os
from urllib.parse import urlparse

from dotenv import load_dotenv

load_dotenv()


def _csv(name: str) -> list[str]:
    return [item.strip() for item in os.getenv(name, "").split(",") if item.strip()]


class Settings:
    service_name = os.getenv("SERVICE_NAME", "credit-cabinet")
    app_env = os.getenv("APP_ENV", "local")
    database_url = os.getenv("DATABASE_URL", "sqlite:///./sql_app.db")
    redis_url = os.getenv("REDIS_URL", "")
    cors_origins = _csv("CORS_ORIGINS")
    advisor_llm_url = os.getenv("ADVISOR_LLM_URL", "").strip()

    @property
    def database_host(self) -> str:
        if self.database_url.startswith("sqlite"):
            return "sqlite"
        return urlparse(self.database_url).hostname or "unknown"


settings = Settings()
