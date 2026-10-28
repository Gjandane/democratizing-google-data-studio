"""Google sign-in at the access gate (api.md 3.3), with the google-auth verifier stubbed: no network."""
import asyncio
import base64
import hashlib
import hmac
import logging
import sqlite3
import time
from types import SimpleNamespace

from fastapi.testclient import TestClient
from google.auth import exceptions as google_exceptions
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token
import pytest

from dss.api import session as session_module
from dss.config import Config
from dss.main import create_app
from fakes import fake_models

CODE = "c0de-c0de-c0de"
CLIENT = "000000000000-example.apps.googleusercontent.com"
ISSUER = "https://accounts.google.com"


def claims(email, verified=True, hd=None, aud=CLIENT):
    values = {"iss": ISSUER, "aud": aud, "sub": "1" + email, "email": email, "email_verified": verified}
    return {**values, "hd": hd} if hd else values


TOKENS = {
    "tok-gmail": claims("someone@gmail.com"),
    "tok-workspace": claims("ana@example.com", hd="example.com"),
    "tok-suffix-only": claims("eve@example.com"),
    "tok-subdomain": claims("sam@sub.example.com", hd="sub.example.com"),
    "tok-judge": claims("judge@example.com", hd="example.com"),
    "tok-judge-upper": claims("Judge@Example.com"),
    "tok-unverified": claims("ana@example.com", verified=False, hd="example.com"),
    "tok-unverified-missing": {**claims("bob@gmail.com"), "email_verified": None},
    "tok-wrong-aud": claims("someone@gmail.com", aud="other-client.apps.googleusercontent.com"),
}
FAILURES = {
    "tok-bad-signature": ValueError("Could not verify token signature. secret-verifier-detail"),
    "tok-expired": ValueError("Token expired, 1700000000 < 1800000000 secret-verifier-detail"),
    "tok-wrong-iss": google_exceptions.GoogleAuthError("Wrong issuer secret-verifier-detail"),
}


@pytest.fixture
def verifier(monkeypatch):
    """Stub google.oauth2.id_token.verify_oauth2_token; any real cert fetch fails the test."""
    calls = []

    def verify(token, request, audience=None, clock_skew_in_seconds=0):
        try:
            asyncio.get_running_loop()
            on_loop = True
        except RuntimeError:
            on_loop = False
        calls.append({"audience": audience, "on_loop": on_loop,
                      "request": isinstance(request, google_requests.Request)})
        if token in FAILURES:
            raise FAILURES[token]
        values = dict(TOKENS[token])
        if values["aud"] != audience:  # what google-auth's jwt.decode checks
            raise ValueError(f"Token has wrong audience {values['aud']}, expected one of {audience}")
        return values

    fetches = []

    def no_network(*args, **kwargs):
        # Recorded, then failed at teardown: the route maps any verifier exception to 401.
        fetches.append(kwargs.get("url") or args[1:2])
        raise AssertionError("tests never fetch Google's certs")

    monkeypatch.setattr(id_token, "verify_oauth2_token", verify)
    monkeypatch.setattr(google_requests.Request, "__call__", no_network)
    yield calls
    assert fetches == []


def google_app(tmp_path, allow="", client_id=CLIENT, code=CODE):
    config = Config(data_dir=tmp_path / "data", access_code=code, google_client_id=client_id,
                    signin_allow=allow)
    return create_app(config, model_lister=fake_models)


def sign_in(client, token):
    return client.post("/api/session", json={"google_id_token": token})


def session_cookie(response):
    cookie = response.headers["set-cookie"]
    return cookie.split(";", 1)[0].removeprefix("dss_session=")


@pytest.mark.parametrize("allow", ["", "*", " * ", ",, "])
def test_any_account_when_allow_is_empty_or_star(tmp_path, verifier, allow):
    with TestClient(google_app(tmp_path, allow)) as client:
        assert client.get("/api/session").json() == {
            "required": True, "ok": False, "google_client_id": CLIENT, "user": None}
        response = sign_in(client, "tok-gmail")
        assert response.status_code == 200, response.text
        assert response.json() == {"required": True, "ok": True, "google_client_id": CLIENT,
                                   "user": "someone@gmail.com"}
        header = response.headers["set-cookie"]
        assert "HttpOnly" in header and "SameSite=strict" in header and "Max-Age=86400" in header
        assert "Secure" not in header and "tok-gmail" not in header and CODE not in header
        assert client.get("/api/builds").status_code == 200
        assert client.get("/api/session").json()["user"] == "someone@gmail.com"
    # The audience is the configured client id, and verification runs off the event loop.
    assert verifier == [{"audience": CLIENT, "on_loop": False, "request": True}]


def test_google_cookie_format_and_https(tmp_path, verifier):
    with TestClient(google_app(tmp_path), base_url="https://host") as client:
        response = sign_in(client, "tok-gmail")
        assert "Secure" in response.headers["set-cookie"]
        prefix, encoded, expiry, mac = session_cookie(response).split(".")
        email = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)).decode()
        assert prefix == "g" and email == "someone@gmail.com"
        assert abs(int(expiry) - (time.time() + 24 * 3600)) < 60
        assert mac == hmac.new(CODE.encode(), f"google|{email}|{expiry}".encode(), hashlib.sha256).hexdigest()
        assert client.get("/api/builds").status_code == 200


def test_domain_entry_matches_hd_never_an_email_suffix(tmp_path, verifier):
    with TestClient(google_app(tmp_path, "@Example.com")) as client:
        allowed = sign_in(client, "tok-workspace")
        assert allowed.status_code == 200 and allowed.json()["user"] == "ana@example.com"
        for token, email in (("tok-gmail", "someone@gmail.com"), ("tok-suffix-only", "eve@example.com"),
                             ("tok-subdomain", "sam@sub.example.com")):
            refused = TestClient(client.app).post("/api/session", json={"google_id_token": token})
            assert refused.status_code == 403, token
            assert refused.json()["error"]["code"] == "signin_not_allowed"
            assert refused.json()["error"]["detail"] == {"email": email}
            assert "set-cookie" not in refused.headers


def test_exact_email_entry_is_case_insensitive(tmp_path, verifier):
    with TestClient(google_app(tmp_path, " JUDGE@example.COM , ,@other.org")) as client:
        assert sign_in(client, "tok-judge").json()["user"] == "judge@example.com"
        assert sign_in(client, "tok-judge-upper").json()["user"] == "Judge@Example.com"
        refused = sign_in(TestClient(client.app), "tok-gmail")
        assert refused.status_code == 403 and refused.json()["error"]["code"] == "signin_not_allowed"


@pytest.mark.parametrize("token,email", [("tok-unverified", "ana@example.com"),
                                         ("tok-unverified-missing", "bob@gmail.com")])
def test_unverified_email_is_refused(tmp_path, verifier, token, email):
    with TestClient(google_app(tmp_path)) as client:
        response = sign_in(client, token)
        assert response.status_code == 403
        assert response.json()["error"] == {"code": "signin_not_allowed", "detail": {"email": email},
                                            "message": "This Google account may not sign in"}
        assert "set-cookie" not in response.headers
        assert client.get("/api/builds").status_code == 401


@pytest.mark.parametrize("token", ["tok-bad-signature", "tok-wrong-aud", "tok-expired",
                                   "tok-wrong-iss", "tok-unknown"])
def test_verifier_errors_are_access_denied_after_delay(tmp_path, verifier, token):
    with TestClient(google_app(tmp_path)) as client:
        started = time.monotonic()
        response = sign_in(client, token)
        assert time.monotonic() - started >= 0.95
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "access_denied"
        assert "secret-verifier-detail" not in response.text and "audience" not in response.text
        assert "set-cookie" not in response.headers
        assert client.get("/api/builds").json()["error"]["code"] == "access_required"


def test_signin_off_without_client_id(tmp_path, verifier):
    with TestClient(google_app(tmp_path, client_id="")) as client:
        assert client.get("/api/session").json() == {
            "required": True, "ok": False, "google_client_id": None, "user": None}
        response = sign_in(client, "tok-gmail")
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "google_signin_off"
    with TestClient(google_app(tmp_path, client_id="", code="")) as client:
        assert sign_in(client, "tok-gmail").json()["error"]["code"] == "google_signin_off"
    assert verifier == []


@pytest.mark.parametrize("body", [{}, {"code": CODE, "google_id_token": "tok-gmail"},
                                  {"code": None}, {"google_id_token": None},
                                  {"code": CODE, "google_id_token": None}, {"token": "tok-gmail"}])
def test_body_needs_exactly_one_credential(tmp_path, verifier, body):
    with TestClient(google_app(tmp_path)) as client:
        response = client.post("/api/session", json=body)
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "invalid_request"
        assert "tok-gmail" not in response.text and CODE not in response.text
        assert "set-cookie" not in response.headers


def test_tampered_expired_and_old_code_cookies(tmp_path, verifier, monkeypatch):
    with TestClient(google_app(tmp_path)) as client:
        cookie = session_cookie(sign_in(client, "tok-gmail"))
    prefix, encoded, expiry, mac = cookie.split(".")
    other = base64.urlsafe_b64encode(b"intruder@gmail.com").decode().rstrip("=")
    flipped = mac[:-1] + ("0" if mac[-1] != "0" else "1")
    tampered = [f"{prefix}.{other}.{expiry}.{mac}", f"{prefix}.{encoded}.{int(expiry) + 3600}.{mac}",
                f"{prefix}.{encoded}.{expiry}.{flipped}", f"{prefix}.{encoded}.{expiry}.{mac.upper()}",
                f"{prefix}.{encoded}.{expiry}.{mac}.x", f"x.{encoded}.{expiry}.{mac}", "g.%%%.1.2", ""]

    def opens(app, value):
        with TestClient(app) as client:
            response = client.get("/api/builds", headers={"Cookie": f"dss_session={value}"})
            if response.status_code == 401:
                assert response.json()["error"]["code"] == "access_required"
            return response.status_code == 200

    app = google_app(tmp_path)
    assert opens(app, cookie)
    for value in tampered:
        assert not opens(app, value), value
    # Expiry: valid until 24 h after sign-in, refused from then on.
    real = time.time
    monkeypatch.setattr(session_module, "time", SimpleNamespace(time=lambda: int(expiry) - 1))
    assert opens(app, cookie)
    monkeypatch.setattr(session_module, "time", SimpleNamespace(time=lambda: int(expiry)))
    assert not opens(app, cookie)
    monkeypatch.setattr(session_module, "time", SimpleNamespace(time=lambda: real() + 24 * 3600 + 1))
    assert not opens(app, cookie)
    monkeypatch.setattr(session_module, "time", time)
    # A changed code logs Google sessions out; so does turning Google sign-in off.
    assert not opens(google_app(tmp_path, code="a-different-code"), cookie)
    assert not opens(google_app(tmp_path, client_id=""), cookie)
    stale = f"g.{encoded}.{int(time.time()) - 1}." + hmac.new(
        CODE.encode(), f"google|someone@gmail.com|{int(time.time()) - 1}".encode(), hashlib.sha256).hexdigest()
    assert not opens(app, stale)


def test_code_and_header_unchanged_with_google_on(tmp_path, verifier):
    with TestClient(google_app(tmp_path)) as client:
        assert client.get("/api/builds", headers={"X-DSS-Access-Code": CODE}).status_code == 200
        assert client.get("/api/session", headers={"X-DSS-Access-Code": CODE}).json() == {
            "required": True, "ok": True, "google_client_id": CLIENT, "user": None}
        started = time.monotonic()
        denied = client.post("/api/session", json={"code": "incorrect-code"})
        assert time.monotonic() - started >= 0.95
        assert denied.status_code == 401 and denied.json()["error"]["code"] == "access_denied"
        response = client.post("/api/session", json={"code": CODE})
        assert response.json() == {"required": True, "ok": True, "google_client_id": CLIENT, "user": None}
        assert session_cookie(response) == session_module.session_value(CODE)
        assert client.get("/api/builds").status_code == 200
        # A code sign-in replaces a Google session cookie, and a Google one replaces it again.
        assert sign_in(client, "tok-gmail").json()["user"] == "someone@gmail.com"
        assert client.get("/api/session").json()["user"] == "someone@gmail.com"
        client.post("/api/session", json={"code": CODE})
        assert client.get("/api/session").json()["user"] is None
    assert verifier[0]["audience"] == CLIENT


def test_agent_routes_ignore_google_cookies(tmp_path, verifier):
    app = create_app(Config(data_dir=tmp_path / "data", access_code=CODE, google_client_id=CLIENT,
                            engine_mode="agent", agent_token="t" * 24), model_lister=fake_models)
    with TestClient(app) as client:
        sign_in(client, "tok-gmail")
        assert client.get("/api/builds").status_code == 200
        response = client.post("/api/agent/heartbeat", json={"chrome_running": False, "signed_in": False})
        assert response.status_code == 401 and response.json()["error"]["code"] == "agent_unauthorized"


def test_token_never_logged_or_traced(tmp_path, verifier, caplog):
    caplog.set_level(logging.DEBUG)
    with TestClient(google_app(tmp_path, "@example.com")) as client:
        for token in ("tok-workspace", "tok-gmail", "tok-unverified", "tok-bad-signature", "tok-wrong-aud"):
            sign_in(TestClient(client.app), token)
        sign_in(client, "tok-workspace")
        traces = client.get("/api/traces").text
    with sqlite3.connect(tmp_path / "data" / "dss.sqlite") as connection:
        tables = [row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        stored = repr([connection.execute(f'SELECT * FROM "{table}"').fetchall() for table in tables])
    connection.close()
    for text in (caplog.text, traces, stored):
        assert "tok-" not in text and "secret-verifier-detail" not in text
