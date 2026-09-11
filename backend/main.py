import logging
import os
import sys
from contextlib import asynccontextmanager
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from core.config import get_settings
from core.redis_store import RedisStore

# Ensure the app directory is in the Python path for imports
app_dir = os.path.dirname(os.path.abspath(__file__))
if app_dir not in sys.path:
    sys.path.insert(0, app_dir)

# Load environment variables
dotenv_path = os.path.join(os.path.dirname(__file__), '.env')
if os.path.exists(dotenv_path):
    load_dotenv(dotenv_path)
else:
    load_dotenv()

# Log presence of critical API keys at startup (do not print full keys)
try:
    import logging as _logging
    _logger = _logging.getLogger(__name__)
    gemini_present = bool(os.environ.get("GEMINI_API_KEY", ""))
    groq_present = bool(os.environ.get("GROQ_API_KEY", ""))
    _logger.info("GEMINI_API_KEY present=%s, GROQ_API_KEY present=%s", gemini_present, groq_present)
except Exception:
    pass

# Import API routers
from routes import api, auth

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(" Parallel AI Backend Started")
    if settings.database_url:
        from core.postgres_store import PostgresStore
        try:
            PostgresStore(settings.database_url).ensure_schema()
            logger.info("PostgreSQL SaaS migration applied")
        except Exception:
            logger.exception("PostgreSQL migration failed; refusing to start without durable auth storage")
            raise
    # Verify faster-whisper model is cached locally — NO network requests
    try:
        import os as _os
        model_name = settings.whisper_model
        cache_dir = _os.path.join(_os.path.expanduser("~"), ".cache", "huggingface", "hub")
        model_found = False
        for root, dirs, files in _os.walk(cache_dir):
            if any(f.endswith(".bin") or f.endswith(".ct2") for f in files):
                model_found = True
                break
        if model_found:
            logger.info("Faster-whisper model '%s' found in local cache at %s — ready for offline STT.", model_name, cache_dir)
        else:
            logger.warning(
                "Faster-whisper model '%s' NOT found in local cache (%s). "
                "Audio STT will fail until the model is cached. "
                "Run: python -c \"from faster_whisper import WhisperModel; WhisperModel('%s', device='cpu', compute_type='int8')\" to download.",
                model_name, cache_dir, model_name,
            )
    except Exception as e:
        logger.warning("Could not verify faster-whisper model cache: %s", e)

    yield

    logger.info(" Parallel AI Backend Stopped")


# Create FastAPI app
app = FastAPI(
    title="Parallel AI",
    description="Autonomous Multimodal Agent Platform API",
    version=settings.version,
    lifespan=lifespan,
)

# ─────────────────────────────────────────────────────────────
# Security Headers Middleware
# ─────────────────────────────────────────────────────────────
@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    try:
        response: Response = await call_next(request)
    except Exception as exc:
        if "ClientDisconnected" in type(exc).__name__:
            logger.info("Client disconnected during request %s %s", request.method, request.url.path)
            return Response(status_code=499)
        raise
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["X-XSS-Protection"] = "1; mode=block"

    # HSTS in production or when SSL is enabled
    if settings.is_production or settings.cookie_secure or request.url.scheme == "https":
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains; preload"

    return response


# ─────────────────────────────────────────────────────────────
# Consistent JSON Error Handlers (No HTML errors returned)
# ─────────────────────────────────────────────────────────────
@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    headers = getattr(exc, "headers", None)
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "status": "error",
            "detail": exc.detail,
            "code": exc.status_code,
        },
        headers=headers,
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    errors = exc.errors()
    first_msg = errors[0].get("msg") if errors else "Invalid request data"
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "status": "error",
            "detail": f"Validation error: {first_msg}",
            "errors": errors,
            "code": 422,
        },
    )


@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled server exception: %s", exc)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "status": "error",
            "detail": "An internal server error occurred.",
            "code": 500,
        },
    )


# CORS Configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.frontend_origins),
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-CSRF-Token", "X-XSRF-Token", "X-Requested-With"],
    expose_headers=["Content-Type", "Set-Cookie"],
)

# Register API Routes
app.include_router(
    auth.router,
    prefix="/api/auth",
    tags=["Auth"]
)
app.include_router(
    api.router,
    prefix="/api",
    tags=["API"]
)

# Root Endpoint
@app.get("/")
async def root():
    return {
        "message": "Parallel AI Backend Running",
        "version": settings.version,
        "status": "healthy"
    }

# Health Check Endpoint
@app.get("/health")
async def health_check():
    return {
        "status": "ok",
        "service": "Parallel AI Backend",
        "version": settings.version
    }


@app.get("/health/redis")
async def redis_health_check():
    try:
        RedisStore().ping()
        return {"status": "ok", "redis": "ok", "version": settings.version}
    except Exception as exc:
        logger.warning("Redis health check failed: %s", exc)
        return {"status": "degraded", "redis": "unavailable", "version": settings.version}



# Run Server
if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", 8000))

    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=port,
        reload=True
    )