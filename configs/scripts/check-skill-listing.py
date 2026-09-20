#!/usr/bin/env python3
"""check-skill-listing.py — does every model-facing skill keep its description?

What Claude Code does (read from the 2.1.258 binary, 2026-09-20)
-----------------------------------------------------------------
The skill listing the model sees is one line per skill,

    - <name>: <description>[ - <when_to_use>]        (capped at 1536 chars)

under a budget of `window_tokens × bytes_per_token × skillListingBudgetFraction`
(default 0.01; `SLASH_COMMAND_TOOL_CHAR_BUDGET` overrides it in characters).
bytes_per_token is 4 for the Claude 4.x family and 3 for later models. When the
listing exceeds the budget, Claude Code keeps every bundled skill in full,
lists any `skillOverrides: name-only` skill as `- <name>`, then walks the rest
in DESCENDING usage score — `usageCount × max(0.5^(days_since_use/7), 0.1)`,
stored per machine in ~/.claude.json — and keeps a description only while it
fits. Everything else becomes name-only. A never-used skill scores 0.

Measured on this machine: a 200k-context model gets 8,000 chars; the listing
was 66,408 chars over 166 skills; 103 of Clade's 144 skills had never been
used. Under those numbers a fresh install cannot auto-select a single Clade
skill on a 200k model — the bundled skills alone fill the budget.

What this checks
----------------
Recomputes the listing from configs/skills with Clade's shipped
configs/settings-skill-overrides.json applied, and asks, for a FRESH install
(no usage history) on a 200k model at the shipped fraction: does the whole
model-facing listing fit, so that no description is dropped? That is the gate
— it depends only on things this repository controls (descriptions, the
overrides file, the fraction). It also reports the 1M-window case, the minimum
fraction that would fit, and, with --usage, what THIS machine's history would
keep.

Stdlib only: the syntax-check CI job installs no dependencies.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import skill_frontmatter as sf  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
SKILLS = REPO / "configs" / "skills"
OVERRIDES = REPO / "configs" / "settings-skill-overrides.json"

DESC_CAP = 1536              # skillListingMaxDescChars default
DEFAULT_FRACTION = 0.01      # skillListingBudgetFraction default
# The bundled skills (dataviz, code-review, artifact-*, claude-api, …) always
# keep their description and are counted BEFORE anything of ours. Measured
# from one session's listing on 2026-09-20; re-measure when it looks wrong.
RESERVED_CHARS = 8000
SCENARIOS = (
    # label, window tokens, bytes per token
    ("200k window · 4 bytes/token (Sonnet 4.x, Haiku 4.5)", 200_000, 4),
    ("1M window · 3 bytes/token (Fable 5.1, Opus 5)", 1_000_000, 3),
)
GATE_SCENARIO = 0            # the fresh-install 200k case is the one that must fit


# ─── Listing arithmetic (mirrors the binary) ───


def entry_text(skill: dict, name_only: bool) -> str:
    if name_only:
        return f"- {skill['name']}"
    desc = skill["description"]
    if skill.get("when_to_use"):
        desc = f"{desc} - {skill['when_to_use']}"
    if len(desc) > DESC_CAP:
        desc = desc[:DESC_CAP - 1] + "…"
    return f"- {skill['name']}: {desc}"


def budget_chars(window: int, bytes_per_token: int, fraction: float) -> int:
    env = os.environ.get("SLASH_COMMAND_TOOL_CHAR_BUDGET")
    if env and env.isdigit() and int(env) > 0:
        return int(env)
    return max(1, math.floor(window * bytes_per_token * fraction))


def usage_score(entry: dict | None, now_ms: float) -> float:
    if not entry:
        return 0.0
    days = (now_ms - float(entry.get("lastUsedAt", 0))) / 86_400_000
    return float(entry.get("usageCount", 0)) * max(0.5 ** (days / 7), 0.1)


def simulate(skills: list[dict], overrides: dict[str, str], budget: int,
             reserved: int, usage: dict[str, dict] | None) -> dict:
    """Return which skills keep a description under the binary's greedy fill."""
    now_ms = time.time() * 1000
    forced = {s["name"] for s in skills if overrides.get(s["name"]) == "name-only"}
    full = {s["name"]: entry_text(s, False) for s in skills}
    short = {s["name"]: entry_text(s, True) for s in skills}
    total = sum(len(short[n]) if n in forced else len(full[n]) for n in full) + (len(skills) - 1)
    listing = total + reserved
    if listing <= budget:
        return {"fits": True, "chars": total, "listing": listing, "budget": budget,
                "kept": sorted(n for n in full if n not in forced), "dropped": [],
                "forced": sorted(forced)}
    # Over budget: base cost is every name plus the reserved bundled block, then
    # descriptions are added in descending usage score while they fit.
    base = sum(len(short[n]) for n in full) + (len(skills) - 1) + reserved
    remaining = budget - base
    candidates = [s["name"] for s in skills if s["name"] not in forced]
    scores = {n: usage_score((usage or {}).get(n), now_ms) for n in candidates}
    candidates.sort(key=lambda n: -scores[n])            # stable: ties stay alphabetical
    kept, dropped = [], []
    for n in candidates:
        extra = len(full[n]) - len(short[n])
        if extra <= remaining:
            kept.append(n)
            remaining -= extra
        else:
            dropped.append(n)
    return {"fits": False, "chars": total, "listing": listing, "budget": budget,
            "kept": sorted(kept), "dropped": sorted(dropped), "forced": sorted(forced)}


def min_fraction(total_chars: int, reserved: int, window: int, bytes_per_token: int) -> float:
    return (total_chars + reserved) / (window * bytes_per_token)


# ─── Loading ───


def load_overrides(path: Path | None) -> tuple[dict[str, str], float]:
    if path is None or not path.exists():
        return {}, DEFAULT_FRACTION
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return {}, DEFAULT_FRACTION
    data = json.loads(text)
    return dict(data.get("skillOverrides") or {}), float(data.get("skillListingBudgetFraction") or DEFAULT_FRACTION)


def load_usage(path: Path | None) -> dict[str, dict] | None:
    if path is None:
        return None
    try:
        return dict(json.loads(path.read_text(encoding="utf-8")).get("skillUsage") or {})
    except (OSError, ValueError):
        return None


# ─── Report ───


def run(skills_dir: Path, overrides_path: Path | None, usage_path: Path | None,
        reserved: int, fraction_override: float | None, as_json: bool) -> int:
    skills = sf.iter_skills(skills_dir)
    if not skills:
        print(f"check-skill-listing: no skills under {skills_dir}", file=sys.stderr)
        return 2
    overrides, fraction = load_overrides(overrides_path)
    if fraction_override is not None:
        fraction = fraction_override
    usage = load_usage(usage_path)
    results = []
    for label, window, bpt in SCENARIOS:
        b = budget_chars(window, bpt, fraction)
        fresh = simulate(skills, overrides, b, reserved, None)
        row = {"scenario": label, "window": window, "bytes_per_token": bpt, "fraction": fraction,
               "budget": b, "reserved": reserved, "listing_chars": fresh["listing"],
               "fits": fresh["fits"], "name_only_by_override": len(fresh["forced"]),
               "dropped_fresh": fresh["dropped"],
               "min_fraction": round(min_fraction(fresh["chars"], reserved, window, bpt), 4)}
        if usage is not None:
            row["dropped_with_usage"] = simulate(skills, overrides, b, reserved, usage)["dropped"]
        results.append(row)
    gate = results[GATE_SCENARIO]
    ok = gate["fits"]
    if as_json:
        print(json.dumps({"ok": ok, "skills": len(skills), "results": results}, indent=2, ensure_ascii=False))
        return 0 if ok else 1
    print(f"check-skill-listing: {len(skills)} skills under {skills_dir.relative_to(REPO) if skills_dir.is_relative_to(REPO) else skills_dir}; "
          f"{len(overrides)} name-only overrides; fraction {fraction}; reserved {reserved} chars for bundled skills")
    for r in results:
        verdict = "fits" if r["fits"] else f"OVER — {len(r['dropped_fresh'])} skill(s) would be name-only on a fresh install"
        print(f"  {r['scenario']}: budget {r['budget']:,} chars, listing {r['listing_chars']:,} → {verdict} "
              f"(minimum fraction {r['min_fraction']})")
        if r["dropped_fresh"]:
            print("    dropped (fresh install, alphabetical tie-break): " + ", ".join(r["dropped_fresh"][:12])
                  + (f" … +{len(r['dropped_fresh']) - 12} more" if len(r["dropped_fresh"]) > 12 else ""))
        if "dropped_with_usage" in r:
            d = r["dropped_with_usage"]
            print(f"    with this machine's usage history: {len(d)} dropped" + (": " + ", ".join(d[:12]) if d else ""))
    if not ok:
        print(f"check-skill-listing: FAIL — the model-facing listing does not fit the fresh-install "
              f"200k budget; raise BUDGET_FRACTION in regen-skill-overrides.py to at least "
              f"{gate['min_fraction']} or shorten descriptions / add name-only overrides", file=sys.stderr)
        return 1
    print("check-skill-listing: OK — every model-facing skill keeps its description on a fresh 200k install")
    return 0


# ─── Self-test: one positive and one negative control per property ───


def _write_skill(root: Path, name: str, desc: str, wtu: str = "") -> None:
    d = root / name
    d.mkdir(parents=True)
    fm = f"---\nname: {name}\ndescription: {desc}\n" + (f'when_to_use: "{wtu}"\n' if wtu else "") + "---\nbody\n"
    (d / "SKILL.md").write_text(fm, encoding="utf-8")


def self_test() -> int:
    failures: list[str] = []

    def check(cond: bool, what: str) -> None:
        (failures.append(what) if not cond else None)

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "skills"
        _write_skill(root, "alpha", "a" * 100)
        _write_skill(root, "beta", "b" * 100, "trigger words")
        _write_skill(root, "gamma", "g" * 100)
        skills = sf.iter_skills(root)
        # 1. entry text mirrors the binary: `- name: desc - when_to_use`, cap at 1536
        beta = next(s for s in skills if s["name"] == "beta")
        check(entry_text(beta, False) == "- beta: " + "b" * 100 + " - trigger words", "entry text format")
        long = {"name": "l", "description": "x" * 2000, "when_to_use": ""}
        check(len(entry_text(long, False)) == len("- l: ") + DESC_CAP, "1536-char cap applies")
        check(entry_text(beta, True) == "- beta", "name-only entry is the bare name")
        # 2. budget arithmetic
        check(budget_chars(200_000, 4, 0.01) == 8000, "200k × 4 × 1% = 8000")
        check(budget_chars(1_000_000, 3, 0.05) == 150_000, "1M × 3 × 5% = 150000")
        # 3. everything fits → nothing dropped, nothing forced
        fit = simulate(skills, {}, 100_000, 0, None)
        check(fit["fits"] and not fit["dropped"] and len(fit["kept"]) == 3, "fits when under budget")
        # 4. the reserved bundled block counts against the budget
        total = fit["chars"]
        check(simulate(skills, {}, total + 10, 0, None)["fits"], "fits at exactly the listing size")
        check(not simulate(skills, {}, total + 10, 50, None)["fits"], "reserved chars push it over")
        # 5. over budget, fresh install: alphabetical tie-break keeps alpha, drops the tail
        over = simulate(skills, {}, len("- alpha: " + "a" * 100) + len("- beta") + len("- gamma") + 2 + 5, 0, None)
        check(over["kept"] == ["alpha"] and over["dropped"] == ["beta", "gamma"], "fresh-install greedy fill by name")
        # 6. usage score reorders: a recently used gamma beats never-used alpha
        now = time.time() * 1000
        usage = {"gamma": {"usageCount": 20, "lastUsedAt": now}}
        used = simulate(skills, {}, len("- gamma: " + "g" * 100) + len("- alpha") + len("- beta") + 2 + 5, 0, usage)
        check(used["kept"] == ["gamma"], "usage score ranks a used skill first")
        check(usage_score({"usageCount": 10, "lastUsedAt": now - 7 * 86_400_000}, now) == 5.0, "score halves per 7 days")
        check(usage_score({"usageCount": 10, "lastUsedAt": now - 700 * 86_400_000}, now) == 1.0, "score floors at 0.1×")
        check(usage_score(None, now) == 0.0, "unknown skill scores 0")
        # 7. a name-only override costs only the name and never takes a description slot
        forced = simulate(skills, {"beta": "name-only"}, 100_000, 0, None)
        check(forced["forced"] == ["beta"] and "beta" not in forced["kept"], "name-only override is honoured")
        check(forced["chars"] == fit["chars"] - (len(entry_text(beta, False)) - len("- beta")), "name-only saves the description chars")
        # 8. minimum fraction is the listing + reserved over the window bytes
        check(abs(min_fraction(7000, 1000, 200_000, 4) - 0.01) < 1e-9, "minimum fraction arithmetic")

    if failures:
        for f in failures:
            print(f"  ✗ {f}")
        print(f"check-skill-listing --self-test: FAILED ({len(failures)})")
        return 1
    print("check-skill-listing --self-test: PASSED (8 properties, positive and negative controls)")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--skills", type=Path, default=SKILLS, help="skills directory (default: configs/skills)")
    parser.add_argument("--overrides", type=Path, default=OVERRIDES,
                        help="settings file with skillOverrides / skillListingBudgetFraction")
    parser.add_argument("--no-overrides", action="store_true", help="simulate without any override (stock Claude Code)")
    parser.add_argument("--usage", type=Path, default=None,
                        help="~/.claude.json to also report what this machine's usage history keeps")
    parser.add_argument("--fraction", type=float, default=None, help="override the fraction under test")
    parser.add_argument("--reserved", type=int, default=RESERVED_CHARS,
                        help=f"chars the bundled skills take first (default {RESERVED_CHARS}, measured)")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args(argv)
    if args.self_test:
        return self_test()
    overrides = None if args.no_overrides else args.overrides
    fraction = args.fraction if args.fraction is not None else (DEFAULT_FRACTION if args.no_overrides else None)
    return run(args.skills, overrides, args.usage, args.reserved, fraction, args.json)


if __name__ == "__main__":
    sys.exit(main())
