#!/usr/bin/env python3
"""Kimi Code plan-quota usage and Clade-style pace indicator.

Data path — the DOCUMENTED one. Kimi Code's own local server (`kimi web`)
exposes `GET /api/v1/oauth/usage` (reference/server-api.md, "Login and
usage"), authenticated with the loopback bearer in `~/.kimi-code/server.token`
and answering `{ usages: { limit5h, limit7d, monthTotal, monthCode }, ... }`.
That is Kimi's analogue of `codex app-server` + `account/rateLimits/read`,
and this helper uses it the same way codex_usage.py uses Codex's: a live
instance (registry: `~/.kimi-code/server/instances/`) is reused; otherwise
one is started on a loopback port, asked once, and shut down.

What it deliberately does NOT do: read `~/.kimi-code/credentials/` or call
`api.kimi.com/coding/v1/usages` itself. The OAuth access token there lives
15 minutes and Kimi rotates the refresh token under a cross-process lock; a
foreign refresher racing that lock is exactly how the CLI tombstones the
credential into "re-login required". Letting `kimi web` hold the token means
the refresh stays Kimi's, and a stale token is Kimi's problem, not ours.

Commands:
  show            fetch live and print every quota window (default)
  statusline      footer line for tui.toml [status_line].command — reads the
                  cache only, never the network, and detaches ONE refresh
  refresh         fetch and rewrite the cache (what statusline detaches)
  setup [off]     wire/unwire [status_line].command in ~/.kimi-code/tui.toml
  style [name]    minimal | icon | detail | off   (statusline only)
  theme [name]    the same emoji sets as slt / codex-usage
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

TARGET_RATE = 0.95
BOOT_TIMEOUT = 30.0
REQUEST_TIMEOUT = 8.0
SHUTDOWN_GRACE = 3.0
# Cache TTLs read by `statusline`. A refresh costs one `kimi web` boot (~1 s,
# ~600 MB for its lifetime) unless an instance is already running, so the
# hot path refreshes only when this session did work since the last fetch
# (contextTokens moved), and otherwise no more than every HARD_TTL — usage
# from another device is real, but nobody is watching it here.
CACHE_TTL = 300
CACHE_HARD_TTL = 1800
ERROR_BACKOFF = 600
PENDING_TTL = 90

CACHE_NAME = ".clade-usage-cache.json"
LOCK_NAME = ".clade-usage-refresh.lock"
THEME_NAME = ".clade-usage-theme"
STYLE_NAME = ".clade-usage-style"
SERVER_TOKEN_NAME = "server.token"
STATUS_LINE_SCRIPT = ("hooks", "statusline.sh")
OUR_COMMAND_MARKER = "statusline.sh"

STYLES = ("minimal", "icon", "detail", "off")
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
# (payload key, label, window length in seconds; None = calendar month)
WINDOWS: tuple[tuple[str, str, int | None], ...] = (
    ("limit5h", "5h", 5 * 3600),
    ("limit7d", "week", 7 * 86400),
    ("monthTotal", "month", None),
)
PERMISSION_BADGES = {"yolo": "Ask When Needed", "auto": "Never Ask"}

RESET = "\033[0m"
DIM = "\033[2m"


class UsageError(RuntimeError):
    """A user-actionable Kimi usage error."""


class ServerUnreachable(UsageError):
    """A registered `kimi web` instance did not answer as a kimi web server.

    The one failure worth retrying on a fresh instance. An in-band `kind:
    "error"` (not logged in, upstream 5xx) comes from Kimi's account service
    and would be the same from any instance, so it is reported, not retried.
    """


# ─── Paths ───


def kimi_home() -> Path:
    return Path(os.environ.get("KIMI_CODE_HOME") or Path.home() / ".kimi-code").expanduser()


def cache_path(home: Path | None = None) -> Path:
    return (home or kimi_home()) / CACHE_NAME


def status_line_script(home: Path | None = None) -> Path:
    return (home or kimi_home()).joinpath(*STATUS_LINE_SCRIPT)


# ─── Server discovery and lifecycle ───


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def live_instances(home: Path | None = None) -> list[dict[str, Any]]:
    """Instances registered by running `kimi web` servers, loopback only.

    Mirrors Kimi's own liveness rule (the pid answers), oldest first.
    """
    directory = (home or kimi_home()) / "server" / "instances"
    found: list[dict[str, Any]] = []
    try:
        names = sorted(directory.iterdir())
    except OSError:
        return found
    for path in names:
        if path.suffix != ".json":
            continue
        try:
            info = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(info, dict):
            continue
        pid, port = info.get("pid"), info.get("port")
        if not isinstance(pid, int) or not isinstance(port, int) or not _pid_alive(pid):
            continue
        host = str(info.get("host") or "127.0.0.1")
        if host not in ("127.0.0.1", "localhost", "0.0.0.0", "::1", "::"):
            continue
        found.append({"pid": pid, "port": port, "started_at": info.get("startedAt") or 0})
    found.sort(key=lambda row: row["started_at"])
    return found


def read_server_token(home: Path | None = None) -> str | None:
    try:
        token = ((home or kimi_home()) / SERVER_TOKEN_NAME).read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return token or None


def _http_json(url: str, token: str | None, timeout: float, method: str = "GET") -> tuple[int, Any]:
    import urllib.error
    import urllib.request

    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read()
            status = response.status
    except urllib.error.HTTPError as exc:
        body = exc.read()
        status = exc.code
    try:
        return status, json.loads(body or b"null")
    except ValueError:
        return status, None


def _healthy(port: int, timeout: float = 1.0) -> bool:
    try:
        status, _ = _http_json(f"http://127.0.0.1:{port}/api/v1/healthz", None, timeout)
    except OSError:
        return False
    return status == 200


def _free_port() -> int:
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class SpawnedServer:
    """One `kimi web --no-open` on a loopback port, torn down on exit."""

    def __init__(self, home: Path, boot_timeout: float = BOOT_TIMEOUT) -> None:
        self.home = home
        self.boot_timeout = boot_timeout
        self.port: int | None = None
        self.process: Any = None

    def __enter__(self) -> SpawnedServer:
        import shutil
        import subprocess

        kimi = shutil.which("kimi")
        if kimi is None:
            raise UsageError("Kimi Code CLI is not installed or is not on PATH.")
        env = dict(os.environ)
        # A helper booting a server every few minutes must never become the
        # thing that downloads a 180 MB update in the background.
        env["KIMI_CODE_NO_AUTO_UPDATE"] = "1"
        # Nor should a headless quota probe count as product usage, or be
        # the instance a user's scheduled task decides to fire from.
        env["KIMI_DISABLE_TELEMETRY"] = "1"
        env["KIMI_DISABLE_CRON"] = "1"
        env["KIMI_CODE_HOME"] = str(self.home)
        requested = _free_port()
        try:
            self.process = subprocess.Popen(
                [kimi, "web", "--no-open", "--port", str(requested)],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=env,
            )
        except OSError as exc:
            raise UsageError(f"Could not start `kimi web`: {exc}") from exc
        deadline = time.monotonic() + self.boot_timeout
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                raise UsageError(
                    f"`kimi web` exited with status {self.process.returncode} before serving."
                )
            # The server registers itself before it listens, and may have
            # moved to port+1 if ours was taken meanwhile: trust the registry
            # entry carrying our pid, then wait for it to answer.
            for info in live_instances(self.home):
                if info["pid"] == self.process.pid and _healthy(info["port"]):
                    self.port = info["port"]
                    return self
            time.sleep(0.1)
        raise UsageError("Timed out waiting for `kimi web` to start.")

    def __exit__(self, *_exc: object) -> None:
        process = self.process
        if process is None or process.poll() is not None:
            return
        token = read_server_token(self.home)
        if self.port is not None:
            try:
                _http_json(
                    f"http://127.0.0.1:{self.port}/api/v1/shutdown", token, 2.0, method="POST"
                )
            except OSError:
                pass
        try:
            process.wait(timeout=SHUTDOWN_GRACE)
            return
        except Exception:
            pass
        process.terminate()
        try:
            process.wait(timeout=2)
        except Exception:
            process.kill()
            process.wait(timeout=2)


def _usage_from(port: int, token: str | None) -> dict[str, Any]:
    try:
        status, envelope = _http_json(
            f"http://127.0.0.1:{port}/api/v1/oauth/usage", token, REQUEST_TIMEOUT
        )
    except OSError as exc:
        raise ServerUnreachable(f"Could not reach kimi web on port {port}: {exc}") from exc
    if status == 401:
        raise UsageError(
            "kimi web rejected the server token in ~/.kimi-code/server.token; "
            "run `kimi web rotate-token` and retry."
        )
    if status != 200 or not isinstance(envelope, dict):
        raise ServerUnreachable(f"kimi web answered HTTP {status} for /api/v1/oauth/usage.")
    if envelope.get("code") != 0:
        raise UsageError(f"kimi web error {envelope.get('code')}: {envelope.get('msg')}")
    data = envelope.get("data")
    if not isinstance(data, dict):
        raise UsageError("kimi web returned an invalid usage envelope.")
    if data.get("kind") == "error":
        raise UsageError(f"Kimi could not read plan usage: {data.get('message')}")
    quota = data.get("quota")
    if data.get("kind") != "ok" or not isinstance(quota, dict):
        raise UsageError("kimi web returned an invalid usage payload.")
    return quota


def fetch_quota(home: Path | None = None) -> tuple[dict[str, Any], str]:
    """Return (quota, source). Reuses a live `kimi web`, else spawns one."""
    home = home or kimi_home()
    if not home.is_dir():
        raise UsageError(f"{home} does not exist — run `kimi` once to log in first.")
    token = read_server_token(home)
    for info in live_instances(home):
        if not _healthy(info["port"]):
            continue
        try:
            return _usage_from(info["port"], token), f"via the running kimi web on 127.0.0.1:{info['port']}"
        except ServerUnreachable:
            continue  # a registry entry that is not (any more) a kimi web: try the next, then our own
    with SpawnedServer(home) as server:
        assert server.port is not None
        return _usage_from(server.port, read_server_token(home)), "via a kimi web started for this call"


# ─── Normalisation and pace ───


def _parse_iso(value: Any) -> float | None:
    if not isinstance(value, str) or not value:
        return None
    from datetime import datetime, timezone

    text = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()


def _month_period(resets_at: float) -> float:
    """Seconds in the billing month that ENDS at resets_at (day clamped)."""
    import calendar
    from datetime import datetime, timezone

    end = datetime.fromtimestamp(resets_at, timezone.utc)
    year, month = (end.year, end.month - 1) if end.month > 1 else (end.year - 1, 12)
    day = min(end.day, calendar.monthrange(year, month)[1])
    start = end.replace(year=year, month=month, day=day)
    return max(1.0, (end - start).total_seconds())


def _remaining(resets_at: float | None, now: float) -> str:
    if resets_at is None:
        return "?"
    minutes = max(0.0, resets_at - now) / 60
    if minutes < 60:
        return f"{int(minutes)}m"
    hours = minutes / 60
    if hours < 24:
        return f"{hours:.0f}h"
    days = hours / 24
    return f"{days:.1f}d" if days < 2 else f"{days:.0f}d"


def _ratio(value: Any) -> float | None:
    try:
        ratio = float(value)
    except (TypeError, ValueError):
        return None
    return ratio if ratio == ratio else None  # NaN guard


def normalize(quota: dict[str, Any], now: float | None = None) -> list[dict[str, Any]]:
    """Flatten Kimi's quota windows into display-ready rows, payload order.

    `monthCode` is a breakdown of `monthTotal` (the TUI shows it as
    "kimi N% · code N%"), so it rides on the month row instead of being one.
    """
    now = time.time() if now is None else now
    usages = quota.get("usages")
    if not isinstance(usages, dict):
        return []
    rows: list[dict[str, Any]] = []
    for key, label, fixed_period in WINDOWS:
        entry = usages.get(key)
        if not isinstance(entry, dict):
            continue
        ratio = _ratio(entry.get("usedRatio"))
        if ratio is None:
            continue
        used = max(0.0, ratio * 100)
        resets_at = _parse_iso(entry.get("resetAt"))
        period_s = float(fixed_period) if fixed_period else (
            _month_period(resets_at) if resets_at else 30 * 86400.0
        )
        if resets_at is None:
            elapsed = 0.0
        else:
            elapsed = max(0.0, min(100.0, (now - (resets_at - period_s)) / period_s * 100))
        delta = used - elapsed * TARGET_RATE
        projected = used / elapsed * 100 if elapsed > 0 else 0.0
        row: dict[str, Any] = {
            "id": key,
            "window": label,
            "period_s": int(period_s),
            "used_percent": round(used, 1),
            "remaining_percent": round(max(0.0, 100 - used), 1),
            "resets_at": resets_at,
            "resets_in": _remaining(resets_at, now),
            "elapsed_percent": round(elapsed, 1),
            "pace_delta": round(delta, 1) + 0.0,
            "projected_percent": round(projected, 1),
        }
        if key == "monthTotal":
            code = _ratio((usages.get("monthCode") or {}).get("usedRatio"))
            if code is not None:
                code_pct = max(0.0, min(used, code * 100))
                row["code_percent"] = round(code_pct, 1)
                row["kimi_percent"] = round(used - code_pct, 1)
        rows.append(row)
    return rows


def pace_row(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The window a 95% target makes sense for: weekly if present, else month."""
    for window in ("week", "month"):
        for row in rows:
            if row["window"] == window:
                return row
    return None


def burst_row(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    for row in rows:
        if row["window"] == "5h":
            return row
    return None


def extra_usage(quota: dict[str, Any]) -> dict[str, Any] | None:
    wallet = quota.get("extraUsage")
    return wallet if isinstance(wallet, dict) else None


# ─── Presentation ───


def _theme_name(home: Path | None = None) -> str:
    try:
        name = ((home or kimi_home()) / THEME_NAME).read_text(encoding="utf-8").strip()
    except OSError:
        name = "circles"
    return name if name in THEMES else "circles"


def _style_name(home: Path | None = None) -> str:
    try:
        name = ((home or kimi_home()) / STYLE_NAME).read_text(encoding="utf-8").strip()
    except OSError:
        name = "icon"
    return name if name in STYLES else "icon"


def _symbol(delta: float, theme: str) -> str:
    symbols = THEMES[theme]
    if delta < -15:
        return symbols[0]
    if delta < -5:
        return symbols[1]
    if delta < 5:
        return symbols[2]
    return symbols[3]


def _signed(delta: float) -> str:
    display = int(round(delta)) or 0
    return f"{'+' if display >= 0 else ''}{display}%"


def _pace_color(projected: float) -> str:
    # Same muted gradient as the Claude Code status line: soft red at 0%
    # projected, amber at 50%, sage green at 95%, a shade brighter past 100%.
    if projected > 100:
        return "\033[38;2;85;160;85m"
    p = max(0.0, min(projected, 95.0))
    if p <= 50:
        t = p / 50.0
        r, g, b = 160, int(75 + 50 * t), int(75 - 20 * t)
    else:
        t = (p - 50.0) / 45.0
        r, g, b = int(160 - 90 * t), int(125 + 20 * t), int(55 + 15 * t)
    return f"\033[38;2;{r};{g};{b}m"


def _burst_color(used: float) -> str:
    if used >= 85:
        return "\033[38;2;185;28;28m"
    if used >= 50:
        return "\033[38;2;217;119;6m"
    return DIM


def usage_segment(
    rows: list[dict[str, Any]], style: str, theme: str, now: float | None = None, color: bool = True
) -> str:
    """The quota part of the footer line; empty when there is nothing to say."""
    now = time.time() if now is None else now
    if style == "off":
        return ""
    pace = pace_row(rows)
    burst = burst_row(rows)
    parts: list[str] = []
    if pace is not None:
        resets_at = pace.get("resets_at")
        delta = float(pace["pace_delta"])
        sym = _symbol(delta, theme)
        col = _pace_color(float(pace["projected_percent"])) if color else ""
        end = RESET if color else ""
        if isinstance(resets_at, (int, float)) and resets_at < now:
            # Last cycle's numbers: neutral symbol, dimmed, no pace claimed.
            neutral = THEMES[theme][2]
            parts.append(f"{DIM}{neutral} (?){RESET}" if color else f"{neutral} (?)")
        else:
            left = _remaining(resets_at if isinstance(resets_at, (int, float)) else None, now)
            label = f"{pace['window']} " if style == "detail" else ""
            icon = f"{sym} " if style in ("icon", "detail") else ""
            parts.append(f"{icon}{label}{col}{_signed(delta)}{end} ({left})")
    if burst is not None and style != "minimal":
        used = float(burst["used_percent"])
        resets_at = burst.get("resets_at")
        left = _remaining(resets_at if isinstance(resets_at, (int, float)) else None, now)
        text = f"5h {int(round(used))}% ({left})"
        parts.append(f"{_burst_color(used)}{text}{RESET}" if color else text)
    elif burst is not None:
        parts.append(f"5h {int(round(float(burst['used_percent'])))}%")
    return " · ".join(parts)


def format_rows(rows: list[dict[str, Any]], theme: str, now: float | None = None) -> str:
    """The `show` report: one line per window, like `/usage` plus pace."""
    if not rows:
        return "No Kimi Code plan-usage windows are available for this account."
    now = time.time() if now is None else now
    labels = {"5h": "5h limit", "week": "Weekly limit", "month": "Monthly limit"}
    width = max(len(labels[row["window"]]) for row in rows)
    lines = []
    for row in rows:
        used = int(round(float(row["used_percent"])))
        line = f"  {labels[row['window']].ljust(width)}  {used:>3}% used"
        if row["window"] != "5h":
            delta = float(row["pace_delta"])
            line += f" · {_symbol(delta, theme)} {_signed(delta)} pace"
        line += f" · resets in {row['resets_in']}"
        if "code_percent" in row:
            kimi = int(round(float(row["kimi_percent"])))
            code = int(round(float(row["code_percent"])))
            line += f" · kimi {kimi}% · code {code}%"
        lines.append(line)
    return "\n".join(lines)


def format_extra_usage(wallet: dict[str, Any] | None) -> str:
    if not wallet:
        return ""
    currency = str(wallet.get("currency") or "")
    symbol = {"CNY": "¥", "USD": "$"}.get(currency.upper(), "")

    def money(cents: Any) -> str:
        try:
            amount = int(cents) / 100
        except (TypeError, ValueError):
            return "?"
        return f"{symbol}{amount:.2f}" if symbol else f"{amount:.2f} {currency}"

    used = money(wallet.get("monthlyUsedCents"))
    balance = money(wallet.get("balanceCents"))
    if wallet.get("monthlyChargeLimitEnabled") and int(wallet.get("monthlyChargeLimitCents") or 0) > 0:
        limit = money(wallet.get("monthlyChargeLimitCents"))
        return f"  Extra usage   {used} of {limit} this month · balance {balance}"
    return f"  Extra usage   {used} this month · no monthly limit · balance {balance}"


def _dict_field(data: dict[str, Any] | None, key: str) -> dict[str, Any]:
    value = data.get(key) if data else None
    return value if isinstance(value, dict) else {}


def _rows_field(data: dict[str, Any] | None) -> list[dict[str, Any]]:
    value = data.get("rows") if data else None
    return [row for row in value if isinstance(row, dict)] if isinstance(value, list) else []


# ─── Cache ───


def read_cache(home: Path | None = None) -> dict[str, Any] | None:
    try:
        data = json.loads(cache_path(home).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def write_cache(data: dict[str, Any], home: Path | None = None) -> None:
    import tempfile

    path = cache_path(home)
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", delete=False
    )
    try:
        with handle:
            json.dump(data, handle, separators=(",", ":"))
        os.chmod(handle.name, 0o600)
        os.replace(handle.name, path)
    except OSError:
        try:
            os.unlink(handle.name)
        except OSError:
            pass


def refresh_cache(
    home: Path | None = None, session_id: str | None = None, context_tokens: int | None = None
) -> dict[str, Any]:
    """Fetch live, rewrite the cache, return it. Errors are recorded, not raised."""
    home = home or kimi_home()
    previous = read_cache(home) or {}
    seen = _dict_field(previous, "seen")
    if session_id:
        seen = dict(list(seen.items())[-19:])
        seen[session_id] = context_tokens
    now = time.time()
    try:
        quota, source = fetch_quota(home)
    except UsageError as exc:
        data = dict(previous)
        data.update({"error": str(exc), "error_at": now, "seen": seen})
        write_cache(data, home)
        return data
    data = {
        "fetched_at": now,
        "source": source,
        "rows": normalize(quota, now),
        "extra_usage": extra_usage(quota),
        "seen": seen,
    }
    write_cache(data, home)
    return data


def _prune_memos(home: Path, max_age: float = 86400.0) -> None:
    """The launcher keeps one replay memo per session; drop day-old ones."""
    now = time.time()
    try:
        for path in home.glob(".clade-usage-memo-*"):
            try:
                if now - path.stat().st_mtime > max_age:
                    path.unlink()
            except OSError:
                pass
    except OSError:
        pass


def _refresh_locked(home: Path, session_id: str | None, context_tokens: int | None) -> int:
    """`refresh` under an advisory lock so concurrent footers spawn ONE server."""
    _prune_memos(home)
    try:
        import fcntl
    except ImportError:
        refresh_cache(home, session_id, context_tokens)
        return 0
    lock_path = home / LOCK_NAME
    try:
        lock = open(lock_path, "a+")
    except OSError:
        refresh_cache(home, session_id, context_tokens)
        return 0
    with lock:  # released when the process ends, however it ends
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return 0
        refresh_cache(home, session_id, context_tokens)
    return 0


# ─── Status line ───


def needs_refresh(
    cache: dict[str, Any] | None, session_id: str | None, context_tokens: Any, now: float
) -> bool:
    if cache is None:
        return True
    if isinstance(cache.get("error_at"), (int, float)) and now - float(cache["error_at"]) < ERROR_BACKOFF:
        return False
    fetched_at = cache.get("fetched_at")
    if not isinstance(fetched_at, (int, float)):
        return True
    age = now - float(fetched_at)
    for row in _rows_field(cache):
        resets_at = row.get("resets_at")
        if isinstance(resets_at, (int, float)) and resets_at < now:
            return True  # a window rolled over; the cached numbers are last cycle's
    if age < CACHE_TTL:
        return False
    if age >= CACHE_HARD_TTL:
        return True
    if not session_id:
        return True
    return _dict_field(cache, "seen").get(session_id) != context_tokens


def _detach_refresh(home: Path, session_id: str | None, context_tokens: Any) -> None:
    """Start `refresh` in its own session so the footer's 300 ms reaper (which
    kills the whole process group) cannot take the server down mid-fetch."""
    import subprocess

    pending = home / (LOCK_NAME + ".pending")
    try:
        if time.time() - pending.stat().st_mtime < PENDING_TTL:
            return
    except OSError:
        pass
    try:
        pending.touch()
    except OSError:
        return
    argv = [sys.executable, os.path.abspath(__file__), "refresh"]
    if session_id:
        argv += ["--session", session_id]
    if isinstance(context_tokens, int):
        argv += ["--context-tokens", str(context_tokens)]
    try:
        subprocess.Popen(
            argv,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            close_fds=True,
        )
    except OSError:
        pass


def _git_branch(cwd: str) -> str | None:
    """Branch name without spawning git: read .git/HEAD (worktrees included)."""
    try:
        path = Path(cwd)
        for candidate in (path, *path.parents):
            git = candidate / ".git"
            if git.is_dir():
                head_path = git / "HEAD"
            elif git.is_file():
                pointer = git.read_text(encoding="utf-8").strip()
                if not pointer.startswith("gitdir: "):
                    return None
                gitdir = Path(pointer[len("gitdir: "):])
                head_path = (gitdir if gitdir.is_absolute() else candidate / gitdir) / "HEAD"
            else:
                continue
            head = head_path.read_text(encoding="utf-8").strip()
            if head.startswith("ref: refs/heads/"):
                return head[len("ref: refs/heads/"):]
            return head[:7] or None
    except OSError:
        return None
    return None


def statusline(payload: dict[str, Any], home: Path | None = None, now: float | None = None) -> str:
    """Footer line 1 for Kimi's [status_line].command — cache in, no network."""
    home = home or kimi_home()
    now = time.time() if now is None else now
    style = _style_name(home)
    if style == "off":
        return ""  # an empty line hands footer line 1 back to Kimi's built-in slots
    session_id = payload.get("sessionId") if isinstance(payload.get("sessionId"), str) else None
    context_tokens = payload.get("contextTokens")
    cache = read_cache(home)
    if needs_refresh(cache, session_id, context_tokens, now):
        _detach_refresh(home, session_id, context_tokens)

    pieces: list[str] = []
    badges = []
    mode = payload.get("permissionMode")
    if isinstance(mode, str) and mode in PERMISSION_BADGES:
        badges.append(PERMISSION_BADGES[mode])
    if payload.get("planMode"):
        badges.append("plan")
    if badges:
        pieces.append("\033[1;33m" + " ".join(f"[{badge}]" for badge in badges) + RESET)
    model = payload.get("model")
    if isinstance(model, str) and model:
        pieces.append(model)
    cwd = payload.get("cwd")
    if isinstance(cwd, str) and cwd:
        location = f"\033[36m{os.path.basename(cwd.rstrip('/')) or cwd}{RESET}"
        branch = payload.get("gitBranch")
        if not isinstance(branch, str) or not branch:
            branch = _git_branch(cwd)
        if branch:
            location += f" \033[1;34mgit:(\033[0;31m{branch}\033[1;34m){RESET}"
        pieces.append(location)
    segment = usage_segment(_rows_field(cache), style, _theme_name(home), now)
    if segment:
        pieces.append(segment)
    elif cache and cache.get("error"):
        pieces.append(f"{DIM}quota ?{RESET}")
    return "  ".join(pieces)


# ─── tui.toml wiring ───


def _default_command(home: Path) -> str:
    script = status_line_script(home)
    if not script.is_file():
        raise UsageError(
            f"{script} is not installed; run Clade's install.sh (it deploys "
            "configs/kimi-hooks/statusline.sh into ~/.kimi-code/hooks/)."
        )
    return str(script)


_TABLE_RE = r"^\s*\[([^\]]+)\]\s*(?:#.*)?$"
_COMMAND_RE = r'^\s*command\s*=\s*"((?:[^"\\]|\\.)*)"\s*(?:#.*)?$'


def _status_line_table(lines: list[str]) -> tuple[int | None, int, int | None, str | None]:
    """(table start, table end, index of its `command` line, that command)."""
    import re

    table_re = re.compile(_TABLE_RE)
    command_re = re.compile(_COMMAND_RE)
    start = None
    for index, line in enumerate(lines):
        match = table_re.match(line)
        if match and match.group(1).strip() == "status_line":
            start = index
            break
    if start is None:
        return None, len(lines), None, None
    end = len(lines)
    for index in range(start + 1, len(lines)):
        if table_re.match(lines[index]):
            end = index
            break
    for index in range(start + 1, end):
        match = command_re.match(lines[index])
        if match:
            return start, end, index, _toml_unescape(match.group(1))
    return start, end, None, None


def status_line_wired(text: str) -> bool:
    """Is an ACTIVE [status_line].command ours? The stock tui.toml carries the
    same path in a comment, so a substring search says yes on every machine."""
    _start, _end, _index, existing = _status_line_table(text.splitlines())
    return existing is not None and OUR_COMMAND_MARKER in existing


def merge_status_line(text: str, command: str | None) -> tuple[str, bool]:
    """Set (or with command=None, remove) our [status_line].command in tui.toml.

    Only whole lines are touched; a `command` that is not ours is never
    overwritten or removed — that is the user's own footer, and Kimi's
    own docs invite them to write one.
    """
    lines = text.splitlines()
    start, _end, index, existing = _status_line_table(lines)
    if start is None:
        if command is None:
            return text, False
        body = text.rstrip("\n")
        block = f'[status_line]\ncommand = "{_toml_escape(command)}"\n'
        return (f"{body}\n\n{block}" if body else block), True
    if index is not None and existing is not None:
        ours = OUR_COMMAND_MARKER in existing
        if command is None:
            if not ours:
                return text, False
            del lines[index]
            # Drop a now-empty table too, so a later hand-written
            # [status_line] does not become a duplicate-table TOML error.
            rest = lines[start + 1 : _end - 1]
            if all(not line.strip() or line.lstrip().startswith("#") for line in rest):
                del lines[start : _end - 1]
                while start > 0 and start <= len(lines) and not lines[start - 1].strip():
                    del lines[start - 1]
                    start -= 1
            return "\n".join(lines).rstrip("\n") + "\n", True
        if existing == command:
            return text, False
        if not ours:
            raise UsageError(
                f"tui.toml already has its own status line command ({existing!r}); "
                "leaving it alone. Remove it by hand to use Clade's."
            )
        lines[index] = f'command = "{_toml_escape(command)}"'
        return "\n".join(lines) + "\n", True
    if command is None:
        return text, False
    lines.insert(start + 1, f'command = "{_toml_escape(command)}"')
    return "\n".join(lines) + "\n", True


def _toml_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _toml_unescape(value: str) -> str:
    return value.replace('\\"', '"').replace("\\\\", "\\")


def setup_status_line(home: Path | None = None, enable: bool = True) -> bool:
    import tempfile

    home = home or kimi_home()
    path = home / "tui.toml"
    try:
        original = path.read_text(encoding="utf-8")
        mode = path.stat().st_mode & 0o777
    except FileNotFoundError:
        original, mode = "", 0o644
    updated, changed = merge_status_line(original, _default_command(home) if enable else None)
    if not changed:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.clade-", delete=False
    )
    with handle:
        handle.write(updated)
    os.chmod(handle.name, mode)
    os.replace(handle.name, path)
    return True


# ─── Commands ───


def set_theme(name: str | None, home: Path) -> int:
    if not name or name == "list":
        current = _theme_name(home)
        print("Available themes:")
        for candidate, symbols in THEMES.items():
            print(f"{'→' if candidate == current else ' '} {candidate:<9} {''.join(symbols)}")
        return 0
    if name not in THEMES:
        raise UsageError(f"Unknown theme: {name}. Run with `theme` to list themes.")
    (home / THEME_NAME).write_text(name + "\n", encoding="utf-8")
    print(f"Kimi usage theme: {name}  {''.join(THEMES[name])}")
    return 0


def set_style(name: str | None, home: Path) -> int:
    examples = {
        "minimal": "Clade git:(main)  +3% (12d) · 5h 40%",
        "icon": "Clade git:(main)  ● +3% (12d) · 5h 40% (3h)",
        "detail": "Clade git:(main)  ● month +3% (12d) · 5h 40% (3h)",
        "off": "Clade git:(main)             (built-in Kimi footer, no quota)",
    }
    if not name or name == "list":
        current = _style_name(home)
        print("Available styles:")
        for candidate in STYLES:
            print(f"{'→' if candidate == current else ' '} {candidate:<7} {examples[candidate]}")
        return 0
    if name not in STYLES:
        raise UsageError(f"Unknown style: {name}. Run with `style` to list styles.")
    (home / STYLE_NAME).write_text(name + "\n", encoding="utf-8")
    print(f"Kimi usage style: {name}")
    return 0


def show(home: Path, as_json: bool) -> int:
    quota, source = fetch_quota(home)
    now = time.time()
    rows = normalize(quota, now)
    wallet = extra_usage(quota)
    write_cache(
        {
            "fetched_at": now,
            "source": source,
            "rows": rows,
            "extra_usage": wallet,
            "seen": _dict_field(read_cache(home), "seen"),
        },
        home,
    )
    if as_json:
        print(json.dumps({"source": source, "rows": rows, "extra_usage": wallet}, indent=2))
        return 0
    print(f"Kimi Code plan usage  ({source})")
    print(format_rows(rows, _theme_name(home), now))
    extra = format_extra_usage(wallet)
    if extra:
        print(extra)
    script = status_line_script(home)
    try:
        wired = status_line_wired((home / "tui.toml").read_text(encoding="utf-8"))
    except OSError:
        wired = False
    state = "wired" if wired else "not wired — run `setup`"
    print(f"Status line: {_style_name(home)} style, {_theme_name(home)} theme ({script.name} {state})")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "command",
        nargs="?",
        choices=("show", "statusline", "refresh", "setup", "style", "theme"),
        default="show",
    )
    parser.add_argument("value", nargs="?")
    parser.add_argument("--json", action="store_true", dest="as_json")
    parser.add_argument("--session", dest="session_id")
    parser.add_argument("--context-tokens", dest="context_tokens", type=int)
    args = parser.parse_args(argv)
    home = kimi_home()
    try:
        if args.command == "statusline":
            try:
                payload = json.load(sys.stdin)
            except (ValueError, OSError):
                payload = {}
            line = statusline(payload if isinstance(payload, dict) else {}, home)
            if line:
                sys.stdout.write(line + "\n")
            return 0
        if args.command == "refresh":
            return _refresh_locked(home, args.session_id, args.context_tokens)
        if args.command == "theme":
            return set_theme(args.value, home)
        if args.command == "style":
            return set_style(args.value, home)
        if args.command == "setup":
            if args.value not in (None, "on", "off"):
                raise UsageError("Setup takes `on` (default) or `off`.")
            enable = args.value != "off"
            changed = setup_status_line(home, enable=enable)
            if enable:
                # Wiring only: install.sh calls this, and an installer must
                # not boot a Kimi server. `show` fetches when the user asks.
                print(
                    "Kimi status line wired to Clade's quota footer."
                    if changed
                    else "Kimi status line already wired to Clade's quota footer."
                )
                print("Start a new Kimi session (or /reload-tui) to see it.")
                return 0
            print(
                "Kimi status line command removed; the built-in footer is back."
                if changed
                else "Kimi tui.toml carried no Clade status line command."
            )
            return 0
        return show(home, args.as_json)
    except UsageError as exc:
        print(f"kimi-usage: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
