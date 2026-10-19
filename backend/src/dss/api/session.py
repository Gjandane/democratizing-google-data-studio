"""Shared access-code gate, including cookie authentication for SSE and iframes."""
import asyncio
import hashlib
import hmac

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, SecretStr
from starlette.requests import Request as StarletteRequest

from dss.harness.guardrails import RunError

router = APIRouter(prefix="/api/session")
OPEN = {("GET", "/api/health"), ("GET", "/api/session"), ("POST", "/api/session")}


def session_value(code):
    return hmac.new(code.encode(), b"dss_session:v1", hashlib.sha256).hexdigest()


def matches(value, expected):
    # Bytes also handle non-ASCII user input without compare_digest raising.
    return hmac.compare_digest(value.encode(), expected.encode())


def authorized(request, code):
    return (not code or matches(request.headers.get("x-dss-access-code", ""), code)
            or matches(request.cookies.get("dss_session", ""), session_value(code)))


class AccessMiddleware:
    def __init__(self, app, config):
        self.app, self.code = app, config.access_code.get_secret_value()

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            path = scope["path"]
            # Agent routes acquire their own token gate in task 5.2.
            agent = path == "/api/agent" or path.startswith("/api/agent/")
            api = path == "/api" or path.startswith("/api/")
            if (api and not agent and (scope["method"], path) not in OPEN
                    and not authorized(StarletteRequest(scope), self.code)):
                response = JSONResponse({"error": {"code": "access_required",
                    "message": "Access code required", "detail": {}}}, status_code=401)
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)


class SessionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: SecretStr


@router.get("")
def get_session(request: Request):
    code = request.app.state.config.access_code.get_secret_value()
    return {"required": bool(code), "ok": authorized(request, code)}


@router.post("")
async def create_session(body: SessionCreate, request: Request, response: Response):
    code = request.app.state.config.access_code.get_secret_value()
    if code and not matches(body.code.get_secret_value(), code):
        await asyncio.sleep(1)
        raise RunError("access_denied", "Incorrect access code", 401)
    response.set_cookie("dss_session", session_value(code), httponly=True, samesite="strict",
                        secure=request.url.scheme == "https", path="/")
    return {"required": bool(code), "ok": True}
