"""Reading pytest results back out of a subprocess pipe.

Every consumer of test results in this repo runs a shell command and regex-matches
``node::id PASSED`` out of the output. Two things silently defeat that, and both
were live here:

1. **ANSI colour.** pytest colourizes whenever ``FORCE_COLOR``/``PY_COLORS`` says
   so, independently of whether stdout is a TTY — and agent harnesses set it
   (Claude Code exports ``FORCE_COLOR=3``). The verdict arrives as
   ``\\x1b[32mPASSED\\x1b[0m``, ``\\s+(PASSED|…)`` no longer matches, and the parse
   comes back empty. CI never sees this: GitHub Actions sets no such variable.
2. **Verbosity arithmetic.** pytest computes verbosity as ``count(-v) - count(-q)``,
   so ``-v --tb=no -q`` is verbosity 0 and prints dots, not per-node lines.
   Appending ``-v`` to a command that already carries ``-q`` buys nothing.

Both failures produce the same artifact — an empty result dict — and every caller
read an empty dict as "nothing to report" rather than "I could not see". That is
what turned the resolve-rate eval into a constant 0% and the intramorphic
regression detector into a permanent all-clear. So: suppress colour at the
process boundary, strip it on the way in regardless, normalize the command, and
let callers distinguish "no results" from "results, all fine".

Stdlib-only leaf with no project imports — ``evals/`` must keep running without
the orchestrator's dependency set, which is why the parser used to be duplicated
there instead of shared.
"""

from __future__ import annotations

import os
import re

# ─── ANSI ─────────────────────────────────────────────────────────────────────

# CSI sequences (colour, cursor moves) plus the OSC-8 hyperlinks newer pytest
# plugins emit around file paths.
_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)")


def strip_ansi(text: str) -> str:
    """Remove terminal escape sequences so result lines match as plain text."""
    return _ANSI_RE.sub("", text)


# ─── Result parsing ───────────────────────────────────────────────────────────

# Anchored per line: a node id (``path::name`` and optional ``::`` segments or a
# ``[param]`` suffix) followed by the verbose-mode verdict word.
_RESULT_RE = re.compile(
    r"^(?P<node>\S.*?::[\w\[\]:./ ,=+-]+?)\s+(?P<verdict>PASSED|FAILED|ERROR)\b",
    re.MULTILINE,
)


def parse_results(output: str) -> dict[str, bool]:
    """Parse ``pytest -v`` output into ``{node_id: passed}``.

    Colour is stripped first, so this is safe on output captured from an
    environment that forces it. An empty dict means no per-node lines were
    found — which is a *measurement failure*, not a clean run; callers that care
    about the difference should check emptiness explicitly rather than treating
    it as "no failures".
    """
    return {
        m.group("node").strip(): m.group("verdict") == "PASSED"
        for m in _RESULT_RE.finditer(strip_ansi(output))
    }


# ─── Command normalization ────────────────────────────────────────────────────

_QUIET_FLAGS_RE = re.compile(r"(?<!\S)(-q|--quiet|--no-header)(?=\s|$)")


def force_verbose(cmd: str) -> str:
    """Normalize a pytest command so it emits per-node result lines.

    Strips quiet flags before adding ``-v``: they cancel each other out, so a
    command carrying both is silently non-verbose. Non-pytest commands pass
    through untouched.
    """
    if "pytest" not in cmd:
        return cmd
    cmd = _QUIET_FLAGS_RE.sub("", cmd)
    cmd = re.sub(r"\s{2,}", " ", cmd).strip()
    if " -v" not in f" {cmd}":
        cmd = cmd.replace("pytest", "pytest -v", 1)
    return cmd


# ─── Process environment ──────────────────────────────────────────────────────

def color_free_env(base: dict[str, str] | None = None) -> dict[str, str]:
    """A copy of the environment with terminal colour forced off.

    ``FORCE_COLOR`` is removed rather than zeroed: pytest's own check treats the
    variable as truthy when merely present, so ``FORCE_COLOR=0`` still colours.
    ``PY_COLORS=0`` is what pytest reads; ``NO_COLOR`` covers the other tools a
    project's ``test_cmd`` may pipe through.
    """
    env = dict(os.environ if base is None else base)
    env.pop("FORCE_COLOR", None)
    env.pop("CLICOLOR_FORCE", None)
    env["PY_COLORS"] = "0"
    env["NO_COLOR"] = "1"
    return env
