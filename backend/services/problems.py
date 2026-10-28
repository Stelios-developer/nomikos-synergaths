"""RFC 9457 errors. Never serialize validation inputs, exception text or URLs."""
from http import HTTPStatus
import re

from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse

from services.observability import get_request_id, new_request_id


def correlation_id(candidate: str | None) -> str:
    return candidate if candidate and re.fullmatch(r"[A-Za-z0-9._-]{1,64}", candidate) else new_request_id()


def problem_response(status: int, detail: str, *, code: str | None = None, headers=None, invalid_params=None,
                     retryable: bool | None = None, uncertain: bool | None = None):
    request_id = get_request_id()
    request_id = correlation_id(None) if request_id == "no-request" else request_id
    codes = {401: "AUTH_REQUIRED", 403: "FORBIDDEN", 409: "CONFLICT", 422: "INVALID_REQUEST", 429: "RATE_LIMITED", 503: "DEPENDENCY_UNAVAILABLE"}
    body = {
        "type": "about:blank", "title": HTTPStatus(status).phrase,
        "status": status, "detail": detail,
        "instance": f"urn:request:{request_id}", "request_id": request_id,
        "code": code or codes.get(status, f"HTTP_{status}"),
        "retryable": status in {408, 429, 502, 503, 504} if retryable is None else retryable,
    }
    if invalid_params is not None:
        body["invalid_params"] = invalid_params
    if uncertain is not None:
        body['uncertain'] = uncertain
    return JSONResponse(body, status_code=status, media_type="application/problem+json", headers={
        **(headers or {}), "Cache-Control": "no-store", "X-Request-ID": request_id,
        "X-Content-Type-Options": "nosniff",
    })


def install_problem_handlers(app):
    @app.exception_handler(HTTPException)
    async def http_error(_request, exc):
        detail = exc.detail if isinstance(exc.detail, str) else "The request could not be completed."
        return problem_response(exc.status_code, detail, headers=exc.headers)

    @app.exception_handler(RequestValidationError)
    async def validation_error(_request, exc):
        # Pydantic's default errors include raw `input`; that can be a document,
        # answer or secret. Only structural field locations/types are returned.
        invalid = [{"name": ".".join(map(str, item["loc"])), "reason": item["type"]} for item in exc.errors()]
        return problem_response(422, "The request contains invalid fields.", invalid_params=invalid)
