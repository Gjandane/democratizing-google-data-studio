"""Render every deck/diagrams/d*.html to deck/img/<name>.png with headless Chrome.

Usage: uv run --project integration python integration/render_diagrams.py

Each PNG is a 1840x800 CSS viewport at device scale 2 (3680x1600 px). Chrome comes from
DSS_CHROME_PATH (real env, then the root .env), else the standard install paths. Chrome runs
with a throwaway profile per page, so it never touches the engine's .chrome-profile.
"""

from __future__ import annotations

import os
import shutil
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIAGRAMS = ROOT / "deck" / "diagrams"
IMG = ROOT / "deck" / "img"
WIDTH, HEIGHT, SCALE = 1840, 800, 2

STANDARD_PATHS = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/usr/bin/google-chrome",
    "/usr/bin/google-chrome-stable",
    "/usr/bin/chromium",
    "/usr/bin/chromium-browser",
]


def env_chrome_path() -> str:
    """DSS_CHROME_PATH from the real env, else from the root .env (only that one name is read)."""
    value = os.environ.get("DSS_CHROME_PATH", "").strip()
    if value:
        return value
    env_file = ROOT / ".env"
    if env_file.is_file():
        for line in env_file.read_text(encoding="utf-8", errors="replace").splitlines():
            key, sep, val = line.strip().partition("=")
            if sep and key.strip() == "DSS_CHROME_PATH":
                return val.strip().strip('"').strip("'")
    return ""


def find_chrome() -> str:
    configured = env_chrome_path()
    if configured:
        if Path(configured).is_file():
            return configured
        sys.exit(f"render_diagrams: DSS_CHROME_PATH points to a missing file: {configured}")
    for candidate in STANDARD_PATHS:
        if candidate and Path(candidate).is_file():
            return candidate
    for name in ("google-chrome", "chrome", "chromium"):
        found = shutil.which(name)
        if found:
            return found
    sys.exit(
        "render_diagrams: Chrome not found. Set DSS_CHROME_PATH in .env (or the environment) "
        "to the Chrome executable, or install Chrome at a standard path, e.g. "
        + STANDARD_PATHS[0]
    )


def png_size(path: Path) -> tuple[int, int]:
    with path.open("rb") as fh:
        head = fh.read(24)
    if len(head) < 24 or head[:8] != b"\x89PNG\r\n\x1a\n" or head[12:16] != b"IHDR":
        raise ValueError(f"{path} is not a PNG")
    return struct.unpack(">II", head[16:24])


def render(chrome: str, html: Path, out: Path, profile: Path) -> None:
    if out.exists():
        out.unlink()
    cmd = [
        chrome,
        "--headless",
        f"--screenshot={out}",
        f"--window-size={WIDTH},{HEIGHT}",
        f"--force-device-scale-factor={SCALE}",
        "--hide-scrollbars",
        "--virtual-time-budget=5000",
        "--disable-gpu",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-extensions",
        "--disable-background-networking",
        "--disable-component-update",
        "--disable-sync",
        "--font-render-hinting=none",
        f"--user-data-dir={profile}",
        html.as_uri(),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if not out.is_file():
        tail = (proc.stderr or "").strip().splitlines()[-5:]
        raise RuntimeError(f"Chrome wrote no screenshot for {html.name} (exit {proc.returncode}): {tail}")


def main() -> int:
    pages = sorted(DIAGRAMS.glob("d*.html"))
    if not pages:
        print(f"render_diagrams: no d*.html in {DIAGRAMS}", file=sys.stderr)
        return 1
    chrome = find_chrome()
    IMG.mkdir(parents=True, exist_ok=True)
    want = (WIDTH * SCALE, HEIGHT * SCALE)
    failures = 0
    with tempfile.TemporaryDirectory(prefix="dss-render-", ignore_cleanup_errors=True) as tmp:
        for html in pages:
            out = IMG / f"{html.stem}.png"
            try:
                render(chrome, html, out, Path(tmp) / html.stem)
                size = png_size(out)
            except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired) as exc:
                print(f"FAIL {html.name}: {exc}")
                failures += 1
                continue
            if size != want:
                print(f"FAIL {out.relative_to(ROOT).as_posix()}: {size[0]}x{size[1]}, want {want[0]}x{want[1]}")
                failures += 1
                continue
            print(f"ok   {out.relative_to(ROOT).as_posix()}  {size[0]}x{size[1]}")
    print(f"{len(pages) - failures}/{len(pages)} diagrams rendered")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
