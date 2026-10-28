"""Reject unsafe browser requests and bound bodies before multipart parsing."""

import asyncio
import tempfile

from services.security import MAX_UPLOAD_SIZE_MB
from services.problems import problem_response

CSRF_HEADER = b"x-csrf-protection"
CSRF_VALUE = b"nexus-v1"
UPLOAD_PATHS = {"/upload", "/integrations/n8n/documents"}


class RequestSecurityMiddleware:
    def __init__(self, app, allowed_origins, auth_required, upload_limit=None):
        self.app = app
        self.origins = {origin.encode() for origin in allowed_origins}
        self.auth_required = auth_required
        self.upload_limit = upload_limit or (MAX_UPLOAD_SIZE_MB + 1) * 1024 * 1024
        self.intakes = asyncio.Semaphore(8)
        self.observers = asyncio.Semaphore(16)

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] not in {
            "POST",
            "PUT",
            "PATCH",
            "DELETE",
        }:
            return await self.app(scope, receive, send)
        headers = dict(scope.get("headers", []))
        origin = headers.get(b"origin")
        integration = scope["path"].startswith("/integrations/n8n/")
        browser = (
            origin is not None or b"cookie" in headers or b"sec-fetch-site" in headers
        )
        if origin is not None and origin not in self.origins:
            return await self.reject(
                scope, receive, send, 403, "Untrusted request origin."
            )
        # The integration uses a server-held key, not browser session cookies.
        # Only anonymous development CLI requests may omit this header.
        if (
            not integration
            and (self.auth_required or browser)
            and headers.get(CSRF_HEADER) != CSRF_VALUE
        ):
            return await self.reject(
                scope, receive, send, 403, "CSRF protection header is required."
            )
        limit = self.upload_limit if scope["path"] in UPLOAD_PATHS else 256 * 1024
        length = headers.get(b"content-length")
        if length is not None:
            try:
                if int(length) < 0:
                    raise ValueError
                if int(length) > limit:
                    return await self.reject(
                        scope, receive, send, 413, "Request body is too large."
                    )
            except ValueError:
                return await self.reject(
                    scope, receive, send, 400, "Invalid content length."
                )
        if self.intakes.locked():
            return await self.reject(
                scope, receive, send, 429, "Too many incoming requests. Retry shortly."
            )
        observer = scope["path"].startswith("/documents/") and scope["path"].endswith(
            ("/intelligence/stream", "/intelligence/run")
        )
        if observer and self.observers.locked():
            return await self.reject(
                scope,
                receive,
                send,
                429,
                "Too many analysis observers. Check saved activity shortly.",
            )
        if observer:
            await self.observers.acquire()
        await self.intakes.acquire()
        intake_held = True
        try:
            # Spooled input is strictly bounded, even without Content-Length.
            # The downstream multipart parser never sees an oversized body.
            with tempfile.SpooledTemporaryFile(max_size=1024 * 1024) as body:
                total = 0
                try:
                    async with asyncio.timeout(60):
                        while True:
                            message = await receive()
                            if message["type"] == "http.disconnect":
                                return
                            data = message.get("body", b"")
                            total += len(data)
                            if total > limit:
                                return await self.reject(
                                    scope,
                                    receive,
                                    send,
                                    413,
                                    "Request body is too large.",
                                )
                            await asyncio.to_thread(body.write, data)
                            if not message.get("more_body", False):
                                break
                except TimeoutError:
                    return await self.reject(
                        scope, receive, send, 408, "Request body timed out."
                    )
                await asyncio.to_thread(body.seek, 0)
                remaining = total

                async def replay():
                    nonlocal remaining
                    if remaining <= 0:
                        # After the final body, preserve downstream disconnect
                        # detection (particularly for streaming responses).
                        return await receive()
                    data = await asyncio.to_thread(body.read, min(64 * 1024, remaining))
                    remaining -= len(data)
                    return {
                        "type": "http.request",
                        "body": data,
                        "more_body": remaining > 0,
                    }

                # An empty body still needs one final http.request event.
                if total == 0:
                    delivered = False

                    async def replay():
                        nonlocal delivered
                        if not delivered:
                            delivered = True
                            return {
                                "type": "http.request",
                                "body": b"",
                                "more_body": False,
                            }
                        return await receive()

                # Analysis is a durable job; a slow browser observer must not
                # occupy the ingress slots needed by n8n stage callbacks.
                if observer:
                    self.intakes.release()
                    intake_held = False
                await self.app(scope, replay, send)
        finally:
            if intake_held:
                self.intakes.release()
            if observer:
                self.observers.release()

    @staticmethod
    async def reject(scope, receive, send, code, detail):
        response = problem_response(code, detail)
        await response(scope, receive, send)
