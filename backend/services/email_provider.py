from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage

from core.config import get_settings

logger = logging.getLogger(__name__)


class EmailProvider:
    """Provider boundary for password-reset delivery (SMTP for real sending, Console for local dev)."""

    def __init__(self):
        self.settings = get_settings()

    def send_password_reset(self, recipient: str, reset_url: str) -> None:
        """Deliver password reset email containing the single-use reset URL.
        
        In development (when EMAIL_PROVIDER=console or SMTP is not set), outputs
        the reset URL clearly to the terminal for developer convenience.
        In production or when EMAIL_PROVIDER=smtp, securely transmits via SMTP.
        """
        settings = get_settings()
        provider = settings.email_provider.lower()

        if provider == "console" or not settings.smtp_host:
            if settings.is_production and provider != "smtp":
                logger.error("Production email provider must be configured with SMTP settings.")
                raise RuntimeError("Production email delivery failed: SMTP is not configured.")
            
            # Development-only logging for local manual flow testing
            logger.info(
                "\n%s\n[DEV ONLY] Password Reset Link for %s\nReset URL: %s\n%s",
                "=" * 72,
                recipient,
                reset_url,
                "=" * 72,
            )
            return

        if provider == "smtp":
            message = EmailMessage()
            message["Subject"] = "Reset your Parallel AI password"
            message["From"] = settings.email_from
            message["To"] = recipient

            # Plaintext body
            plain_body = (
                "You requested a password reset for your Parallel AI account.\n\n"
                f"Reset Password:\n{reset_url}\n\n"
                "This link is valid for a limited time and can only be used once.\n"
                "If you did not request a password reset, you can safely ignore this email.\n"
            )
            message.set_content(plain_body)

            # HTML rich version
            html_body = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background-color: #020617; color: #f8fafc; padding: 24px;">
  <div style="max-width: 520px; margin: 0 auto; background: #0f172a; border: 1px solid #1e293b; border-radius: 12px; padding: 32px;">
    <h2 style="color: #38bdf8; margin-top: 0;">Parallel AI Password Reset</h2>
    <p style="color: #94a3b8; font-size: 14px; line-height: 1.6;">
      You requested a password reset for your Parallel AI account.
    </p>
    <div style="text-align: center; margin: 28px 0;">
      <a href="{reset_url}" style="display: inline-block; background: linear-gradient(135deg, #06b6d4, #3b82f6); color: #020617; text-decoration: none; font-weight: 600; font-size: 14px; padding: 12px 24px; border-radius: 8px;">
        Reset Password
      </a>
    </div>
    <p style="color: #64748b; font-size: 12px; line-height: 1.5;">
      Reset Password:<br>
      <a href="{reset_url}" style="color: #38bdf8; word-break: break-all;">{reset_url}</a>
    </p>
    <hr style="border: 0; border-top: 1px solid #1e293b; margin: 24px 0;">
    <p style="color: #475569; font-size: 11px;">
      This link is single-use and expires shortly. If you did not make this request, you can ignore this email.
    </p>
  </div>
</body>
</html>"""
            message.add_alternative(html_body, subtype="html")

            with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as smtp:
                if settings.smtp_tls:
                    smtp.starttls()
                if settings.smtp_username and settings.smtp_password:
                    smtp.login(settings.smtp_username, settings.smtp_password)
                smtp.send_message(message)
                logger.info("Password reset email sent via SMTP to %s", recipient)