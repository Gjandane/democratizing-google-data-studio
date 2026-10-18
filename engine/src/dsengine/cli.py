"""Contract CLI entry point."""

import argparse
import io
import json
import math
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from dsengine.events import EventWriter
from dsengine.executor import run_recipe
from dsengine.printer import recipe_commands
from dsengine.recipe import ENGINE_ROOT, RecipeError, load_recipe


def _positive_seconds(value: str) -> float:
    try:
        seconds = float(value)
    except ValueError:
        raise argparse.ArgumentTypeError("timeout must be a positive, finite number") from None
    if not math.isfinite(seconds) or seconds <= 0:
        raise argparse.ArgumentTypeError("timeout must be a positive, finite number")
    return seconds


def main(argv: list[str] | None = None) -> int:
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(encoding="utf-8")
    load_dotenv(ENGINE_ROOT.parent / ".env", override=False)
    parser = argparse.ArgumentParser(prog="dsengine", description="Validate and replay Data Studio recipes.")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("browser", "login", "check"):
        commands.add_parser(name)
    for name in ("validate", "print", "run"):
        command = commands.add_parser(name)
        command.add_argument("recipe", type=Path)
        if name == "run":
            command.add_argument("--dry-run", action="store_true")
            command.add_argument("--screens", type=Path)
            command.add_argument("--screencast", action="store_true")
            command.add_argument("--timeout", type=_positive_seconds,
                                 default=os.environ.get("DSS_ENGINE_TIMEOUT_S", "600"))
    args = parser.parse_args(argv)
    events = EventWriter()
    if args.command in {"browser", "login", "check"}:
        from dsengine import chrome
        try:
            config = chrome.ChromeConfig.from_env()
            if args.command == "browser":
                chrome.ensure_browser(config)
                return 0
            if args.command == "login":
                return 0 if chrome.login(config) else 3
            print(json.dumps(chrome.check(config)), flush=True)
            return 0
        except chrome.ChromeError as exc:
            print(f"ERROR dsengine.chrome: {exc}", file=sys.stderr)
            events.error(str(exc))
            return 1
    try:
        recipe = load_recipe(args.recipe)
    except RecipeError as exc:
        print(f"ERROR dsengine.recipe: {exc}", file=sys.stderr)
        if args.command == "run":
            events.error(str(exc))
        return 2
    if args.command == "validate":
        return 0
    if args.command == "print":
        for line in recipe_commands(recipe):
            print(line)
        return 0
    return run_recipe(recipe, events, dry_run=args.dry_run,
                      screens=args.screens or recipe.path.parent / "screens",
                      screencast=args.screencast, timeout=args.timeout)


if __name__ == "__main__":
    raise SystemExit(main())
