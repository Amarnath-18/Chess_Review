"""Request-size limit and response security headers."""
from __future__ import annotations

from collections.abc import Callable

from starlette.types import ASGIApp, Message, Receive, Scope, Send


class BodyTooLarge(Exception):
    pass


class BodySizeLimitMiddleware:
    """Refuse oversized request bodies before they are read.

    A declared Content-Length over the limit gets a clean 413. A body that is streamed without a
    length is cut off as soon as it passes the limit, so memory use stays bounded either way.
    """

    def __init__(self, app: ASGIApp, max_bytes: Callable[[], int]) -> None:
        self.app = app
        self._limit = max_bytes  # read on every request so it can be changed without a rebuild

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        max_bytes = self._limit()
        declared = dict(scope["headers"]).get(b"content-length", b"")
        if declared.isdigit() and int(declared) > max_bytes:
            await self._reject(send)
            return

        received = 0
        started = False

        async def limited_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > max_bytes:
                    raise BodyTooLarge
            return message

        async def tracking_send(message: Message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, tracking_send)
        except BodyTooLarge:
            if not started:
                await self._reject(send)

    async def _reject(self, send: Send) -> None:
        body = b'{"detail":"The request is too large."}'
        await send(
            {
                "type": "http.response.start",
                "status": 413,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode()),
                    (b"connection", b"close"),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})


SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cross-Origin-Opener-Policy": "same-origin",
    # Responses hold one person's games: never let a shared cache keep them.
    "Cache-Control": "no-store",
}
