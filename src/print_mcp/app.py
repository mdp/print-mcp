from __future__ import annotations

import contextlib
import hmac
import json

import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route
from starlette.types import ASGIApp, Receive, Scope, Send

from .config import Settings, get_settings
from .printer import CupsPrinter
from .server import create_mcp


class SecurityMiddleware:
    def __init__(self, app: ASGIApp, token: str, allowed_origins: frozenset[str]):
        self.app = app
        self.token = token.encode()
        self.allowed_origins = allowed_origins

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not scope.get("path", "").startswith("/mcp"):
            await self.app(scope, receive, send)
            return
        headers = {key.lower(): value for key, value in scope.get("headers", [])}
        origin = headers.get(b"origin")
        if origin is not None:
            normalized = origin.decode("latin-1").rstrip("/")
            if normalized not in self.allowed_origins:
                await self._reject(send, 403, "origin is not allowed")
                return
        authorization = headers.get(b"authorization", b"")
        scheme, separator, supplied = authorization.partition(b" ")
        valid = (
            separator == b" "
            and scheme.lower() == b"bearer"
            and hmac.compare_digest(supplied, self.token)
        )
        if not valid:
            await self._reject(send, 401, "missing or invalid bearer token", authenticate=True)
            return
        await self.app(scope, receive, send)

    @staticmethod
    async def _reject(send: Send, status: int, detail: str, authenticate: bool = False) -> None:
        body = json.dumps({"error": detail}).encode()
        headers = [
            (b"content-type", b"application/json"),
            (b"content-length", str(len(body)).encode()),
        ]
        if authenticate:
            headers.append((b"www-authenticate", b"Bearer"))
        await send({"type": "http.response.start", "status": status, "headers": headers})
        await send({"type": "http.response.body", "body": body})


def create_app(settings: Settings | None = None) -> ASGIApp:
    settings = settings or get_settings()
    printer = CupsPrinter(settings)
    mcp = create_mcp(settings, printer)

    async def health(_: Request) -> JSONResponse:
        return JSONResponse({"status": "ok"})

    async def ready(_: Request) -> JSONResponse:
        printers = await printer.list_printers()
        ready_printers = sum(item.available for item in printers)
        status = 200 if printers else 503
        return JSONResponse(
            {
                "status": "ready" if printers else "not-ready",
                "printers": len(printers),
                "available": ready_printers,
            },
            status_code=status,
        )

    @contextlib.asynccontextmanager
    async def lifespan(_: Starlette):
        async with mcp.session_manager.run():
            yield

    application = Starlette(
        routes=[
            Route("/healthz", health, methods=["GET"]),
            Route("/readyz", ready, methods=["GET"]),
            Mount("/", app=mcp.streamable_http_app()),
        ],
        lifespan=lifespan,
    )
    return SecurityMiddleware(application, settings.mcp_bearer_token, settings.allowed_origins)


def main() -> None:
    settings = get_settings()
    uvicorn.run(create_app(settings), host=settings.host, port=settings.port, proxy_headers=True)


if __name__ == "__main__":
    main()
