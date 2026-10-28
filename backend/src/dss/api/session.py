"""Shared access gate: the access code, or Google sign-in, as a cookie for SSE and iframes."""
import asyncio
import base64
import hashlib
import hmac
import re
import time

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token
from pydantic import BaseModel, ConfigDict, SecretStr, model_validator
from starlette.requests import Request as StarletteRequest

from dss.harness.guardrails import RunError

router = APIRouter(prefix="/api/session")
OPEN = {("GET", "/api/health"), ("GET", "/api/session"), ("POST", "/api/session")}
COOKIE = "dss_session"
GOOGLE_TTL_S = 24 * 3600
GOOGLE_COOKIE = re.compile(r"g\.([A-Za-z0-9_-]+)\.([0-9]{1,12})\.([0-9a-f]{64})")


def session_value(code):
    return hmac.new(code.encode(), b"dss_session:v1", hashlib.sha256).hexdigest()


def google_mac(code, email, expiry):
    return hmac.new(code.encode(), f"google|{email}|{expiry}".encode(), hashlib.sha256).hexdigest()


def google_value(code, email, expiry):
    encoded = base64.urlsafe_b64encode(email.encode()).decode().rstrip("=")
    return f"g.{encoded}.{expiry}.{google_mac(code, email, expiry)}"


def google_user(value, code):
    """The email of a Google cookie signed under this code and not yet expired, else None."""
    parsed = GOOGLE_COOKIE.fullmatch(value)
    if not parsed:
        return None
    encoded, expiry, mac = parsed.groups()
    try:
        email = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)).decode()
    except ValueError:  # binascii.Error and UnicodeDecodeError are both ValueErrors
        return None
    if not matches(mac, google_mac(code, email, expiry)) or int(expiry) <= time.time():
        return None
    return email


def matches(value, expected):
    # Bytes also handle non-ASCII user input without compare_digest raising.
    return hmac.compare_digest(value.encode(), expected.encode())


def access(request, config):
    """(ok, user): whether the request carries the code or a session cookie, and its Google email."""
    code = config.access_code.get_secret_value()
    if not code:
        return True, None
    cookie = request.cookies.get(COOKIE, "")
    # Google cookies count only while Google sign-in is on; the code cookie always does.
    user = google_user(cookie, code) if config.google_client_id else None
    ok = (user is not None or matches(request.headers.get("x-dss-access-code", ""), code)
          or matches(cookie, session_value(code)))
    return ok, user


def session(config, ok, user=None):
    return {"required": bool(config.access_code.get_secret_value()), "ok": ok,
            "google_client_id": config.google_client_id or None, "user": user}


class AccessMiddleware:
    def __init__(self, app, config):
        self.app, self.config = app, config

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            path = scope["path"]
            # Agent routes acquire their own token gate in task 5.2.
            agent = path == "/api/agent" or path.startswith("/api/agent/")
            api = path == "/api" or path.startswith("/api/")
            if (api and not agent and (scope["method"], path) not in OPEN
                    and not access(StarletteRequest(scope), self.config)[0]):
                response = JSONResponse({"error": {"code": "access_required",
                    "message": "Access code required", "detail": {}}}, status_code=401)
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)


class SessionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: SecretStr | None = None
    google_id_token: SecretStr | None = None

    @model_validator(mode="after")
    def one_credential(self):
        sent = [name for name in ("code", "google_id_token") if name in self.model_fields_set]
        if len(sent) != 1 or getattr(self, sent[0]) is None:
            raise ValueError("Send exactly one of code and google_id_token")
        return self


def verify(token, client_id):
    # Checks the signature against Google's certs, aud (= client_id), iss and exp.
    return id_token.verify_oauth2_token(token, google_requests.Request(), client_id)


def allowed(claims, rules):
    if not rules or "*" in rules:
        return True
    # A domain entry matches the Workspace hd claim only, never an email suffix.
    email, domain = claims["email"].lower(), str(claims.get("hd") or "").lower()
    return any(bool(domain) and rule[1:] == domain if rule.startswith("@") else rule == email
               for rule in rules)


async def google_session(token, config, request, response):
    client_id = config.google_client_id
    if not client_id:
        raise RunError("google_signin_off", "Google sign-in is not enabled", 400)
    try:
        claims = await asyncio.to_thread(verify, token, client_id)
    except Exception:
        # The token and the verifier's message stay out of logs, traces and the reply.
        claims = None
    if not isinstance(claims, dict):
        await asyncio.sleep(1)
        raise RunError("access_denied", "Google sign-in failed", 401)
    email = claims.get("email")
    email = email if isinstance(email, str) else ""
    if not email or claims.get("email_verified") not in (True, "true") or not allowed(claims, config.signin_allow):
        raise RunError("signin_not_allowed", "This Google account may not sign in", 403, {"email": email})
    expiry = int(time.time()) + GOOGLE_TTL_S
    response.set_cookie(COOKIE, google_value(config.access_code.get_secret_value(), email, expiry),
                        max_age=GOOGLE_TTL_S, httponly=True, samesite="strict",
                        secure=request.url.scheme == "https", path="/")
    return session(config, True, email)


@router.get("")
def get_session(request: Request):
    config = request.app.state.config
    return session(config, *access(request, config))


@router.post("")
async def create_session(body: SessionCreate, request: Request, response: Response):
    config = request.app.state.config
    if body.google_id_token is not None:
        return await google_session(body.google_id_token.get_secret_value(), config, request, response)
    code = config.access_code.get_secret_value()
    if code and not matches(body.code.get_secret_value(), code):
        await asyncio.sleep(1)
        raise RunError("access_denied", "Incorrect access code", 401)
    response.set_cookie(COOKIE, session_value(code), httponly=True, samesite="strict",
                        secure=request.url.scheme == "https", path="/")
    return session(config, True)
