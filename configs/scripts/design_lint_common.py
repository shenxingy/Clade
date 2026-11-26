"""design_lint_common — what design-lint.py's html and source lanes share.

design-lint.py reached 1,489 of the 1,500-line cap once the source lane and
its motion-runtime checks landed, so the source lane moved to
design_lint_source.py and the five things both lanes read moved here: the
findings `Report` (with the `Finding` it holds), `custom_properties` and
`resolve_value` for var() tokens, the `<style>` block pattern and the
focus-restore pattern. design-lint.py imports this from beside itself;
install.sh copies every configs/scripts/*.py and regen-codex-plugin.py bundles
all three files into the artifact skill. Stdlib only.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

SEVERITY_ORDER = {"FAIL": 0, "WARN": 1, "SKIP": 2, "PASS": 3}


# ─── Findings ───


@dataclass
class Finding:
    check: str
    severity: str          # FAIL | WARN | SKIP | PASS
    target: str
    detail: str
    measured: Any = None
    threshold: Any = None


@dataclass
class Report:
    lane: str
    findings: list[Finding] = field(default_factory=list)

    def add(self, *a, **kw) -> None:
        self.findings.append(Finding(*a, **kw))

    @property
    def failed(self) -> bool:
        return any(f.severity == "FAIL" for f in self.findings)

    def render(self) -> str:
        rows = sorted(self.findings, key=lambda f: SEVERITY_ORDER.get(f.severity, 9))
        out = []
        for f in rows:
            mark = {"FAIL": "✗", "WARN": "!", "SKIP": "–", "PASS": "✓"}.get(f.severity, "?")
            out.append(f"  {mark} [{f.severity:4}] {f.target}: {f.detail}")
        counts: dict[str, int] = {}
        for f in self.findings:
            counts[f.severity] = counts.get(f.severity, 0) + 1
        summary = " ".join(f"{k}={v}" for k, v in sorted(counts.items()))
        out.append(f"  ── {self.lane}: {summary or 'no checks ran'}")
        return "\n".join(out)


# ─── CSS custom properties (var() resolution) ───


_VAR_DEF = re.compile(r"(--[\w-]+)\s*:\s*([^;}]+)")
_VAR_USE = re.compile(r"var\(\s*(--[\w-]+)\s*(?:,\s*([^)]+))?\)")


def custom_properties(css: str) -> dict[str, str]:
    """Collect `--token: value` declarations so var() references can resolve.

    The skill tells designers to build on CSS custom properties, so a checker
    that gives up at `var(--ink)` is blind on exactly the idiom it recommends.
    Later definitions win, matching the cascade for same-specificity rules.
    """
    return {name: value.strip() for name, value in _VAR_DEF.findall(css)}


def resolve_value(value: str, props: dict[str, str], depth: int = 0) -> str:
    """Substitute var() references, honouring fallbacks, with a recursion cap."""
    if depth > 8 or "var(" not in value:
        return value

    def swap(m: re.Match) -> str:
        return props.get(m.group(1), (m.group(2) or "")).strip()

    return resolve_value(_VAR_USE.sub(swap, value), props, depth + 1)


# ─── Patterns both lanes read ───

_STYLE_BLOCK = re.compile(r"<style[^>]*>(.*?)</style>", re.S | re.I)
# A focus rule counts as a RESTORE only when it sets an indicator. The obvious
# regex — any :focus rule mentioning `outline` — is satisfied by the very rule
# that removes it (`button:focus { outline: none }`), which is the one case
# the check exists to catch; the html lane shipped exactly that blind spot.
_FOCUS_RESTORE = re.compile(
    r":focus(?:-visible|-within)?\b[^{]*\{[^}]*"
    r"(?:outline(?!\s*:\s*(?:none|0)\b)|box-shadow|border|ring)", re.I | re.S)
