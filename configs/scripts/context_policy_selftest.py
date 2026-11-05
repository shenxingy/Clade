#!/usr/bin/env python3
"""context_policy_selftest.py — the positive and negative controls behind context-policy.py's self-test flag.

Kept beside that script, not inside it, so that the script carries only the policy. It imports nothing from it: every
case runs the CLI of the script it is handed (`apply`, and the policy check) as a subprocess, so a guard removed from
that file turns this red. orchestrator/tests/test_self_tests_can_fire.py removes them one at a time to prove it;
tests/test-context-policy-install.sh covers the rest (install.sh, the write path, the version probe, the locations
of a server-side window cache, status).
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Optional

# ─── Constants ───
# Literals on purpose: a test that read these from the script under test would follow a renamed key silently.
KEY, STATE_FILE, GONE = "autoCompactWindow", ".clade-context-state.json", "absent"
OK, V300, V200 = "2.1.283 (Claude Code)\\n", "2.1.300 (Claude Code)\\n", "2.1.200 (Claude Code)\\n"

# (what is checked, case dir, `claude --version` output, settings seeded, flag, process env, policy edit, want).
# An empty label is a setup step; steps sharing a case dir run in order on the same files. Every step must also
# exit 0: a crashed apply writes nothing too, exactly like a correct skip.
STEPS: list[tuple[str, str, str, Any, str, Optional[dict[str, str]], Optional[dict[str, Any]], Any]] = [
    ("opt-in writes the value", "a", OK, {"x": 1}, "--opt-in", None, None, 350000),
    ("the default writes nothing", "b", OK, {}, "", None, None, GONE),
    ("below the version floor nothing is written", "c", V200, {}, "--opt-in", None, None, GONE),
    ("a banner line before the version", "d", "Hi\\n" + OK, {}, "--opt-in", None, None, 350000),
    ("a line that is not Claude Code's is no version", "e", "3.4.5 loaded\\n", {}, "--opt-in", None, None, GONE),
    ("a user value wins", "f", OK, {KEY: 500000}, "--opt-in", None, None, 500000),
    ("", "g", OK, {}, "--opt-in", None, None, 350000),
    ("a user edit is theirs, so opt-out keeps it", "g", OK, {KEY: 400000}, "--opt-out", None, None, 400000),
    ("", "h", OK, {}, "--opt-in", None, None, 350000),
    ("a key the user deleted is never re-added", "h", OK, {}, "", None, None, GONE),
    ("--opt-in re-adds it", "h", OK, None, "--opt-in", None, None, 350000),
    ("opt-out retracts a Clade-owned value", "h", OK, None, "--opt-out", None, None, GONE),
    ("", "o", OK, {}, "--opt-in", None, None, 350000),
    ("", "o", OK, {KEY: 500000}, "", None, None, 500000),
    ("a value the user took over and then deleted is not re-added", "o", OK, {}, "", None, None, GONE),
    ("", "p", OK, {KEY: 500000}, "--opt-in", None, None, 500000),
    ("the user's own value, deleted after opt-in, is not replaced", "p", OK, {}, "", None, None, GONE),
    ("settings.json env shadows", "i", OK, {"env": {"CLAUDE_CODE_AUTO_COMPACT_WINDOW": "1"}}, "--opt-in", None, None,
     GONE),
    ("the process env shadows", "j", OK, {}, "--opt-in", {"DISABLE_COMPACT": "1"}, None, GONE),
    ("managed settings shadow", "k", OK, {}, "--opt-in", None, None, GONE),
    ("unreadable managed settings shadow", "q", OK, {}, "--opt-in", None, None, GONE),
    ("a managed-settings.d drop-in shadows", "s", OK, {}, "--opt-in", None, None, GONE),
    ("", "l", OK, {}, "--opt-in", None, None, 350000),
    ("retired at exactly retire_from", "l", V300, None, "", None, {"retire_from_cc_version": "2.1.300"}, GONE),
    ("", "m", OK, {}, "--opt-in", None, None, 350000),
    ("an owned value follows a policy change", "m", OK, None, "", None, {"value": 300000}, 300000),
    ("an unknown version removes nothing", "m", "", None, "--opt-out", None, None, 300000),
]
# Files a case dir holds before its first step: managed settings that shadow, one that cannot be parsed, a drop-in.
SEED = (("k", "managed.json", json.dumps({KEY: 600000})), ("q", "managed.json", "{ not json"),
        ("s", "managed-settings.d/10-admin.json", '{"env": {"DISABLE_COMPACT": "1"}}'))
# A window Anthropic tunes server-side, as 2.1.283 caches it in the global config (here the case dir's .claude.json):
# (what is checked, case dir, settings seeded, .claude.json written before the step or None to leave it, flag, want).
# While a cache is a non-empty object Clade retracts its own value and writes none; null or {} is no signal.
WINDOW = {"claude-opus-5-5": {"default": 400000, "surfaces": {"cli": 450000}}}
SERVER: list[tuple[str, str, Any, Any, str, Any]] = [
    ("opt-in with autoCompactWindowsCache set writes nothing", "u", {}, {"autoCompactWindowsCache": WINDOW},
     "--opt-in", GONE),
    ("", "v", {}, None, "--opt-in", 350000),
    ("a Clade-owned value is retracted once a server window is cached", "v", None,
     {"autoCompactWindowsCache": {"claude-opus-5-5": 400000}}, "", GONE),
    ("and written again once the cache is empty", "v", None, {"autoCompactWindowsCache": {}}, "", 350000),
    ("a clientDataCacheSlots rowan_thicket window writes nothing", "w", {},
     {"clientDataCacheSlots": {"bi1-x": {"data": {"rowan_thicket": WINDOW}}}}, "--opt-in", GONE),
    ("negative control: null caches are no signal", "x", {},
     {"autoCompactWindowsCache": None, "clientDataCacheSlots": {"bi1-x": {"data": {"rowan_thicket": None}}}},
     "--opt-in", 350000),
    ("negative control: empty caches are no signal", "y", {},
     {"autoCompactWindowsCache": {}, "clientDataCacheSlots": {"bi1-x": {"data": {"rowan_thicket": {}}}}},
     "--opt-in", 350000),
]
# Each must make the policy check exit 1.
BROKEN: tuple[tuple[str, Any], ...] = (("value", 99_999), ("min_cc_version", "2.1"), ("retire_from_cc_version", "2.1.1"),
          ("verified_through_cc_version", "2.0.0"), ("measurement", {}), ("enabled_by_default", "yes"),
          ("skip_when", {}))


# ─── Cases ───
def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def apply_case(script: str, base: Any, d: Path, shim: str, settings: Any, flag: str = "",
               env: Optional[dict[str, str]] = None, edit: Optional[dict[str, Any]] = None) -> tuple[int, Any]:
    """(exit status, value) of `apply` in case dir D, with only a fake `claude` printing SHIM on PATH and HOME=D."""
    (d / "bin").mkdir(parents=True, exist_ok=True)
    (d / "bin" / "claude").write_text(f"#!/bin/sh\nprintf '{shim}'\n")
    (d / "bin" / "claude").chmod(0o755)
    if settings is not None:
        (d / "settings.json").write_text(json.dumps(settings))
    policy = json.loads(json.dumps(base))
    e = policy["claude_code"][KEY]
    e.update({"enabled_by_default": False, "retire_from_cc_version": None, "value": 350000, **(edit or {})})
    e["skip_when"]["managed_settings"] = [str(d / "managed.json")]
    (d / "policy.json").write_text(json.dumps(policy))
    rc = subprocess.run([sys.executable, script, "apply", "--claude-dir", str(d), "--policy", str(d / "policy.json"),
                         *([flag] if flag else [])], env={"PATH": str(d / "bin"), "HOME": str(d), **(env or {})},
                        capture_output=True, timeout=60, check=False).returncode
    return rc, load_json(d / "settings.json").get(KEY, GONE)


def check_exit(script: str, policy: Any, path: Path) -> int:
    path.write_text(json.dumps(policy))
    return subprocess.run([sys.executable, script, "--check", "--policy", str(path)], capture_output=True,
                          timeout=60, check=False).returncode


# ─── Entry point ───
def run(script: str, policy_path: str) -> int:
    """Run every control against SCRIPT (context-policy.py) with POLICY_PATH as the base policy; 1 if any failed."""
    base, bad = load_json(Path(policy_path)), []
    with tempfile.TemporaryDirectory() as tmp:
        r = Path(tmp)
        for name, rel, text in SEED:
            (r / name / rel).parent.mkdir(parents=True, exist_ok=True)
            (r / name / rel).write_text(text)
        for label, name, shim, settings, flag, env, edit, want in STEPS:
            got = apply_case(script, base, r / name, shim, settings, flag, env, edit)
            bad += [] if got == (0, want) else [f"{label or 'setup ' + name}: got {got!r}, want {(0, want)!r}"]
        for label, name, settings, global_cfg, flag, want in SERVER:
            if global_cfg is not None:
                (r / name).mkdir(exist_ok=True)
                (r / name / ".claude.json").write_text(json.dumps(global_cfg))
            got = apply_case(script, base, r / name, OK, settings, flag)
            bad += [] if got == (0, want) else [f"{label or 'setup ' + name}: got {got!r}, want {(0, want)!r}"]
        n = r / "n"
        n.mkdir()
        (n / "real.json").write_text(json.dumps({"z": 1, "a": 2}))
        (n / "settings.json").symlink_to(n / "real.json")
        rcs = [apply_case(script, base, n, OK, None, "--opt-in")[0]]
        before = [(n / f).read_bytes() for f in ("real.json", STATE_FILE)]
        rcs.append(apply_case(script, base, n, OK, None)[0])
        after = [(n / f).read_bytes() for f in ("real.json", STATE_FILE)]
        checks: list[tuple[str, Any, Any]] = [
            ("both applies exit 0", rcs, [0, 0]),
            ("a symlinked settings.json stays a symlink", (n / "settings.json").is_symlink(), True),
            ("other keys keep value and order", list(load_json(n / "real.json")), ["z", "a", KEY]),
            ("a second run changes no byte", after, before),
            ("the shipped policy passes the check", check_exit(script, base, r / "shipped.json"), 0)]
        for field, broken in BROKEN:
            mutant = json.loads(json.dumps(base))
            mutant["claude_code"][KEY][field] = broken
            checks.append((f"the check refuses {field}={broken!r}", check_exit(script, mutant, r / "bad.json"), 1))
        bad += [f"{label}: got {got!r}, want {want!r}" for label, got, want in checks if got != want]
    print(*(f"FAIL {line}" for line in bad), f"context-policy self-test: {'FAILED' if bad else 'passed'} "
          f"({len(STEPS) + len(SERVER) + len(checks)} checks, {len(bad)} failed)", sep="\n")
    return 1 if bad else 0
