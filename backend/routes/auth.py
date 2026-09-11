import logging
import secrets
from typing import Any
from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, status
from pydantic import BaseModel, EmailStr

from core.config import get_settings
from services.auth_service import AuthService
from services.email_provider import EmailProvider

logger = logging.getLogger(__name__)
router = APIRouter()
auth_service = AuthService()
email_provider = EmailProvider()
settings = get_settings()


class SignupRequest(BaseModel):
    email: str
    password: str
    name: str | None = None


class LoginRequest(BaseModel):
    email: str
    password: str


class ForgotPasswordRequest(BaseModel):
    email: str


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


def _get_client_ip(request: Request) -> str:
    """Extract client IP from request headers or socket."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "127.0.0.1"


def _set_auth_cookies(response: Response, token: str) -> str:
    """Attach secure HttpOnly session cookie and readable CSRF cookie."""
    csrf_token = secrets.token_urlsafe(32)
    # 1. Server session cookie (HttpOnly)
    response.set_cookie(
        key=settings.session_cookie_name,
        value=token,
        max_age=settings.session_ttl_seconds,
        httponly=True,
        secure=settings.cookie_secure or settings.is_production,
        samesite=settings.cookie_samesite,
        path="/",
    )
    # 2. CSRF cookie (Readable by frontend JS for Double Submit Cookie pattern)
    response.set_cookie(
        key=settings.csrf_cookie_name,
        value=csrf_token,
        max_age=settings.session_ttl_seconds,
        httponly=False,
        secure=settings.cookie_secure or settings.is_production,
        samesite=settings.cookie_samesite,
        path="/",
    )
    return csrf_token


def _clear_auth_cookies(response: Response) -> None:
    """Delete session and CSRF cookies."""
    response.delete_cookie(key=settings.session_cookie_name, path="/")
    response.delete_cookie(key=settings.csrf_cookie_name, path="/")


async def get_current_user_optional(
    request: Request,
    authorization: str | None = Header(default=None),
) -> dict[str, Any] | None:
    """Extract authenticated user from either HttpOnly session cookie or Bearer header."""
    token: str | None = None

    # 1. Check Bearer token header
    if authorization:
        parts = authorization.split()
        if len(parts) == 2 and parts[0].lower() == "bearer":
            token = parts[1]

    # 2. Fallback to HttpOnly session cookie
    if not token:
        token = request.cookies.get(settings.session_cookie_name)

    if not token:
        return None

    return auth_service.get_user_by_token(token)


async def get_current_user(
    request: Request,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    """Strict authentication dependency — raises 401 if unauthenticated."""
    user = await get_current_user_optional(request, authorization)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication credentials required or session expired.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


async def verify_csrf(request: Request) -> None:
    """
    CSRF verification for mutating requests authenticated via cookies.
    Bearer-authenticated requests are inherently immune to ambient-cookie CSRF.
    """
    # Safe methods do not mutate state
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return

    # If request uses Authorization Bearer header, ambient cookie CSRF does not apply
    auth_header = request.headers.get("authorization", "")
    if auth_header.lower().startswith("bearer "):
        return

    # If authenticated via cookie, require matching X-CSRF-Token or X-Requested-With
    cookie_token = request.cookies.get(settings.csrf_cookie_name)
    header_token = request.headers.get("x-csrf-token") or request.headers.get("x-xsrf-token")

    # If no session cookie is present, allow request through to standard auth check
    if not request.cookies.get(settings.session_cookie_name):
        return

    # If cookie auth is active, validate Double-Submit CSRF token
    if not cookie_token or not header_token or not secrets.compare_digest(cookie_token, header_token):
        # Relax for development/local non-browser tools if X-Requested-With header is present
        if request.headers.get("x-requested-with") == "XMLHttpRequest":
            return
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="CSRF validation failed. Missing or mismatched CSRF token.",
        )


@router.post("/signup")
async def signup(req: SignupRequest, request: Request, response: Response):
    """Register a new user account without establishing an authenticated session."""
    ip = _get_client_ip(request)
    allowed, retry_after = auth_service.check_rate_limit(
        f"signup:{ip}",
        limit=settings.auth_signup_rate_limit,
        window_seconds=settings.auth_rate_limit_window,
    )
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Too many signup attempts. Please try again in {retry_after} seconds.",
        )

    user_agent = request.headers.get("user-agent", "")
    user, _, error = auth_service.signup(
        email=req.email,
        password=req.password,
        name=req.name,
        user_agent=user_agent,
        ip_address=ip,
    )
    if error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=error)

    # CRITICAL: DO NOT set session cookies or return session tokens!
    return {
        "status": "ok",
        "message": "Account created successfully. Please sign in.",
        "user": user,
    }


@router.post("/login")
async def login(req: LoginRequest, request: Request, response: Response):
    """Authenticate user credentials and issue secure session cookies."""
    ip = _get_client_ip(request)
    allowed, retry_after = auth_service.check_rate_limit(
        f"login:{ip}",
        limit=settings.auth_login_rate_limit,
        window_seconds=settings.auth_rate_limit_window,
    )
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Too many login attempts. Please try again in {retry_after} seconds.",
        )

    user_agent = request.headers.get("user-agent", "")
    user, token, error = auth_service.login(
        email=req.email,
        password=req.password,
        user_agent=user_agent,
        ip_address=ip,
    )
    if error:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=error)

    csrf_token = _set_auth_cookies(response, token)
    return {
        "status": "ok",
        "user": user,
        "csrf_token": csrf_token,
    }


@router.get("/me")
async def get_me(request: Request, current_user: dict[str, Any] = Depends(get_current_user)):
    """Get current authenticated user identity and refresh CSRF token."""
    csrf_token = request.cookies.get(settings.csrf_cookie_name) or secrets.token_urlsafe(32)
    return {
        "status": "ok",
        "user": current_user,
        "csrf_token": csrf_token,
    }


@router.post("/forgot-password")
async def forgot_password(req: ForgotPasswordRequest, request: Request):
    """Generate a short-lived, one-time password reset token sent via email provider.
    
    NEVER returns the reset token in the response body or logs raw tokens.
    Always returns uniform success response to prevent user enumeration.
    """
    ip = _get_client_ip(request)
    allowed, retry_after = auth_service.check_rate_limit(
        f"forgot:{ip}",
        limit=settings.auth_forgot_password_rate_limit,
        window_seconds=settings.auth_rate_limit_window,
    )
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Too many requests. Please try again in {retry_after} seconds.",
        )

    clean_email = req.email.strip().lower()
    token, generic_msg = auth_service.create_reset_token(clean_email)

    if token:
        reset_url = f"{settings.password_reset_base_url}?token={token}"
        try:
            email_provider.send_password_reset(clean_email, reset_url)
        except Exception:
            logger.exception("Password reset delivery encountered an error")

    # Always return identical response - NEVER leak reset_token
    return {
        "status": "ok",
        "message": generic_msg,
    }


@router.post("/reset-password")
async def reset_password(req: ResetPasswordRequest, request: Request):
    """Reset password using one-time token and revoke all existing sessions."""
    ip = _get_client_ip(request)
    allowed, retry_after = auth_service.check_rate_limit(
        f"reset:{ip}",
        limit=settings.auth_reset_password_rate_limit,
        window_seconds=settings.auth_rate_limit_window,
    )
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Too many reset attempts. Please try again in {retry_after} seconds.",
        )

    success, msg = auth_service.reset_password(req.token, req.new_password)
    if not success:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=msg)

    return {
        "status": "ok",
        "message": msg,
    }


@router.post("/change-password")
async def change_password(
    req: ChangePasswordRequest,
    current_user: dict[str, Any] = Depends(get_current_user),
    _csrf: None = Depends(verify_csrf),
):
    """Change password for an authenticated user."""
    success, msg = auth_service.change_password(
        user_id=current_user["id"],
        current_password=req.current_password,
        new_password=req.new_password,
    )
    if not success:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=msg)

    return {
        "status": "ok",
        "message": msg,
    }


@router.post("/logout")
async def logout(
    request: Request,
    response: Response,
    authorization: str | None = Header(default=None),
    _csrf: None = Depends(verify_csrf),
):
    """Revoke session token and clear HttpOnly cookies."""
    token: str | None = None
    if authorization:
        parts = authorization.split()
        if len(parts) == 2 and parts[0].lower() == "bearer":
            token = parts[1]

    if not token:
        token = request.cookies.get(settings.session_cookie_name)

    if token:
        auth_service.logout(token)

    _clear_auth_cookies(response)
    return {"status": "ok", "message": "Logged out successfully"}
