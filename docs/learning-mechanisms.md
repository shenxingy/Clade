**English**（中文版尚未提供 — [README 中文版](../README.zh-CN.md)）

[← Back to README](../README.md)

# Self-Learning Mechanisms

Clade has two complementary mechanisms that keep the system aligned with reality without manual upkeep:

1. [Commit Lessons](#commit-lessons--learn-from-your-git-history) — *reactive*: mine `git log` for recurring fix patterns, inject them into every session
2. [Doc Align](#doc-align--keep-counts-and-facts-in-sync-across-all-docs) — *preventive*: declare facts once, auto-detect drift across all `*.md`

Together: Clade learns from past mistakes **and** prevents future drift.

---

## Commit Lessons — learn from your git history

Every project's `git log` is a record of mistakes you (or Claude) already made. Clade mines it.

At every session start, `commit-archeology.sh` scans the last 60 days of commits for **recurring** patterns and injects the top 4 as context:

```
## 🧠 Commit Lessons (this repo, last 60d)
- 5× wiring-gap (last ef6ef76 on 2026-04-11) → fix: ... wire sessionId to all API calls
- 8× compat-gap (last 9d8afb1 on 2026-03-30) → fix(commit): cross-platform CI guidance
- 3× deploy-gap (last 1f32dd8 on 2026-04-27) → fix(install): deploy orchestrator-settings.example.json
- 12× claude-overridden (last 700b952) → 12 Claude commits whose files later got a non-Claude fix
```

**Detectors (all run locally, never upload):**
- `wiring-gap` — fix commits with "wire / hook up / not registered / not called"
- `deploy-gap` — fix commits referencing install.sh or "missing from"
- `compat-gap` — fix commits about macOS / bash / cross-platform fallbacks
- `disambiguate` — naming collisions / built-in conflicts
- `claude-overridden` — Claude-authored commits whose files later got a human-only fix (uses `Co-Authored-By: Claude` trailer)
- `mass-fix-day-*` — any single day with ≥10 fix commits (noisy initial pass signal)

**Works in any Claude Code frontend** (TUI, desktop, IDE) — the hook is in `~/.claude/settings.json`, fires regardless of UI. Web (claude.ai/code) is the only exception (it can't read your local git).

**Tunable via env vars:** `COMMIT_ARCH_WINDOW=60` (days), `COMMIT_ARCH_TOP_N=4` (lines injected), `COMMIT_ARCH_MIN=3` (min occurrences), `COMMIT_ARCH_CACHE_HOURS=24` (rescan throttle).

To verify on any project: `cd <repo> && bash ~/.claude/scripts/commit-archeology.sh --inject --force`.

If nothing prints: repo has <5 commits in window, or no pattern hit ≥3 occurrences. Both are fine — silent no-op is the design.

---

## Doc Align — keep counts and facts in sync across all docs

Every project has shared facts that drift: skill counts in README, version numbers in landing pages, trial periods in marketing copy. Manual sync is a losing game — `git log` already shows multiple "update README counts" commits in this repo alone.

`docs/facts.json` is the **single source of truth**. `doc-align.py` checks every `*.md` against it.

```json
{
  "facts": [
    {
      "name": "skills",
      "value": 103,
      "derive": {"type": "count_glob", "pattern": "configs/skills/*/"},
      "patterns": ["^## Skills\\s*\\((\\d+)\\)", "^(\\d+) skills,"]
    }
  ]
}
```

**Modes:**
- `doc-align.py check` — report drift, exit non-zero if any
- `doc-align.py apply` — auto-rewrite drifting values in-place
- `doc-align.py refresh` — re-derive auto-derivable facts (counts from filesystem)
- `doc-align.py sync` — refresh + apply (one-shot)

**`derive` types (V1):** `count_glob` (count files/dirs matching glob). More to come (`http_get_json`, `count_lines`, etc.) when needed. No shell-injection surface — safe primitives only.

**Auto-runs on every install.** `install.sh` calls `refresh` so `facts.json` always reflects the filesystem (skill/hook/agent/script counts). `apply` is opt-in (you decide when to rewrite docs).

**Real-time guard.** A PostToolUse:Edit hook (`doc-align-check.sh`) fires whenever Claude edits a `*.md` and flags drift inline — so a stale count never reaches commit.

**Universal:** lives in `~/.claude/scripts/doc-align.py` after install — works on any project that has a `docs/facts.json`. Repos without one are silent no-ops.
