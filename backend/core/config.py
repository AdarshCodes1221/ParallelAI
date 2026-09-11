import os
from dataclasses import dataclass
from functools import lru_cache


@dataclass(frozen=True)
class Settings:
    version: str = os.getenv("APP_VERSION", "3.0.0")
    redis_url: str = os.getenv("REDIS_URL", "redis://localhost:6379")
    database_url: str = os.getenv("DATABASE_URL", "")
    s3_endpoint_url: str = os.getenv("S3_ENDPOINT_URL", "")
    s3_bucket: str = os.getenv("S3_BUCKET", "")
    s3_region: str = os.getenv("S3_REGION", "us-east-1")
    s3_access_key: str = os.getenv("S3_ACCESS_KEY", os.getenv("AWS_ACCESS_KEY_ID", ""))
    s3_secret_key: str = os.getenv("S3_SECRET_KEY", os.getenv("AWS_SECRET_ACCESS_KEY", ""))
    email_provider: str = os.getenv("EMAIL_PROVIDER", "console").lower()
    email_from: str = os.getenv("EMAIL_FROM", "no-reply@example.com")
    frontend_url: str = os.getenv("FRONTEND_URL", "http://localhost:5173").rstrip("/")
    password_reset_base_url: str = os.getenv(
        "PASSWORD_RESET_BASE_URL",
        f"{os.getenv('FRONTEND_URL', 'http://localhost:5173').rstrip('/')}/reset-password",
    )
    smtp_host: str = os.getenv("SMTP_HOST", "")
    smtp_port: int = int(os.getenv("SMTP_PORT", "587"))
    smtp_username: str = os.getenv("SMTP_USERNAME", "")
    smtp_password: str = os.getenv("SMTP_PASSWORD", "")
    smtp_tls: bool = os.getenv("SMTP_TLS", "true").lower() in ("1", "true", "yes")
    environment: str = os.getenv("ENVIRONMENT", os.getenv("ENV", "development")).lower()
    document_storage_path: str = os.getenv("DOCUMENT_STORAGE_PATH", os.path.join(os.path.dirname(os.path.dirname(__file__)), "storage"))
    frontend_origins: tuple[str, ...] = tuple(origin.strip() for origin in os.getenv("FRONTEND_ORIGINS", "http://localhost:5173").split(",") if origin.strip())
    max_upload_size_mb: int = int(os.getenv("MAX_UPLOAD_SIZE_MB", "50"))
    embedding_provider: str = os.getenv("EMBEDDING_PROVIDER", "ollama")
    embedding_model: str = os.getenv("EMBEDDING_MODEL", "nomic-embed-text")
    embedding_dimension: int = int(os.getenv("EMBEDDING_DIMENSION", "768"))
    primary_llm_provider: str = os.getenv("PRIMARY_LLM_PROVIDER", "ollama")
    fallback_llm_provider: str = os.getenv("FALLBACK_LLM_PROVIDER", "gemini")
    llm_mode: str = os.getenv("LLM_MODE", "offline").lower()
    ollama_url: str = os.getenv("OLLAMA_URL", "http://host.docker.internal:11434")
    ollama_llm_model: str = os.getenv("OLLAMA_LLM_MODEL", "llama3.2:3b")
    whisper_model: str = os.getenv("WHISPER_MODEL", "base")
    whisper_device: str = os.getenv("WHISPER_DEVICE", "cpu")
    whisper_compute_type: str = os.getenv("WHISPER_COMPUTE_TYPE", "int8")
    session_cookie_name: str = os.getenv("SESSION_COOKIE_NAME", "session_token")
    csrf_cookie_name: str = os.getenv("CSRF_COOKIE_NAME", "csrf_token")
    session_ttl_seconds: int = int(os.getenv("SESSION_TTL_SECONDS", str(7 * 24 * 3600)))
    reset_token_ttl_seconds: int = int(os.getenv("RESET_TOKEN_TTL_SECONDS", "3600"))
    cookie_secure: bool = os.getenv("COOKIE_SECURE", "false").lower() in ("1", "true", "yes")
    cookie_samesite: str = os.getenv("COOKIE_SAMESITE", "lax").lower()
    auth_rate_limit_max: int = int(os.getenv("AUTH_RATE_LIMIT_MAX", "30"))
    auth_rate_limit_window: int = int(os.getenv("AUTH_RATE_WINDOW_SECONDS", os.getenv("AUTH_RATE_LIMIT_WINDOW", "60")))
    auth_login_rate_limit: int = int(os.getenv("AUTH_LOGIN_RATE_LIMIT", "10"))
    auth_signup_rate_limit: int = int(os.getenv("AUTH_SIGNUP_RATE_LIMIT", "10"))
    auth_forgot_password_rate_limit: int = int(os.getenv("AUTH_FORGOT_PASSWORD_RATE_LIMIT", "5"))
    auth_reset_password_rate_limit: int = int(os.getenv("AUTH_RESET_PASSWORD_RATE_LIMIT", "5"))
    is_production: bool = environment in ("production", "prod")
    query_expansion_enabled: bool = os.getenv("QUERY_EXPANSION_ENABLED", "true").lower() in ("true", "1", "yes")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
