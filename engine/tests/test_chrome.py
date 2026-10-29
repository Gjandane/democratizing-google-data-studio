"""`dsengine login` waits for sign-in, a usable Data Studio home and a supported UI."""

from contextlib import contextmanager
from pathlib import Path

import pytest

from dsengine import chrome, cli
from dsengine.selectors import load_selectors

SELECTORS = load_selectors()


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


class FakeLocator:
    def __init__(self, page, selector):
        self.page = page
        self.selector = selector

    def filter(self, visible):
        assert visible is True
        return self

    def count(self):
        self.page.lookups.append((self.page.clock.now, self.selector))
        if self.selector == SELECTORS["first_run_dialog"]:
            return int(self.page.clock.now < self.page.dialog_until)
        if self.selector == SELECTORS["studio_home"]:
            # Its accessible name is English, so a translated home never matches.
            return int(self.page.browser.lang.lower().startswith("en") or not self.page.browser.lang)
        raise AssertionError(f"unexpected selector {self.selector}")


class FakePage:
    def __init__(self, browser):
        self.browser = browser
        self.clock = browser.clock
        self.dialog_until = browser.dialog_until
        self.url = "about:blank"
        self.lookups = []
        self.closed = False
        self.gotos = []

    def goto(self, url, **kwargs):
        self.gotos.append(url)
        self.url = url

    def wait_for_timeout(self, ms):
        self.clock.now += ms / 1000

    def locator(self, selector):
        return FakeLocator(self, selector)

    def evaluate(self, script):
        if script == "document.documentElement.lang":
            return self.browser.lang
        return {"lang": self.browser.lang, "outer": self.browser.outer, "inner": 1440}

    def bring_to_front(self):
        pass

    def close(self):
        self.closed = True


class FakeContext:
    def __init__(self, clock, signed_in_at=0.0, dialog_until=0.0, lang="en", zoom=1.0):
        self.clock = clock
        self.signed_in_at = signed_in_at
        self.dialog_until = dialog_until
        self.lang = lang
        self.outer = round(1454 * zoom)
        self.pages = []

    def new_page(self):
        page = FakePage(self)
        self.pages.append(page)
        return page

    def cookies(self, urls):
        if self.clock.now >= self.signed_in_at:
            return [{"name": "SID", "value": "x"}]
        return []


@pytest.fixture
def fake_login(monkeypatch):
    clock = Clock()
    monkeypatch.setattr(chrome.time, "monotonic", clock)
    monkeypatch.setattr(chrome, "ensure_browser", lambda config, url: "ws://127.0.0.1/x")

    def install(**kwargs):
        context = FakeContext(clock, **kwargs)

        @contextmanager
        def attached(config):
            yield context

        monkeypatch.setattr(chrome, "attached", attached)
        return context

    return clock, install


def run_login(capsys, timeout=300):
    config = chrome.ChromeConfig(Path("/tmp/profile").resolve(), 9222)
    result = chrome.login(config, timeout=timeout)
    return result, capsys.readouterr().err.splitlines()


def test_login_returns_after_sign_in_and_ready_home(fake_login, capsys):
    clock, install = fake_login
    context = install(signed_in_at=10)
    ok, err = run_login(capsys)
    assert ok is True
    probe = context.pages[1]
    assert probe.gotos == [chrome.STUDIO_URL]
    assert any(selector == SELECTORS["studio_home"] for _, selector in probe.lookups)
    assert clock.now >= 10
    assert probe.closed
    assert not any("terms" in line for line in err)


def test_login_waits_for_first_run_dialog_polling_every_3_s(fake_login, capsys):
    clock, install = fake_login
    context = install(dialog_until=20)
    ok, err = run_login(capsys)
    assert ok is True
    assert clock.now >= 20
    probe = context.pages[1]
    # The person's dialog input survives: no reload while it shows.
    assert probe.gotos == [chrome.STUDIO_URL]
    times = [at for at, selector in probe.lookups if selector == SELECTORS["first_run_dialog"]]
    assert len(times) >= 6
    gaps = [b - a for a, b in zip(times, times[1:])]
    assert all(2.9 <= gap <= 3.3 for gap in gaps)
    steps = [line for line in err if "terms" in line]
    assert len(steps) == 1
    assert "Continue" in steps[0] and "Data Studio" in steps[0]


def test_login_times_out_while_dialog_shows(fake_login, capsys):
    clock, install = fake_login
    context = install(dialog_until=10_000)
    ok, err = run_login(capsys)
    assert ok is False
    assert 300 <= clock.now < 301
    assert len([line for line in err if "terms" in line]) == 1
    assert "timed out" in err[-1]
    assert not context.pages[1].closed  # the person still needs the dialog tab


def test_login_times_out_without_sign_in(fake_login, capsys):
    clock, install = fake_login
    context = install(signed_in_at=10_000)
    ok, err = run_login(capsys)
    assert ok is False
    assert len(context.pages) == 1
    assert "Sign-in timed out" in err[-1]


@pytest.mark.parametrize("lang, zoom, expected", [
    ("fr", 1.0, ["Google account language"]),
    ("en", 0.9, ["Chrome zoom", "100%"]),
    ("de", 1.25, ["Google account language", "Chrome zoom"]),
])
def test_login_rejects_unsupported_language_or_zoom(fake_login, capsys, lang, zoom, expected):
    clock, install = fake_login
    install(lang=lang, zoom=zoom)
    ok, err = run_login(capsys)
    assert ok is False
    assert clock.now < 10  # reported at once, not after the 5 min timeout
    assert len([line for line in err if "Google account language" in line or "Chrome zoom" in line]) == 1
    assert all(word in err[-1] for word in expected)


@pytest.mark.parametrize("lang", ["en", "en-GB", ""])
def test_login_accepts_english_at_100_percent(fake_login, capsys, lang):
    _, install = fake_login
    install(lang=lang)
    ok, _ = run_login(capsys)
    assert ok is True


def test_login_uses_absolute_profile_without_dotenv(monkeypatch, tmp_path):
    profile = tmp_path / "visitor profile"
    engine_root = tmp_path / "engine"
    engine_root.mkdir()
    monkeypatch.setattr(cli, "ENGINE_ROOT", engine_root)  # no ../.env beside it
    monkeypatch.setenv("DSS_CHROME_PROFILE", str(profile))
    monkeypatch.delenv("DSS_CDP_PORT", raising=False)
    seen = []
    monkeypatch.setattr(chrome, "login", lambda config: seen.append(config) or True)
    assert cli.main(["login"]) == 0
    assert seen[0].profile == profile.resolve()
    assert seen[0].port == 9222


def test_login_exit_code_3_when_not_ready(monkeypatch, tmp_path):
    monkeypatch.setattr(cli, "ENGINE_ROOT", tmp_path)
    monkeypatch.setenv("DSS_CHROME_PROFILE", str(tmp_path / "p"))
    monkeypatch.setattr(chrome, "login", lambda config: False)
    assert cli.main(["login"]) == 3
