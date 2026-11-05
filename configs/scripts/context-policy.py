#!/usr/bin/env python3
"""context-policy.py — Clade's opt-in, upgrade-safe Claude Code context-window policy (why 350000: the policy file).

`apply` (install.sh 8d) writes ONE key, top-level `autoCompactWindow`, only while the sidecar .clade-context-state.json
proves the value is Clade's: any other value, or a deleted key, is the user's from then on (on 2.1.283 `/autocompact N`
overwrites this key and `/autocompact auto` deletes it, so equality, not precedence, protects the user). It steps aside
for every more specific mechanism, retracts its value while Anthropic tunes the window server-side (server_tuning),
fails closed on an unknown or too-old Claude Code, and never touches the network, modelSettings, managed settings, an
env var, Codex or Kimi. `status` is read-only; `uninstall` (uninstall.sh) retracts
as an opt-out does and drops the sidecar; `--check`; `--self-test` (its controls: context_policy_selftest.py).
"""
from __future__ import annotations

import argparse
import contextlib
import functools
import importlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:  # aliases only mypy evaluates: `tuple[...]` at runtime fails on the Python 3.8 install.sh accepts
    from typing import TypeGuard
    Version = tuple[int, int, int]
    Probe = Callable[[], tuple[Optional[Version], str]]
    Managed = list[tuple[str, Optional[dict[str, Any]]]]  # None: the file exists and cannot be read

# ─── Constants ───
SCHEMA, STATE_SCHEMA, STATE_FILE = "clade.context-policy/v1", "clade.context-state/v1", ".clade-context-state.json"
KEY = "autoCompactWindow"
VALUE_MIN, VALUE_MAX = 100_000, 1_000_000  # 2.1.236-2.1.283 schema: int().min(1e5).max(1e6).catch(void 0)
OUTPUT_RESERVE, SUMMARY_BUFFER = 20_000, 13_000  # trigger = W - min(maxOut, 20000) - 13000 (2.1.283 binary)
VERSION_LINE = re.compile(r"^(\d+)\.(\d+)\.(\d+)\b.*\(Claude Code\)")
VERSION_PATH = re.compile(r"/versions/(\d+)\.(\d+)\.(\d+)$")
DOCS_URL = "https://code.claude.com/docs/en/model-config"
# abspath, not resolve(): ~/.claude/scripts may be a symlink into a sync store, and the policy sits beside it.
DEFAULT_POLICY = Path(os.path.abspath(__file__)).parent.parent / "context-policy.json"
FRESH: dict[str, Any] = {"choice": None, "wrote": None, "cc_version": None, "user_removed": False, "user_owned": False}
FLAGS = ("user_removed", "user_owned")


def is_int(x: Any) -> TypeGuard[int]:
    return isinstance(x, int) and not isinstance(x, bool)


def same_int(cur: Any, wrote: Any) -> bool:
    """Ownership is exact equality of two ints: `true` (== 1) or a quoted "350000" is the user's, never Clade's."""
    return is_int(cur) and is_int(wrote) and cur == wrote


def obj(x: Any) -> dict[str, Any]:
    return x if isinstance(x, dict) else {}


# ─── Versions ───
def parse_version(text: Any) -> Optional[Version]:
    hit = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)", text) if isinstance(text, str) else None
    return (int(hit[1]), int(hit[2]), int(hit[3])) if hit else None


def fmt(v: Optional[Version]) -> str:
    return ".".join(str(p) for p in v) if v else "unknown"


def find_claude() -> Optional[str]:
    """PATH, then the installers' own locations by path alone: a non-interactive `ssh host ./install.sh` (as
    fleet-install.sh runs it) never sources the rc file that puts ~/.local/bin on PATH, and no rc file is sourced here."""
    for exe in (shutil.which("claude"), Path.home() / ".local/bin/claude", Path.home() / ".claude/local/claude"):
        if exe and os.path.isfile(exe) and os.access(exe, os.X_OK):
            return str(exe)
    return None


def detect_cc_version() -> tuple[Optional[Version], str]:
    """Every line of `claude --version` is scanned (an interactive wrapper may print a banner first), under a 10 s
    Python timeout (macOS has no timeout(1)) with stdin closed; else a `.../versions/X.Y.Z` realpath; else unknown."""
    exe = find_claude()
    if not exe:
        return None, "Claude Code not found on PATH, in ~/.local/bin or in ~/.claude/local"
    try:
        proc = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=10,
                              stdin=subprocess.DEVNULL)
        for line in proc.stdout.splitlines() if proc.returncode == 0 else []:
            hit = VERSION_LINE.match(line.strip())
            if hit:
                return (int(hit[1]), int(hit[2]), int(hit[3])), "claude --version"
    except (OSError, subprocess.TimeoutExpired):
        pass
    found = VERSION_PATH.search(os.path.realpath(exe))
    return ((int(found[1]), int(found[2]), int(found[3])), f"realpath {found.string}") if found else (
        None, "Claude Code version unreadable")


# ─── Policy file ───
def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def check_policy(policy: Any) -> list[str]:
    """Every rule is one `apply` relies on; an error means install would act on a value nobody verified."""
    if not isinstance(policy, dict) or policy.get("schema") != SCHEMA:
        return [f"schema is not {SCHEMA!r}"]
    e = obj(obj(policy.get("claude_code")).get(KEY))
    if not e:
        return [f"claude_code.{KEY} is missing"]
    errs: list[str] = []
    if not (is_int(e.get("value")) and VALUE_MIN <= e["value"] <= VALUE_MAX):
        errs.append(f"value {e.get('value')!r} is not an int in [{VALUE_MIN}, {VALUE_MAX}]; Claude Code drops it")
    if not isinstance(e.get("enabled_by_default"), bool):
        errs.append("enabled_by_default must be true or false")
    lo, hi = parse_version(e.get("min_cc_version")), parse_version(e.get("verified_through_cc_version"))
    if lo is None or hi is None:
        errs.append("min_cc_version and verified_through_cc_version must be X.Y.Z")
    elif lo > hi:
        errs.append("min_cc_version is above verified_through_cc_version")
    retire = parse_version(e.get("retire_from_cc_version"))
    if e.get("retire_from_cc_version") is not None and (retire is None or lo is None or retire <= lo):
        errs.append("retire_from_cc_version must be null or an X.Y.Z above min_cc_version")
    skip = obj(e.get("skip_when"))
    if not (isinstance(skip.get("model_settings_key"), str)
            and all(isinstance(skip.get(k), list) for k in ("env", "settings_false", "managed_settings"))):
        errs.append("skip_when needs env, settings_false and managed_settings lists and a model_settings_key")
    if not (isinstance(obj(e.get("measurement")).get("population"), str) and e["measurement"]["population"]):
        errs.append("measurement.population must say what the value was measured on")
    for tool, vkey in (("codex", "verified_codex_version"), ("kimi", "verified_kimi_version")):
        block = obj(policy.get(tool))
        if block.get("mode") != "report-only":
            errs.append(f"{tool}.mode must be 'report-only': v1 writes nothing for {tool}")
        elif parse_version(block.get(vkey)) is None:
            errs.append(f"{tool}.{vkey} must be X.Y.Z")
    return errs


# ─── Settings and sidecar IO ───
def mtime_ns(path: Path) -> Optional[int]:
    return os.stat(os.path.realpath(path)).st_mtime_ns if os.path.exists(path) else None


def read_settings(path: Path) -> tuple[dict[str, Any], Optional[int]]:
    """(settings, mtime of the real file). Stat first: any write after it changes the mtime compared later."""
    stamp = mtime_ns(path)
    data = json.loads(Path(os.path.realpath(path)).read_text(encoding="utf-8")) if stamp is not None else {}
    if not isinstance(data, dict):
        raise ValueError("not a JSON object")
    return data, stamp


def write_atomic(path: Path, text: str) -> None:
    """Temp file beside the REAL file, then os.replace: a symlinked settings.json stays a symlink; mode is kept."""
    real = Path(os.path.realpath(path))
    mode = real.stat().st_mode & 0o7777 if real.exists() else 0o600
    fd, tmp = tempfile.mkstemp(dir=str(real.parent), prefix=f".{real.name}.clade-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.chmod(tmp, mode)
        os.replace(tmp, real)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def load_state(path: Path) -> tuple[dict[str, Any], Optional[str]]:
    """A missing or malformed sidecar owns nothing: every value in settings.json is then the user's."""
    try:
        raw = load_json(path)
        slot = raw["claude_code"][KEY]
        st = {"choice": raw["choice"], "wrote": slot["wrote"], "cc_version": slot["cc_version"],
              **{k: slot[k] for k in FLAGS}}
        valid = raw["schema"] == STATE_SCHEMA and st["choice"] in (None, "in", "out")
        valid = valid and (st["wrote"] is None or is_int(st["wrote"]))
        valid = valid and all(isinstance(st[k], bool) for k in FLAGS)
    except FileNotFoundError:
        return dict(FRESH), None
    except (OSError, ValueError, KeyError, TypeError):
        valid = False
    if not valid:
        return dict(FRESH), "sidecar unreadable or malformed; Clade owns nothing until it writes again"
    return st, None


def load_managed(paths: list[str]) -> Managed:
    """Each managed-settings.json, then the managed-settings.d/*.json drop-ins beside it, which is what 2.1.283 reads
    (sorted, dot-files skipped). One that exists and cannot be read may set anything: None, and Clade steps aside."""
    files: list[str] = []
    for p in paths:
        drop = os.path.join(os.path.dirname(p), "managed-settings.d")
        try:
            names = sorted(n for n in os.listdir(drop) if n.endswith(".json") and not n.startswith("."))
            files += [p, *(os.path.join(drop, n) for n in names)]
        except (FileNotFoundError, NotADirectoryError):
            files.append(p)
        except OSError:  # the drop-in directory exists and cannot be listed: reading it below fails, so it shadows
            files += [p, drop]
    out: Managed = []
    for p in dict.fromkeys(files):
        if os.path.lexists(p):
            data: Any = None
            with contextlib.suppress(OSError, ValueError):
                data = load_json(Path(p))
            out.append((p, data if isinstance(data, dict) else None))
    return out


def server_tuning(claude_dir: Path) -> list[str]:
    """Windows Anthropic pushes for this account, as cached in Claude Code's global config: `autoCompactWindowsCache`
    and the `rowan_thicket` client-data tier (in any clientDataCacheSlots slot, or the legacy clientDataCache that
    2.1.283 falls back to when no slot matches). The settings key outranks both (2.1.283 resolver), so while either is
    a non-empty object Clade retracts its own value and writes nothing: Anthropic's tuning wins. 2.1.283 reads its
    global config from <config dir>/.config.json when that legacy file exists, else $CLAUDE_CONFIG_DIR/.claude.json,
    else ~/.claude.json; every one of them is read here. These are undocumented cache names read from the 2.1.283
    binary: if a later version renames them this sees nothing, and the version re-verify (status NOTICE) is the
    remaining guard. A file that is absent, unreadable or invalid (Claude Code rewrites it constantly) is no signal.
    """
    dirs = [claude_dir]
    if os.environ.get("CLAUDE_CONFIG_DIR"):
        dirs.append(Path(os.environ["CLAUDE_CONFIG_DIR"]))
    candidates = [d / name for d in dirs for name in (".claude.json", ".config.json")]
    if claude_dir.name == ".claude":  # the default ~/.claude: the global config is ~/.claude.json beside it
        candidates.append(claude_dir.parent / ".claude.json")
    found: list[str] = []
    for path in dict.fromkeys(Path(os.path.realpath(p)) for p in candidates):
        try:
            cfg = obj(load_json(path))
        except (OSError, ValueError):  # absent, unreadable, or read mid-rewrite: no signal
            continue
        if obj(cfg.get("autoCompactWindowsCache")):
            found.append(f"{path} autoCompactWindowsCache")
        slots = [obj(slot).get("data") for slot in obj(cfg.get("clientDataCacheSlots")).values()]
        if any(obj(obj(data).get("rowan_thicket")) for data in slots):
            found.append(f"{path} clientDataCacheSlots rowan_thicket")
        if obj(obj(cfg.get("clientDataCache")).get("rowan_thicket")):
            found.append(f"{path} clientDataCache rowan_thicket")
    return found


# ─── Decision ───
def skip_reasons(settings: Mapping[str, Any], env: Mapping[str, str], managed: Managed,
                 skip: Mapping[str, Any]) -> list[str]:
    """Every more specific mechanism the user or an admin already chose; Clade steps aside for each."""
    found: list[str] = []
    sources: list[tuple[str, Optional[Mapping[str, Any]]]] = [("settings.json", settings), *managed]
    for name, src in sources:
        if src is None:
            found.append(f"{name} (unreadable, so it may set anything)")
            continue
        senv = obj(src.get("env"))
        found += [f"{name} env.{k}" for k in skip["env"] if k in senv]
        found += [f"{name} {k}: false" for k in skip["settings_false"] if src.get(k) is False]
        mkey = skip["model_settings_key"]
        found += [f"{name} modelSettings.{m}.{mkey}" for m, v in obj(src.get("modelSettings")).items() if mkey in obj(v)]
        if name != "settings.json" and KEY in src:
            found.append(f"{name} {KEY}")
    found += [f"process env {k}" for k in skip["env"] if k in env]
    return found


def decide(settings: dict[str, Any], state: dict[str, Any], entry: Mapping[str, Any], flag: Optional[str],
           env: Mapping[str, str], managed: Managed, probe: Probe,
           server: Optional[list[str]] = None) -> tuple[dict[str, Any], dict[str, Any], list[str]]:
    """Pure apart from `probe`, which runs only when there is something to write or retract."""
    s, st = dict(settings), dict(state)
    out: list[str] = []
    cur, value = s.get(KEY), entry["value"]
    # 1. Re-derive ownership from what the file holds NOW, before the flags, so an opt-in can clear user_removed.
    #    A key that was Clade's or the user's and is gone was deleted by the user (/autocompact auto on 2.1.283).
    if (st["wrote"] is not None or st["user_owned"]) and cur is None:
        st["user_removed"], st["wrote"], st["user_owned"] = True, None, False
        out.append(f"{KEY} was removed by the user; Clade will not write it again (./install.sh --context-policy does)")
    elif st["wrote"] is not None and not same_int(cur, st["wrote"]):
        st["wrote"], st["user_owned"] = None, True
        out.append(f"{KEY}={cur!r} was set by the user; it is theirs now and Clade will not touch it")
    # 2. The choice persists in the sidecar: fleet-install runs ./install.sh with no arguments.
    if flag == "in":
        st["choice"], st["user_removed"] = "in", False
    elif flag == "out":
        st["choice"] = "out"
    enabled = st["choice"] == "in" or (st["choice"] is None and entry["enabled_by_default"] is True)
    owned = st["wrote"] is not None
    # A value present while enabled that Clade did not write is the user's; remembering it is what keeps a later
    # deletion of it from reading as an empty slot to fill.
    st["user_owned"] = st["user_owned"] or (enabled and cur is not None and not owned)
    if not enabled and not owned:
        out.append("off (opted out)" if st["choice"] == "out" else "off by default; opt in: ./install.sh --context-policy")
        return s, st, out
    version, how = probe()
    if version is None:
        out.append(f"Skipped ({how}); settings.json left as it was, nothing written or removed")
        return s, st, out
    lo = parse_version(entry["min_cc_version"]) or (0, 0, 0)
    hi = parse_version(entry["verified_through_cc_version"]) or lo
    retire = parse_version(entry.get("retire_from_cc_version"))
    too_old = version < lo
    retired = retire is not None and version >= retire
    why = ("opted out" if st["choice"] == "out" else "not enabled" if not enabled
           else f"retired from Claude Code {fmt(retire)}" if retired
           else f"Claude Code {fmt(version)} is below the verified floor {fmt(lo)}" if too_old
           else f"Anthropic tunes the window server-side ({', '.join(server)})" if server else "")
    # 3. Retract: only a value Clade still owns, and only for a reason it can name.
    if owned and why:
        del s[KEY]
        st["wrote"] = st["cc_version"] = None
        out.append(f"Removed {KEY} (Clade-owned): {why}")
        return s, st, out
    if why or st["user_removed"]:
        out.append(f"nothing written: {why or 'the user removed the key'}")
        return s, st, out
    shadow = skip_reasons(s, env, managed, entry["skip_when"])
    if shadow:
        out.append("steps aside for " + ", ".join(shadow) + "; nothing written")
        return s, st, out
    if version > hi:
        out.append(f"verified through Claude Code {fmt(hi)}; you run {fmt(version)}: still written (documented, "
                   f"schema-checked); re-verify with python3 ~/.claude/scripts/context-policy.py status ({DOCS_URL})")
    # 4. Write when absent, or update a value Clade still owns; a user value is never rewritten.
    if cur is None or (owned and cur != value):
        s[KEY], st["wrote"], st["cc_version"] = value, value, fmt(version)
        out.append(f"set {KEY} = {value} (Claude Code {fmt(version)}, {how}); compaction near "
                   f"{value - OUTPUT_RESERVE - SUMMARY_BUFFER:,} tokens on a 1M model")
    else:
        out.append(f"{KEY} = {cur} ({'Clade-owned, unchanged' if owned else 'the user value, left alone'})")
    return s, st, out


# ─── apply ───
def cmd_apply(claude_dir: Path, flag: Optional[str], policy_path: Path) -> int:
    policy = load_json(policy_path)
    if check_policy(policy):
        print("  context policy: policy file invalid, nothing changed: " + "; ".join(check_policy(policy)))
        return 1
    entry = policy["claude_code"][KEY]
    settings_path, state_path = claude_dir / "settings.json", claude_dir / STATE_FILE
    state, warn = load_state(state_path)
    if warn:
        print(f"  context policy: {warn}")
    managed, probe = load_managed(entry["skip_when"]["managed_settings"]), functools.lru_cache(detect_cc_version)
    for attempt in (1, 2):
        try:
            settings, stamp = read_settings(settings_path)
        except (OSError, ValueError) as exc:
            print(f"  context policy: settings.json unreadable ({exc}); nothing changed")
            return 1
        new, new_state, lines = decide(settings, state, entry, flag, os.environ, managed, probe,
                                       server_tuning(claude_dir))
        if new == settings:
            break
        if mtime_ns(settings_path) != stamp:  # a live session wrote it (/effort, /autocompact): re-read once
            if attempt == 1:
                continue
            print("  context policy: settings.json kept changing while applying; nothing written")
            return 1
        write_atomic(settings_path, json.dumps(new, indent=2, ensure_ascii=False) + "\n")
        break
    for line in lines:
        print(f"  context policy: {line}")
    slot = {k: new_state[k] for k in ("wrote", "cc_version", *FLAGS)}
    text = json.dumps({"schema": STATE_SCHEMA, "choice": new_state["choice"], "claude_code": {KEY: slot}}, indent=2)
    text += "\n"
    previous = state_path.read_text(encoding="utf-8") if state_path.exists() else None
    if text != previous and (previous is not None or new_state != FRESH):  # a default install leaves no sidecar
        write_atomic(state_path, text)
    return 0


def cmd_uninstall(claude_dir: Path, policy_path: Path) -> int:
    """uninstall.sh: retract exactly as --opt-out does, then delete the sidecar unless it still records a value Clade
    could not retract (an unreadable Claude Code version removes nothing); there it is the only proof of ownership."""
    state_path = claude_dir / STATE_FILE
    if not state_path.exists():
        print("  context policy: never applied here; nothing to retract")
        return 0
    rc = cmd_apply(claude_dir, "out", policy_path)
    wrote = load_state(state_path)[0]["wrote"]
    if rc == 0 and wrote is None:
        state_path.unlink()
        print(f"  context policy: removed {STATE_FILE}")
    else:
        print(f"  context policy: kept {STATE_FILE}, which still records {KEY}={wrote} as Clade's. Delete the key "
              "from settings.json by hand, or re-run ./uninstall.sh once `claude --version` works")
    return rc


# ─── status ───
def read_toml(path: Path) -> Optional[dict[str, Any]]:
    """None when absent, {"_unreadable": why} when unparseable. Callers read only named, non-secret keys."""
    if not path.is_file():
        return None
    try:
        return obj(importlib.import_module("tomllib").loads(path.read_text(encoding="utf-8")))
    except ImportError:
        return {"_unreadable": "needs Python 3.11+ (tomllib)"}
    except (OSError, ValueError) as exc:
        return {"_unreadable": type(exc).__name__}


def codex_line(cfg: dict[str, Any], b: Mapping[str, Any]) -> str:
    model = cfg.get("model") if isinstance(cfg.get("model"), str) else None
    window, limit = cfg.get("model_context_window"), cfg.get("model_auto_compact_token_limit")
    window = window if is_int(window) else b["reference_context_window"] if model in (None, b["reference_model"]) else 0
    if not window:
        return f"model {model}: window unknown (derived only for {b['reference_model']})"
    point = int(window * b["compact_fraction"])
    point = min(point, limit) if is_int(limit) else point
    return (f"model {model or 'unset'} compacts near {point:,} ({b['compact_fraction']:.0%} of {window:,}; "
            f"model_auto_compact_token_limit {limit if is_int(limit) else 'unset'}); {b['decision']}")


def kimi_line(cfg: dict[str, Any], b: Mapping[str, Any]) -> str:
    model, loop = cfg.get("default_model"), obj(cfg.get("loop_control"))
    entry = obj(obj(cfg.get("models")).get(model)) if isinstance(model, str) else {}
    size = obj(entry.get("overrides")).get("max_input_size")
    size = size if is_int(size) else entry.get("max_context_size")
    ratio = loop.get("compaction_trigger_ratio", b["trigger_ratio"])
    reserved = loop.get("reserved_context_size", b["reserved_context_size"])
    if not is_int(size) or not isinstance(ratio, (int, float)) or not is_int(reserved):
        return f"default_model {model}: window unknown; {b['decision']}"
    trigger = min(round(size * ratio), size - reserved if 0 < reserved < size else size)
    return (f"{model} compacts near {trigger:,} (window {size:,}, ratio {ratio}, reserved {reserved:,}); "
            f"{b['decision']}. Manual option: {b['manual_option']}")


def cmd_status(claude_dir: Path, policy_path: Path, as_json: bool) -> int:
    policy = load_json(policy_path)
    if check_policy(policy):
        print(f"context-policy status: {policy_path}: " + "; ".join(check_policy(policy)), file=sys.stderr)
        return 1
    e, home = policy["claude_code"][KEY], Path.home()
    version, how = detect_cc_version()
    try:
        settings = read_settings(claude_dir / "settings.json")[0]
    except (OSError, ValueError):
        settings = {}
    state, warn = load_state(claude_dir / STATE_FILE)
    cur = settings.get(KEY)
    owner = "none" if cur is None else "clade" if same_int(cur, state["wrote"]) else "user"
    shadow = skip_reasons(settings, os.environ, load_managed(e["skip_when"]["managed_settings"]), e["skip_when"])
    shadow += [f"a server-side window cached in {s} (Clade retracts its own value and writes none)"
               for s in server_tuning(claude_dir)]
    user_file = os.path.realpath(claude_dir / "settings.json")  # run from $HOME, .claude/settings.json IS this file
    shadow += [f"project {p} sets {KEY} (whether project scope is honoured is UNVERIFIED)"
               for p in (Path(".claude/settings.json"), Path(".claude/settings.local.json"))
               if p.is_file() and os.path.realpath(p) != user_file
               and f'"{KEY}"' in p.read_text(encoding="utf-8", errors="replace")]
    hi = parse_version(e["verified_through_cc_version"])
    newer = version is not None and hi is not None and version > hi
    # Claude Code drops an int outside [1e5, 1e6] (.catch(void 0)) and uses the model window; a shadow decides alone.
    window = cur if is_int(cur) and VALUE_MIN <= cur <= VALUE_MAX else VALUE_MAX
    trigger = None if shadow else window - OUTPUT_RESERVE - SUMMARY_BUFFER
    vendors = []
    for name, cfg_path, ver, line in (("Codex", ".codex", policy["codex"]["verified_codex_version"], codex_line),
                                      ("Kimi", ".kimi-code", policy["kimi"]["verified_kimi_version"], kimi_line)):
        cfg = read_toml(home / cfg_path / "config.toml")
        body = (f"config.toml {'absent' if cfg is None else cfg['_unreadable']}" if cfg is None or "_unreadable" in cfg
                else line(cfg, policy[name.lower()]))
        vendors.append(f"{name} (report-only, derived on {name.lower()} {ver}): {body}")
    lines = [f"Claude Code {fmt(version)} ({how}); policy floor {e['min_cc_version']}, verified through "
             f"{e['verified_through_cc_version']}, retire from {e.get('retire_from_cc_version') or 'never'}",
             f"{KEY}: {'absent' if cur is None else cur} (owner {owner}; policy value {e['value']}; choice "
             f"{state['choice'] or 'default'}{'; the user removed it' if state['user_removed'] else ''})",
             f"compaction on a 1M model near {trigger:,} tokens (W - 20,000 - 13,000; formula of the 2.1.283 binary)"
             if trigger is not None else "compaction point: not computed, the shadowing setting below decides it",
             "shadowed by: " + (", ".join(shadow) if shadow else "nothing"), *vendors]
    if newer:
        lines.insert(1, f"NOTICE: you run {fmt(version)}, newer than the verified {e['verified_through_cc_version']}. "
                        f"Re-verify the key's precedence and the trigger formula against {DOCS_URL}, then raise "
                        "verified_through_cc_version in configs/context-policy.json. This command never fetches it.")
    report = {"claude_code": {"version": fmt(version), "detected_by": how, "newer_than_verified": newer},
              KEY: {"value": cur, "owner": owner, "policy_value": e["value"], "choice": state["choice"],
                    **{k: state[k] for k in FLAGS}, "sidecar_warning": warn},
              "trigger_1m_model": trigger, "shadowed_by": shadow, "lines": lines}
    print(json.dumps(report, indent=2) if as_json else "\n".join(lines))
    return 0


# ─── CLI ───
def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Clade's opt-in Claude Code context-window policy (see the docstring).")
    ap.add_argument("cmd", nargs="?", choices=("apply", "status", "uninstall"))
    ap.add_argument("--claude-dir", type=Path, help="apply, uninstall: required; status: default ~/.claude")
    ap.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    choice = ap.add_mutually_exclusive_group()
    choice.add_argument("--opt-in", dest="flag", action="store_const", const="in", help="apply: opt in (persists)")
    choice.add_argument("--opt-out", dest="flag", action="store_const", const="out", help="apply: opt out (persists)")
    ap.add_argument("--json", action="store_true", help="status: machine-readable")
    ap.add_argument("--check", action="store_true", help="validate the policy file and exit")
    ap.add_argument("--self-test", action="store_true", help="run the positive and negative controls")
    args = ap.parse_args(argv)
    if args.self_test:  # the controls live in context_policy_selftest.py beside this file and drive its CLI
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        return int(importlib.import_module("context_policy_selftest").run(os.path.abspath(__file__), str(args.policy)))
    if args.check:
        errs = check_policy(load_json(args.policy))
        for line in errs or ["valid"]:
            print(f"context-policy --check: {args.policy}: {line}", file=sys.stderr if errs else sys.stdout)
        return 1 if errs else 0
    try:
        if args.cmd == "apply" and args.claude_dir:
            return cmd_apply(args.claude_dir, args.flag, args.policy)
        if args.cmd == "uninstall" and args.claude_dir:
            return cmd_uninstall(args.claude_dir, args.policy)
        if args.cmd == "status":
            return cmd_status(args.claude_dir or Path.home() / ".claude", args.policy, args.json)
    except (OSError, ValueError) as exc:  # unreadable policy, unwritable settings: report, change nothing more
        print(f"  context policy: {exc}; stopped", file=sys.stderr)
        return 1
    ap.print_usage(sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
