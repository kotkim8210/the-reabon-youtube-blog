"""IP blocking middleware."""

import logging

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.db import is_ip_blocked

logger = logging.getLogger(__name__)


def get_client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client:
        return request.client.host
    return ""


class IPBlockMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        ip = get_client_ip(request)
        if ip and await is_ip_blocked(ip):
            logger.warning(f"Blocked request from {ip}")
            return JSONResponse(
                status_code=403,
                content={"detail": "Access denied"},
            )
        request.state.client_ip = ip
        return await call_next(request)
