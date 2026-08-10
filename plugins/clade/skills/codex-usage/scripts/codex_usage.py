#!/usr/bin/env python3
"""Codex rate-limit usage and Clade-style pace indicator.

The helper deliberately delegates authentication to ``codex app-server``. It
never reads Codex's credential file or calls a private account endpoint.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import selectors
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any


TARGET_RATE = 0.95
APP_SERVER_TIMEOUT = 10.0
FULL_STATUS_LINE = [
    "model-with-reasoning",
    "context-remaining",
    "five-hour-limit",
    "weekly-limit",
    "git-branch",
    "current-dir",
]
# `project-name` (short repo name) instead of `current-dir` (full path): the
# Codex footer truncates from the right, and a long working-directory path pushes
# the weekly-limit usage field off-screen. Keeping the location field compact and
# the usage field last preserves the `project · branch · usage` reading order while
# leaving the important pace figure visible on narrow panes.
MINIMAL_STATUS_LINE = ["project-name", "git-branch", "weekly-limit"]
USAGE_ITEMS = ("five-hour-limit", "weekly-limit")
STYLES = ("minimal", "icon", "detail")
THEMES = {
    "circles": ("○", "◑", "●", "◉"),
    "plain": ("--", "-", "+", "++"),
    "bird": ("🥚", "🐣", "🐥", "🦢"),
    "moon": ("🌑", "🌙", "🌛", "🌝"),
    "weather": ("🌩️", "🌧️", "🌤️", "🌈"),
    "mood": ("🫠", "😐", "😊", "🤩"),
    "coffee": ("😴", "☕", "💪", "⚡"),
    "rocket": ("🌍", "🚀", "🛸", "⭐"),
    "ocean": ("🫧", "🐠", "🐬", "🐋"),
    "dragon": ("🥚", "🦎", "🐉", "👑"),
}


class UsageError(RuntimeError):
    """A user-actionable Codex usage error."""


def codex_home() -> Path:
    return Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")).expanduser()


def _messages() -> list[dict[str, Any]]:
    return [
        {
            "method": "initialize",
            "id": 1,
            "params": {
                "clientInfo": {
                    "name": "clade_usage",
                    "title": "Clade Usage",
                    "version": "0.1.0",
                }
            },
        },
        {"method": "initialized", "params": {}},
        {"method": "account/rateLimits/read", "id": 2},
    ]


def fetch_rate_limits(timeout: float = APP_SERVER_TIMEOUT) -> dict[str, Any]:
    """Read an authenticated snapshot through Codex's public app-server RPC."""
    try:
        process = subprocess.Popen(
            ["codex", "app-server", "--stdio"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            bufsize=1,
        )
    except FileNotFoundError as exc:
        raise UsageError("Codex CLI is not installed or is not on PATH.") from exc

    if process.stdin is None or process.stdout is None:
        process.kill()
        raise UsageError("Could not open the Codex app-server transport.")

    try:
        for message in _messages():
            process.stdin.write(json.dumps(message, separators=(",", ":")) + "\n")
        process.stdin.flush()

        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                ready = selector.select(max(0.0, deadline - time.monotonic()))
                if not ready:
                    break
                line = process.stdout.readline()
                if not line:
                    break
                try:
                    response = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if response.get("id") != 2:
                    continue
                if "error" in response:
                    message = response["error"].get(
                        "message", "unknown app-server error"
                    )
                    raise UsageError(
                        f"Codex could not read account rate limits: {message}"
                    )
                result = response.get("result")
                if not isinstance(result, dict):
                    raise UsageError("Codex returned an invalid rate-limit response.")
                return result
        raise UsageError("Timed out while reading Codex rate limits.")
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2)


def _window_label(duration_mins: int | None) -> str:
    if not duration_mins:
        return "limit"
    if duration_mins % 10080 == 0:
        weeks = duration_mins // 10080
        return "week" if weeks == 1 else f"{weeks}w"
    if duration_mins % 1440 == 0:
        days = duration_mins // 1440
        return "day" if days == 1 else f"{days}d"
    if duration_mins % 60 == 0:
        return f"{duration_mins // 60}h"
    return f"{duration_mins}m"


def _remaining(resets_at: int | None, now: float) -> str:
    if not resets_at:
        return "?"
    seconds = max(0.0, resets_at - now)
    minutes = seconds / 60
    if minutes < 60:
        return f"{int(minutes)}m"
    hours = minutes / 60
    if hours < 24:
        return f"{hours:.0f}h"
    days = hours / 24
    return f"{days:.1f}d" if days < 2 else f"{days:.0f}d"


def _pace(window: dict[str, Any], now: float) -> tuple[float, float]:
    used = float(window.get("usedPercent") or 0)
    duration = window.get("windowDurationMins")
    resets_at = window.get("resetsAt")
    if not duration or not resets_at:
        return 0.0, 0.0
    started_at = float(resets_at) - float(duration) * 60
    elapsed = max(0.0, min(100.0, (now - started_at) / (duration * 60) * 100))
    delta = used - elapsed * TARGET_RATE
    projected = used / elapsed * 100 if elapsed > 0 else 0.0
    return delta, projected


def _theme_name() -> str:
    path = codex_home() / ".clade-usage-theme"
    try:
        name = path.read_text(encoding="utf-8").strip()
    except OSError:
        name = "circles"
    return name if name in THEMES else "circles"


def _style_name() -> str:
    path = codex_home() / ".clade-usage-style"
    try:
        name = path.read_text(encoding="utf-8").strip()
    except OSError:
        name = "minimal"
    return name if name in STYLES else "minimal"


def _symbol(delta: float, theme: str) -> str:
    symbols = THEMES[theme]
    if delta < -15:
        return symbols[0]
    if delta < -5:
        return symbols[1]
    if delta < 5:
        return symbols[2]
    return symbols[3]


def normalize(snapshot: dict[str, Any], now: float | None = None) -> list[dict[str, Any]]:
    """Flatten rate-limit buckets into stable, display-ready rows."""
    now = time.time() if now is None else now
    buckets = snapshot.get("rateLimitsByLimitId")
    if not isinstance(buckets, dict) or not buckets:
        single = snapshot.get("rateLimits")
        buckets = {"codex": single} if isinstance(single, dict) else {}

    rows: list[dict[str, Any]] = []
    for bucket_id, bucket in buckets.items():
        if not isinstance(bucket, dict):
            continue
        bucket_name = bucket.get("limitName") or (
            "Codex" if bucket_id == "codex" else str(bucket_id)
        )
        for key in ("primary", "secondary"):
            window = bucket.get(key)
            if not isinstance(window, dict):
                continue
            duration = window.get("windowDurationMins")
            delta, projected = _pace(window, now)
            rounded_delta = round(delta, 1)
            if rounded_delta == 0:
                rounded_delta = 0.0
            rows.append(
                {
                    "limit_id": bucket_id,
                    "name": bucket_name,
                    "window": _window_label(duration),
                    "duration_mins": duration,
                    "used_percent": int(window.get("usedPercent") or 0),
                    "remaining_percent": max(0, 100 - int(window.get("usedPercent") or 0)),
                    "resets_at": window.get("resetsAt"),
                    "resets_in": _remaining(window.get("resetsAt"), now),
                    "pace_delta": rounded_delta,
                    "projected_percent": round(projected, 1),
                }
            )
    return sorted(rows, key=lambda row: (row["limit_id"] != "codex", row["name"], row["window"]))


def _project_context(cwd: Path | None = None) -> tuple[str, str | None]:
    cwd = (cwd or Path.cwd()).resolve()
    project_root = cwd
    try:
        root_result = subprocess.run(
            ["git", "-C", str(cwd), "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
        if root_result.returncode == 0 and root_result.stdout.strip():
            project_root = Path(root_result.stdout.strip())
        result = subprocess.run(
            ["git", "-C", str(cwd), "branch", "--show-current"],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
        branch = result.stdout.strip() if result.returncode == 0 else ""
        if not branch:
            result = subprocess.run(
                ["git", "-C", str(cwd), "rev-parse", "--short", "HEAD"],
                capture_output=True,
                text=True,
                timeout=2,
                check=False,
            )
            branch = result.stdout.strip() if result.returncode == 0 else ""
    except (FileNotFoundError, subprocess.SubprocessError):
        branch = ""
    project = project_root.name or str(project_root)
    return project, branch or None


def _compact_delta(delta: float) -> tuple[str, int]:
    display_delta = round(delta)
    if display_delta == 0:
        display_delta = 0
    sign = "+" if display_delta >= 0 else ""
    return sign, display_delta


def format_rows(
    rows: list[dict[str, Any]],
    theme: str | None = None,
    style: str | None = None,
    project: str | None = None,
    branch: str | None = None,
) -> str:
    if not rows:
        return "No Codex rate-limit windows are available for this account."
    theme = theme or _theme_name()
    style = style or _style_name()
    if style not in STYLES:
        raise UsageError(f"Unknown style: {style}.")

    primary = rows[0]
    delta = float(primary["pace_delta"])
    sign, display_delta = _compact_delta(delta)
    if project is None:
        project, detected_branch = _project_context()
        branch = branch or detected_branch
    context = f"{project} git:({branch})" if branch else str(project)
    if style == "minimal":
        return f"{context}{sign}{display_delta}% ({primary['resets_in']})"
    if style == "icon":
        return (
            f"{context} {_symbol(delta, theme)} "
            f"{sign}{display_delta}% ({primary['resets_in']})"
        )

    lines = []
    for row in rows:
        delta = float(row["pace_delta"])
        sign, display_delta = _compact_delta(delta)
        lines.append(
            f"{row['name']} {row['window']}: {row['used_percent']}% used · "
            f"{_symbol(delta, theme)} {sign}{display_delta}% pace · "
            f"resets in {row['resets_in']}"
        )
    return "\n".join(lines)


def _merge_status_line(text: str, layout: str = "merge") -> tuple[str, bool]:
    """Add native usage fields while preserving the user's existing fields."""
    if layout not in {"merge", "minimal", "full"}:
        raise UsageError(f"Unknown status-line layout: {layout}.")
    selected = MINIMAL_STATUS_LINE if layout == "minimal" else FULL_STATUS_LINE
    table_matches = list(re.finditer(r"(?m)^\s*\[([^]]+)]\s*(?:#.*)?$", text))
    tui_match = next((m for m in table_matches if m.group(1).strip() == "tui"), None)
    if tui_match is None:
        prefix = text.rstrip()
        separator = "\n\n" if prefix else ""
        setting = json.dumps(selected if layout != "merge" else FULL_STATUS_LINE)
        return f"{prefix}{separator}[tui]\nstatus_line = {setting}\n", True

    section_end = len(text)
    for match in table_matches:
        if match.start() > tui_match.start():
            section_end = match.start()
            break
    section = text[tui_match.end() : section_end]
    setting_match = re.search(r"(?m)^(\s*)status_line\s*=\s*(\[[^\n]*])\s*(?:#.*)?$", section)
    if setting_match is None:
        if re.search(r"(?m)^\s*status_line\s*=", section):
            raise UsageError(
                "Existing tui.status_line uses a multi-line or unsupported format; "
                "run /statusline and add five-hour-limit plus weekly-limit manually."
            )
        insertion = "\nstatus_line = " + json.dumps(
            selected if layout != "merge" else FULL_STATUS_LINE
        ) + "\n"
        absolute = tui_match.end()
        return text[:absolute] + insertion + text[absolute:], True

    try:
        items = json.loads(setting_match.group(2))
    except json.JSONDecodeError as exc:
        raise UsageError("Existing tui.status_line is not a simple string array.") from exc
    if not isinstance(items, list) or not all(isinstance(item, str) for item in items):
        raise UsageError("Existing tui.status_line is not a string array.")

    if layout == "merge":
        merged = list(items)
        # Insert the usage fields before whichever location field appears first
        # (`current-dir` or `project-name`) so a long path can be truncated on the
        # right without hiding the usage percentages; otherwise append at the end.
        location_positions = [
            merged.index(field)
            for field in ("current-dir", "project-name")
            if field in merged
        ]
        insert_at = min(location_positions, default=len(merged))
        for item in USAGE_ITEMS:
            if item not in merged:
                merged.insert(insert_at, item)
                insert_at += 1
    else:
        merged = list(selected)
    if merged == items:
        return text, False

    replacement = f"{setting_match.group(1)}status_line = {json.dumps(merged)}"
    start = tui_match.end() + setting_match.start()
    end = tui_match.end() + setting_match.end()
    return text[:start] + replacement + text[end:], True


def setup_status_line(path: Path | None = None, layout: str = "merge") -> bool:
    path = path or codex_home() / "config.toml"
    try:
        original = path.read_text(encoding="utf-8")
        original_mode = path.stat().st_mode & 0o777
    except FileNotFoundError:
        original = ""
        original_mode = 0o600
    updated, changed = _merge_status_line(original, layout=layout)
    if not changed:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.clade-",
            delete=False,
        ) as handle:
            handle.write(updated)
            temporary = Path(handle.name)
        temporary.chmod(original_mode)
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return True


def set_theme(name: str | None) -> int:
    if not name or name == "list":
        current = _theme_name()
        print("Available themes:")
        for candidate, symbols in THEMES.items():
            marker = "→" if candidate == current else " "
            print(f"{marker} {candidate:<9} {''.join(symbols)}")
        return 0
    if name not in THEMES:
        raise UsageError(f"Unknown theme: {name}. Run with `theme` to list themes.")
    path = codex_home() / ".clade-usage-theme"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(name + "\n", encoding="utf-8")
    print(f"Codex usage theme: {name}  {''.join(THEMES[name])}")
    return 0


def set_style(name: str | None) -> int:
    if not name or name == "list":
        current = _style_name()
        print("Available styles:")
        examples = {
            "minimal": "project git:(main)-9% (6d)",
            "icon": "project git:(main) 🐥 -9% (6d)",
            "detail": "Codex week: 42% used · 🐥 -9% pace · resets in 6d",
        }
        for candidate in STYLES:
            marker = "→" if candidate == current else " "
            print(f"{marker} {candidate:<7} {examples[candidate]}")
        return 0
    if name not in STYLES:
        raise UsageError(f"Unknown style: {name}. Run with `style` to list styles.")
    path = codex_home() / ".clade-usage-style"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(name + "\n", encoding="utf-8")
    print(f"Codex usage style: {name}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command", nargs="?", choices=("show", "setup", "style", "theme"), default="show"
    )
    parser.add_argument("value", nargs="?")
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args(argv)
    try:
        if args.command == "theme":
            return set_theme(args.value)
        if args.command == "style":
            return set_style(args.value)
        if args.command == "setup":
            layout = args.value or "merge"
            if layout not in {"merge", "minimal", "full"}:
                raise UsageError("Setup layout must be merge, minimal, or full.")
            changed = setup_status_line(layout=layout)
            print(
                f"Codex status line configured with the {layout} layout."
                if changed
                else f"Codex status line already uses the {layout} layout."
            )
            print("Start a new Codex session to reload the footer.\n")
        rows = normalize(fetch_rate_limits())
        print(json.dumps(rows, indent=2) if args.as_json else format_rows(rows))
        return 0
    except UsageError as exc:
        print(f"codex-usage: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
