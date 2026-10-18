"""Operation contracts shared by the executor and live operation modules."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import time
from typing import Any, Mapping

from dsengine.events import EventWriter
from dsengine.recipe import Recipe


class OperationError(RuntimeError):
    """A safe, user-facing operation failure message."""


@dataclass
class OpResult:
    message: str = ""


@dataclass
class OpContext:
    recipe: Recipe
    selectors: Mapping[str, str]
    events: EventWriter
    screens: Path
    run_deadline: float
    op_deadline: float = float("inf")
    current_op: str = ""
    bypass_run_deadline: bool = False
    report_opened: bool = False
    report_saved: bool = False
    report_url: str | None = None
    open_url: str | None = None
    canvas_dimensions: tuple[int, int] | None = None
    state: dict[str, Any] = field(default_factory=dict)

    def remaining_s(self) -> float:
        deadline = self.op_deadline
        if not self.bypass_run_deadline:
            deadline = min(deadline, self.run_deadline)
        return max(0.0, deadline - time.monotonic())

    def timeout_ms(self) -> int:
        return max(1, int(self.remaining_s() * 1000))

    def locator(self, page: Any, key: str) -> Any:
        try:
            selector = self.selectors[key]
        except KeyError:
            raise OperationError(f"required UI selector is missing: {key}") from None
        return page.locator(selector)

    def warn(self, message: str) -> None:
        self.events.emit("log", level="warn", message=message)


from dsengine.ops import charts, controls, report, pages, text, style


def handler_for(name: str):
    """Return the operation module that owns this op, if it is implemented."""
    if name in report.HANDLED_OPS:
        return report
    if name in charts.HANDLED_OPS:
        return charts
    if name in controls.HANDLED_OPS:
        return controls
    for module in (pages, text, style):
        if name in module.HANDLED_OPS:
            return module
    return None


__all__ = ["OpContext", "OpResult", "OperationError", "handler_for"]
