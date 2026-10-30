from pathlib import Path

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import FileResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

INDEX = "index.html"
IMMUTABLE = "public, max-age=31536000, immutable"
NO_CACHE = "no-cache"
SHORT_CACHE = "public, max-age=3600"
RESERVED_PREFIXES = ("api/", "webhook/")
RESERVED_PATHS = {"api", "webhook", "healthz", "readyz"}

CONTENT_SECURITY_POLICY = "; ".join(
    (
        "default-src 'self'",
        "script-src 'self' https://st.max.ru",
        "style-src 'self' 'unsafe-inline'",
        "img-src 'self' data: blob: https://*.max.ru https://*.oneme.ru",
        "font-src 'self' data:",
        "connect-src 'self' https://*.max.ru",
        "frame-ancestors 'self' https://max.ru https://*.max.ru https://*.oneme.ru",
        "base-uri 'self'",
        "form-action 'self'",
        "object-src 'none'",
    )
)

COMMON_HEADERS: tuple[tuple[bytes, bytes], ...] = (
    (b"x-content-type-options", b"nosniff"),
    (b"referrer-policy", b"strict-origin-when-cross-origin"),
    (b"permissions-policy", b"camera=(), microphone=(), geolocation=(), payment=()"),
    (b"cross-origin-opener-policy", b"same-origin-allow-popups"),
)


class SecurityHeadersMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        is_api = str(scope.get("path", "")).startswith("/api/")

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                present = {name.lower() for name, _ in headers}
                extra = [(name, value) for name, value in COMMON_HEADERS if name not in present]
                content_type = next(
                    (value for name, value in headers if name.lower() == b"content-type"), b""
                )
                if content_type.startswith(b"text/html"):
                    extra.append((b"content-security-policy", CONTENT_SECURITY_POLICY.encode()))
                if is_api and b"cache-control" not in present:
                    extra.append((b"cache-control", b"no-store"))
                message["headers"] = headers + extra
            await send(message)

        await self.app(scope, receive, send_with_headers)


def _resolve(root: Path, path: str) -> Path | None:
    if not path or "\x00" in path:
        return None
    candidate = (root / path).resolve()
    if not candidate.is_relative_to(root) or not candidate.is_file():
        return None
    return candidate


def spa_router(dist_dir: Path) -> APIRouter | None:
    root = dist_dir.resolve()
    index = root / INDEX
    if not index.is_file():
        return None
    router = APIRouter(include_in_schema=False)

    @router.api_route("/{path:path}", methods=["GET", "HEAD"])
    async def serve(path: str) -> FileResponse:
        if path in RESERVED_PATHS or path.startswith(RESERVED_PREFIXES):
            raise HTTPException(status.HTTP_404_NOT_FOUND)
        found = _resolve(root, path)
        if found is None or found == index:
            if path.startswith("assets/"):
                raise HTTPException(status.HTTP_404_NOT_FOUND)
            return FileResponse(index, headers={"Cache-Control": NO_CACHE})
        cache = IMMUTABLE if path.startswith("assets/") else SHORT_CACHE
        return FileResponse(found, headers={"Cache-Control": cache})

    return router
