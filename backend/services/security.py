"""Request guards for the document-analysis product."""
import hmac
import os

from fastapi import Header, HTTPException, status
from slowapi import Limiter
from slowapi.util import get_remote_address

API_KEY = os.getenv("API_KEY")
LEGACY_API_KEY_ENABLED = os.getenv("LEGACY_API_KEY_ENABLED", "false").lower() == "true"
ADMIN_API_KEY = os.getenv("ADMIN_API_KEY")
N8N_WEBHOOK_API_KEY = os.getenv("N8N_WEBHOOK_API_KEY")

RATE_LIMIT_QUERY = os.getenv("RATE_LIMIT_QUERY", "20/minute")
RATE_LIMIT_UPLOAD = os.getenv("RATE_LIMIT_UPLOAD", "10/minute")
RATE_LIMIT_SUPERVISOR = os.getenv("RATE_LIMIT_SUPERVISOR", "5/minute")
RATE_LIMIT_PANEL = os.getenv("RATE_LIMIT_PANEL", "5/minute")
RATE_LIMIT_RESEARCH = os.getenv("RATE_LIMIT_RESEARCH", "8/minute")
RATE_LIMIT_AUDIT = os.getenv("RATE_LIMIT_AUDIT", "15/minute")
RATE_LIMIT_INTELLIGENCE = os.getenv("RATE_LIMIT_INTELLIGENCE", "4/minute")
MAX_UPLOAD_SIZE_MB = int(os.getenv("MAX_UPLOAD_SIZE_MB", "20"))
MAX_PDF_PAGES = int(os.getenv("MAX_PDF_PAGES", "250"))
MAX_DOCUMENTS_PER_USER = int(os.getenv("MAX_DOCUMENTS_PER_USER", "100"))
MAX_STORAGE_MB_PER_USER = int(os.getenv("MAX_STORAGE_MB_PER_USER", "500"))

limiter = Limiter(key_func=get_remote_address)


async def require_api_key(x_api_key: str | None = Header(default=None)):
    # This was used by the old browser-only build. It is opt-in now: the
    # authenticated browser uses Better Auth HttpOnly sessions instead, and a
    # VITE_* API key would be public by definition.
    if not LEGACY_API_KEY_ENABLED or not API_KEY:
        return
    if not x_api_key or not hmac.compare_digest(x_api_key, API_KEY):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid API key. Send it as the X-API-Key header.",
        )


async def require_admin_api_key(x_admin_api_key: str | None = Header(default=None)):
    """Protect operational telemetry and evaluation data from normal users."""
    if not ADMIN_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin diagnostics are disabled.",
        )
    if not x_admin_api_key or not hmac.compare_digest(x_admin_api_key, ADMIN_API_KEY):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid admin credential.",
        )


async def require_n8n_webhook_api_key(x_n8n_api_key: str | None = Header(default=None)):
    if not N8N_WEBHOOK_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="n8n integration is disabled. Set N8N_WEBHOOK_API_KEY to enable it.",
        )
    if not x_n8n_api_key or not hmac.compare_digest(x_n8n_api_key, N8N_WEBHOOK_API_KEY):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid X-N8N-API-Key header.",
        )
