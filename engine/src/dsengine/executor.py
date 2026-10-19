"""Replay validated recipes in an owned Data Studio tab."""

from __future__ import annotations

from pathlib import Path
import time
from typing import Any

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from dsengine import chrome
from dsengine.events import EventWriter
from dsengine.linking import build_url
from dsengine.ops import OpContext, OperationError, handler_for
from dsengine.recipe import Recipe
from dsengine.selectors import SelectorError, load_selectors

PER_OP_TIMEOUT_S = 20.0


def _safe_message(error: Exception) -> str:
    if isinstance(error, OperationError):
        return str(error)
    if isinstance(error, (PlaywrightTimeoutError, TimeoutError)):
        return "operation timed out"
    return f"operation failed ({type(error).__name__})"


def reset_ui(page: Any, ctx: OpContext) -> None:
    """Clear transient selection state before the one permitted retry."""
    try:
        page.keyboard.press("Escape", timeout=ctx.timeout_ms())
    except Exception:
        pass
    try:
        canvas = ctx.locator(page, "canvas")
        if canvas.count() == 0 or not canvas.is_visible():
            return
        box = canvas.bounding_box()
        if box:
            # Click the empty workspace immediately to the left of the canvas.
            page.mouse.click(max(1, box["x"] - 12), box["y"] + min(40, box["height"] / 2),
                             timeout=ctx.timeout_ms())
    except Exception:
        pass


def _dismiss_known_popups(page: Any, ctx: OpContext) -> None:
    """Dismiss UI popups whose selectors are recorded in the selector bundle."""
    for key in sorted(name for name in ctx.selectors if name.startswith("dismiss.")):
        try:
            popup = ctx.locator(page, key)
            if popup.count() and popup.is_visible():
                popup.click(timeout=ctx.timeout_ms())
        except Exception:
            continue


def _run_one(page: Any, op: Any, ctx: OpContext) -> str:
    handler = handler_for(op.op)
    if handler is None:
        raise OperationError(f"operation {op.op} is not implemented yet")
    _dismiss_known_popups(page, ctx)
    handler.run(page, op, ctx)
    _dismiss_known_popups(page, ctx)
    handler.verify(page, op, ctx)
    return ""


def _finish(events: EventWriter, *, status: str, report_url: str | None,
            ok: int, failed: int, skipped: int, error_code: str | None) -> int:
    events.emit("run_finished", status=status, report_url=report_url,
                ok=ok, failed=failed, skipped=skipped, error_code=error_code)
    return 0 if status in {"ok", "partial"} else 1


def run_recipe(
    recipe: Recipe,
    events: EventWriter,
    *,
    dry_run: bool = False,
    screens: Path | None = None,
    screencast: bool = False,
    timeout: float = 600,
) -> int:
    events.emit("run_started", build_id=recipe.header.build_id,
                version=recipe.header.version, total_ops=len(recipe.ops))

    if dry_run:
        # A dry run is a full preview, independent of browser settings or time budgets.
        for op in recipe.ops:
            events.emit("op_started", op_id=op.id, op=op.op)
            events.emit("op_finished", op_id=op.id, op=op.op, status="skipped",
                        message="dry-run", screenshot=None, duration_ms=0)
        events.emit("run_finished", status="ok", report_url=None,
                    ok=0, failed=0, skipped=len(recipe.ops), error_code=None)
        return 0

    if not recipe.ops:
        events.emit("run_finished", status="ok", report_url=None,
                    ok=0, failed=0, skipped=0, error_code=None)
        return 0

    run_started = time.monotonic()
    run_deadline = run_started + timeout
    try:
        selectors = load_selectors()
    except SelectorError:
        events.error("Cannot load the Data Studio selector bundle")
        return _finish(events, status="failed", report_url=None,
                       ok=0, failed=0, skipped=0, error_code="selector_error")

    open_url = None
    if any(op.op == "open_report" for op in recipe.ops):
        try:
            # Validate required Linking API configuration before touching Chrome.
            open_url = build_url(recipe.header)
        except ValueError as error:
            events.error(str(error))
            return _finish(events, status="failed", report_url=None,
                           ok=0, failed=0, skipped=len(recipe.ops),
                           error_code="configuration_error")

    try:
        config = chrome.ChromeConfig.from_env()
        chrome.ensure_browser(config)
        session = chrome.check(config)
    except chrome.ChromeError as error:
        events.error(str(error))
        return _finish(events, status="failed", report_url=None,
                       ok=0, failed=0, skipped=0, error_code="browser_error")

    if not session.get("signed_in", False):
        events.error("Data Studio is not signed in; sign in manually and retry")
        events.emit("run_finished", status="failed", report_url=None,
                    ok=0, failed=0, skipped=len(recipe.ops), error_code="not_signed_in")
        return 3

    screens_dir = Path(screens) if screens is not None else recipe.path.parent / "screens"
    ctx = OpContext(recipe=recipe, selectors=selectors, events=events,
                    screens=screens_dir, run_deadline=run_deadline, open_url=open_url)

    try:
        with chrome.attached(config) as browser_context:
            page = browser_context.new_page()
            capture = None
            try:
                page.set_viewport_size({"width": 1920, "height": 1200})
                if screencast:
                    capture = chrome.Screencast(page, events)
                successes = 0
                failures = 0
                skipped = 0
                open_succeeded = False
                save_succeeded = False
                link_succeeded = False
                timed_out = False

                for op in recipe.ops:
                    op_name = op.op
                    is_finalizer = op_name in {"save_report", "get_link"}
                    if time.monotonic() >= run_deadline and not is_finalizer:
                        timed_out = True
                        skipped += 1
                        events.emit("op_started", op_id=op.id, op=op_name)
                        events.emit("op_finished", op_id=op.id, op=op_name,
                                    status="skipped", message="run timeout before execution",
                                    screenshot=None, duration_ms=0)
                        continue

                    events.emit("op_started", op_id=op.id, op=op_name)
                    started = time.monotonic()
                    ctx.current_op = op_name
                    ctx.op_deadline = started + PER_OP_TIMEOUT_S
                    ctx.bypass_run_deadline = is_finalizer
                    page.set_default_timeout(ctx.timeout_ms())

                    message = ""
                    status = "failed"
                    screenshot: str | None = None
                    for attempt in range(2):
                        try:
                            message = _run_one(page, op, ctx)
                            status = "ok"
                            break
                        except Exception as error:
                            message = _safe_message(error)
                            if attempt == 0:
                                reset_ui(page, ctx)
                                continue
                            try:
                                screens_dir.mkdir(parents=True, exist_ok=True)
                                screenshot_path = screens_dir / f"{op.id}_failed.png"
                                page.screenshot(path=str(screenshot_path), full_page=True,
                                                timeout=ctx.timeout_ms())
                                screenshot = screenshot_path.name
                            except Exception:
                                screenshot = None

                    duration_ms = max(0, int((time.monotonic() - started) * 1000))
                    events.emit("op_finished", op_id=op.id, op=op_name, status=status,
                                message=message, screenshot=screenshot,
                                duration_ms=duration_ms)

                    if status == "ok":
                        successes += 1
                        if op_name == "open_report":
                            open_succeeded = True
                            ctx.report_opened = True
                        elif op_name == "save_report":
                            save_succeeded = True
                            ctx.report_saved = True
                        elif op_name == "get_link":
                            link_succeeded = True
                    else:
                        failures += 1
                        if op_name == "open_report":
                            return _finish(events, status="failed", report_url=None,
                                           ok=successes, failed=failures,
                                           skipped=max(0, len(recipe.ops) - successes - failures),
                                           error_code="open_report_failed")

                    if time.monotonic() >= run_deadline and not is_finalizer:
                        timed_out = True

                if time.monotonic() >= run_deadline:
                    timed_out = True

                ctx.bypass_run_deadline = True
                if timed_out:
                    events.error("Whole-run timeout reached; remaining report operations were prioritized")

                if timed_out:
                    status = "failed"
                elif failures == 0 and open_succeeded and save_succeeded and link_succeeded:
                    status = "ok"
                elif failures > 0 and open_succeeded and save_succeeded and link_succeeded:
                    status = "partial"
                else:
                    status = "failed"
                return _finish(events, status=status,
                               report_url=ctx.report_url if link_succeeded else None,
                               ok=successes, failed=failures, skipped=skipped,
                               error_code="timeout" if timed_out else None)
            finally:
                try:
                    if capture is not None:
                        capture.close()
                finally:
                    try:
                        page.close()
                    except Exception:
                        pass
    except chrome.ChromeError as error:
        events.error(str(error))
        return _finish(events, status="failed", report_url=None,
                       ok=0, failed=0, skipped=len(recipe.ops), error_code="browser_error")
    except Exception as error:
        events.error(_safe_message(error))
        return _finish(events, status="failed", report_url=None,
                       ok=0, failed=0, skipped=len(recipe.ops), error_code="browser_error")
