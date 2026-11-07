"""Environment configuration. Read once at import; secrets never have defaults."""
import os
from dataclasses import dataclass


def _flag(name: str, default: str = "0") -> bool:
    return os.getenv(name, default) == "1"


@dataclass(frozen=True)
class Settings:
    env: str = os.getenv("ORRFIN_ENV", "development")
    database_url: str = os.getenv("DATABASE_URL", "")
    secret_key: str = os.getenv("ORRFIN_SECRET_KEY", "")
    pool_size: int = int(os.getenv("ORRFIN_POOL_SIZE", "10"))

    s3_endpoint_url: str = os.getenv("S3_ENDPOINT_URL", "")
    s3_access_key: str = os.getenv("S3_ACCESS_KEY", "")
    s3_secret_key: str = os.getenv("S3_SECRET_KEY", "")
    s3_bucket: str = os.getenv("S3_BUCKET", "orrfin-documents")

    public_app_url: str = os.getenv("PUBLIC_APP_URL", "http://localhost:8080").rstrip("/")
    cookie_secure: bool = _flag("COOKIE_SECURE")
    allow_signup: bool = _flag("ORRFIN_ALLOW_SIGNUP", "1")
    session_hours: int = int(os.getenv("ORRFIN_SESSION_HOURS", "12"))

    allow_mock_erp: bool = _flag("ORRFIN_ALLOW_MOCK_ERP")
    mock_erp_url: str = os.getenv("MOCK_ERP_URL", "http://mock-erp:9100")

    ocr_enabled: bool = _flag("ORRFIN_OCR_ENABLED", "1")

    ai_provider: str = os.getenv("ORRFIN_AI_PROVIDER", "anthropic")
    ai_model: str = os.getenv("ORRFIN_AI_MODEL", "")
    anthropic_api_key: str = os.getenv("ANTHROPIC_API_KEY", "")
    groq_api_key: str = os.getenv("GROQ_API_KEY", "")
    groq_model: str = os.getenv("GROQ_MODEL", "")

    tinyfish_api_key: str = os.getenv("TINYFISH_API_KEY", "")
    hindsight_api_key: str = os.getenv("HINDSIGHT_API_KEY", "")
    hindsight_api_url: str = os.getenv("HINDSIGHT_API_URL", "https://api.hindsight.vectorize.io")

    max_upload_bytes: int = 25 * 1024 * 1024


settings = Settings()
