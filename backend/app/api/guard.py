"""Only this machine's own UI may drive the API.

The backend holds a tracker key with write access and listens on localhost, so any web page open
in the same browser can try to reach it. Two checks stop that:

- Host: a page that rebinds its own hostname to 127.0.0.1 (DNS rebinding) still sends its own
  name in the Host header, so unknown hosts are refused (400).
- Origin: a cross-site form or fetch carries a valid Host but the attacker's Origin, so writes
  (anything but GET/HEAD/OPTIONS) from another origin are refused (403). Requests without an
  Origin header, such as curl, are allowed.
"""

from urllib.parse import urlsplit

from fastapi import FastAPI, Request, Response
from fastapi.responses import PlainTextResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def foreign_origin(origin: str | None, allowed: list[str]) -> bool:
    return origin is not None and urlsplit(origin).hostname not in allowed


def install(app: FastAPI, allowed_hosts: list[str]) -> None:
    @app.middleware("http")
    async def same_origin_writes(request: Request, call_next) -> Response:
        if request.method not in SAFE_METHODS and foreign_origin(
                request.headers.get("origin"), allowed_hosts):
            return PlainTextResponse("Cross-origin request refused", status_code=403)
        return await call_next(request)

    # Added last so it runs first: an unknown host never reaches the Origin check.
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=allowed_hosts)
