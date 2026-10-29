"""Installed Chrome, isolated profile, and owned-page-only CDP sessions."""

from contextlib import contextmanager
from dataclasses import dataclass
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import time
from urllib.error import URLError
from urllib.parse import urlsplit
from urllib.request import ProxyHandler, build_opener

from playwright.sync_api import Error as PlaywrightError, sync_playwright

from dsengine.recipe import ENGINE_ROOT

ACCOUNTS_URL = "https://accounts.google.com/"
STUDIO_URL = "https://datastudio.google.com/"


class ChromeError(RuntimeError):
    """Safe message suitable for the CLI; never includes cookies or CDP details."""


class Screencast:
    """Stream JPEGs from one owned page on Playwright's event loop."""

    def __init__(self, page, events):
        self.events = events
        self.last_frame = None
        self.active = False
        self.session = page.context.new_cdp_session(page)
        self.session.on("Page.screencastFrame", self._frame)
        try:
            self.active = True
            self.session.send("Page.startScreencast", {"format": "jpeg", "quality": 60})
        except Exception:
            self.close()
            raise

    def _frame(self, frame):
        try:
            now = time.monotonic()
            if self.active and (self.last_frame is None or now - self.last_frame >= 0.5):
                self.last_frame = now
                self.events.emit("frame", data=frame["data"])
        finally:
            # Dropped frames also need an acknowledgement or Chrome stalls capture.
            try:
                self.session.send("Page.screencastFrameAck", {"sessionId": frame["sessionId"]})
            except PlaywrightError:
                pass  # The page may have closed while delivering its last frame.

    def close(self):
        self.active = False
        self.session.remove_listener("Page.screencastFrame", self._frame)
        try:
            self.session.send("Page.stopScreencast")
        except PlaywrightError:
            pass
        finally:
            try:
                self.session.detach()
            except PlaywrightError:
                pass


@dataclass(frozen=True)
class ChromeConfig:
    profile: Path
    port: int

    @classmethod
    def from_env(cls):
        try:
            port = int(os.environ.get("DSS_CDP_PORT", "9222"))
            if not 1 <= port <= 65535:
                raise ValueError
        except ValueError:
            raise ChromeError("DSS_CDP_PORT must be an integer from 1 to 65535") from None
        profile = Path(os.environ.get("DSS_CHROME_PROFILE") or "../.chrome-profile").expanduser()
        if not profile.is_absolute():
            profile = ENGINE_ROOT / profile
        return cls(profile.resolve(), port)

    @property
    def endpoint(self):
        return f"http://127.0.0.1:{self.port}"

    @property
    def marker(self):
        return self.profile / ".dsengine-cdp.json"


def chrome_path() -> str:
    explicit = os.environ.get("DSS_CHROME_PATH")
    candidates = [explicit] if explicit else [
        shutil.which("google-chrome"), shutil.which("google-chrome-stable"),
        str(Path(os.environ.get("PROGRAMFILES", "C:/Program Files")) / "Google/Chrome/Application/chrome.exe"),
        str(Path(os.environ.get("LOCALAPPDATA", "")) / "Google/Chrome/Application/chrome.exe"),
        "C:/Program Files (x86)/Google/Chrome/Application/chrome.exe",
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return str(candidate)
    raise ChromeError("Google Chrome not found; set DSS_CHROME_PATH to its executable")


def _version(config):
    try:
        # Ignore proxy environment variables for this strictly loopback request.
        with build_opener(ProxyHandler({})).open(config.endpoint + "/json/version", timeout=1) as response:
            value = json.load(response)
            return value if isinstance(value, dict) else None
    except (OSError, URLError, ValueError):
        return None


def _port_busy(config):
    with socket.socket() as sock:
        sock.settimeout(0.2)
        return sock.connect_ex(("127.0.0.1", config.port)) == 0


def _owned_endpoint(config, version):
    try:
        saved = json.loads(config.marker.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        saved = {}
    if not isinstance(saved, dict):
        saved = {}
    websocket = version.get("webSocketDebuggerUrl", "")
    try:
        parsed = urlsplit(websocket) if isinstance(websocket, str) else None
        local = (parsed is not None and parsed.scheme == "ws"
                 and parsed.hostname in {"127.0.0.1", "localhost"}
                 and parsed.port == config.port)
    except ValueError:
        local = False
    if (not local or saved.get("websocket") != websocket
            or saved.get("port") != config.port
            or not websocket):
        raise ChromeError("DSS_CDP_PORT is occupied by an unrecognized browser; use a free port")
    return websocket


def ensure_browser(config: ChromeConfig, url: str = STUDIO_URL):
    version = _version(config)
    if version:
        return _owned_endpoint(config, version)
    if _port_busy(config):
        raise ChromeError("DSS_CDP_PORT is busy; use a free port")
    executable = chrome_path()
    try:
        config.profile.mkdir(parents=True, exist_ok=True)
        process = subprocess.Popen([
            executable, f"--user-data-dir={config.profile}",
            f"--remote-debugging-port={config.port}", "--remote-debugging-address=127.0.0.1",
            "--no-first-run", "--no-default-browser-check", f"--app={url}",
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            version = _version(config)
            if version and version.get("webSocketDebuggerUrl"):
                config.marker.write_text(json.dumps({
                    "websocket": version["webSocketDebuggerUrl"], "port": config.port,
                }), encoding="utf-8")
                return _owned_endpoint(config, version)
            if process.poll() is not None:
                break
            time.sleep(0.2)
    except OSError:
        raise ChromeError("Cannot start Chrome or write DSS_CHROME_PROFILE; check the configured paths") from None
    raise ChromeError("Chrome CDP did not start; close the dedicated profile's windows and retry")


@contextmanager
def attached(config: ChromeConfig):
    """Disconnect on exit; never close the user's browser or existing tabs."""
    version = _version(config)
    if not version:
        raise ChromeError("Chrome is not running; run dsengine browser first")
    websocket = _owned_endpoint(config, version)
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.connect_over_cdp(websocket, timeout=10000)
            if not browser.contexts:
                raise ChromeError("Chrome has no persistent browser context")
            yield browser.contexts[0]
    except PlaywrightError:
        raise ChromeError("Chrome connection or navigation failed; retry dsengine browser or login") from None


def _has_google_session(context):
    # Read only the dedicated profile's cookies, never serialize or log them.
    return any(cookie["name"] in {"SID", "__Secure-1PSID", "__Secure-3PSID"}
               and bool(cookie["value"]) for cookie in context.cookies([ACCOUNTS_URL]))


def _studio_signed_in(page, context):
    page.goto(STUDIO_URL, wait_until="domcontentloaded", timeout=20000)
    url = urlsplit(page.url)
    return (url.hostname in {"datastudio.google.com", "lookerstudio.google.com"}
            and not url.path.startswith(("/u/0/login", "/login"))
            and _has_google_session(context))


def check(config: ChromeConfig) -> dict[str, bool]:
    if not _version(config):
        if _port_busy(config):
            raise ChromeError("DSS_CDP_PORT is busy; use a free port")
        return {"chrome_running": False, "signed_in": False}
    with attached(config) as context:
        page = context.new_page()
        try:
            signed_in = _studio_signed_in(page, context)
        finally:
            page.close()
    return {"chrome_running": True, "signed_in": signed_in}


def _home_state(page, selectors):
    """Return dialog, ready or loading; the person completes any dialog, never the engine."""
    if page.locator(selectors["first_run_dialog"]).filter(visible=True).count():
        return "dialog"
    if page.locator(selectors["studio_home"]).filter(visible=True).count():
        return "ready"
    # The home selector is English text, so a translated home never matches it:
    # treat it as ready and let the UI check name its language.
    return "ready" if not _english(page.evaluate("document.documentElement.lang")) else "loading"


def _english(lang):
    lang = (lang or "").lower()
    return not lang or lang.split("-")[0] == "en"


def _ui_problems(page):
    """What the person must change for English selectors and 100% placement zoom."""
    state = page.evaluate("({lang: document.documentElement.lang, outer: outerWidth, inner: innerWidth})")
    problems = []
    lang = (state.get("lang") or "").lower()
    if not _english(lang):
        problems.append(f"Data Studio shows language '{lang}': set your Google account language to "
                        "English (myaccount.google.com > Personal info > Language)")
    # outerWidth is in screen pixels and innerWidth in CSS pixels, so their ratio
    # is Chrome's page zoom (plus ~1% of window frame), whatever the display scale.
    zoom = state["outer"] / state["inner"] if state.get("inner") else 1.0
    if abs(zoom - 1) > 0.05:
        problems.append(f"Chrome zoom is about {round(zoom * 100)}%: set it to 100% in the dedicated "
                        "Chrome window (Ctrl+0, Settings > Appearance > Page zoom)")
    return problems


def login(config: ChromeConfig, timeout: float = 300) -> bool:
    from dsengine.selectors import SelectorError, load_selectors

    try:
        selectors = load_selectors()
    except SelectorError as exc:
        raise ChromeError(str(exc)) from None
    ensure_browser(config, ACCOUNTS_URL)
    print("Sign in manually in the dedicated Chrome window. Waiting up to 5 minutes.", file=sys.stderr, flush=True)
    with attached(config) as context:
        page = context.new_page()
        probe = None
        signed_in = told = timed_out = False
        try:
            page.goto(ACCOUNTS_URL, wait_until="domcontentloaded", timeout=20000)
            deadline = time.monotonic() + timeout
            next_check = 0.0
            while time.monotonic() < deadline:
                if time.monotonic() >= next_check:
                    if not signed_in and _has_google_session(context):
                        if probe is None:
                            probe = context.new_page()
                        signed_in = _studio_signed_in(probe, context)
                        if signed_in:
                            print("Data Studio sign-in confirmed.", file=sys.stderr, flush=True)
                    # Poll the loaded home without reloading it, so the person's
                    # first-run dialog keeps what they entered.
                    state = _home_state(probe, selectors) if signed_in else None
                    if state == "ready":
                        problems = _ui_problems(probe)
                        if problems:
                            print("; ".join(problems) + "; then run dsengine login again.",
                                  file=sys.stderr, flush=True)
                            return False
                        print("Data Studio is ready.", file=sys.stderr, flush=True)
                        return True
                    if state == "dialog" and not told:
                        probe.bring_to_front()
                        print("In the dedicated Chrome window's Data Studio tab, choose your country, "
                              "accept the Data Studio terms of service, click Continue and answer any follow-up dialog.",
                              file=sys.stderr, flush=True)
                        told = True
                    next_check = time.monotonic() + 3
                page.wait_for_timeout(250)
            timed_out = True
        finally:
            # Keep the login and first-run tabs available on timeout for the person.
            if probe is not None and not (timed_out and signed_in):
                probe.close()
        if signed_in:
            print("Data Studio setup timed out; finish it in Chrome, then run dsengine login again.",
                  file=sys.stderr)
        else:
            print("Sign-in timed out; complete it manually, then run dsengine check.", file=sys.stderr)
        return False
