**English**（中文版尚未提供 — [README 中文版](../README.zh-CN.md)）

← Back to [README](../README.md)

# Configuration & Customization

## Table of Contents

1. [Required](#required)
2. [Optional](#optional)
3. [Tuning](#tuning)
4. [Add a correction rule manually](#add-a-correction-rule-manually)
5. [Adjust quality gate thresholds](#adjust-quality-gate-thresholds)
6. [Add a new hook](#add-a-new-hook)
7. [Add a new agent](#add-a-new-agent)
8. [Add a new skill](#add-a-new-skill)

---

## Required

Nothing. Everything works out of the box with sensible defaults.

## Optional

Set these in `~/.claude/settings.json` under `"env"`:

| Variable | Purpose |
|----------|---------|
| `TG_BOT_TOKEN` | Telegram bot token for notifications |
| `TG_CHAT_ID` | Telegram chat ID for notifications |

## Tuning

| File | What to tune |
|------|-------------|
| `~/.claude/corrections/rules.md` | Add/edit correction rules directly |
| `~/.claude/corrections/stats.json` | Adjust error rates per domain (0-1) to control quality gate strictness |
| `~/.claude/orchestrator-settings.json` | Override orchestrator defaults — model, worker pool, GitHub sync, auto-retry, etc. |

### Orchestrator settings

After running `./install.sh`, a reference copy of every supported orchestrator
key lives at `~/.claude/orchestrator-settings.example.json`. To override a
default:

```bash
# Copy only the keys you want to change into the real settings file.
# Defaults from orchestrator/config.py:_SETTINGS_DEFAULTS apply for unset keys.
cat > ~/.claude/orchestrator-settings.json <<'EOF'
{
  "max_workers": 4,
  "auto_classify_retry": true
}
EOF
```

The `.example.json` is overwritten by every `./install.sh` run so it always
matches the current `_SETTINGS_DEFAULTS`; your real `orchestrator-settings.json`
is never touched.

## Add a correction rule manually

Edit `~/.claude/corrections/rules.md`:
```
- [2026-02-17] imports: Use @/ path aliases instead of relative paths
- [2026-02-17] naming: Use camelCase for TypeScript variables, not snake_case
```

## Adjust quality gate thresholds

Edit `~/.claude/corrections/stats.json`:
```json
{
  "frontend": 0.4,
  "backend": 0.05,
  "ml": 0.2,
  "ios": 0,
  "android": 0,
  "systems": 0,
  "academic": 0,
  "schema": 0.2
}
```

`> 0.3` triggers strict mode (adds build + test checks). `< 0.1` triggers relaxed mode (basic checks only). Domains: `frontend`, `backend`, `ml`, `ios`, `android`, `systems` (Rust/Go), `academic` (LaTeX), `schema`.

## Enable end-to-end browser verification

`/verify` ships a **UI Interaction** strategy that drives a real browser (navigate
the running app, snapshot pages, click/fill, flag console errors and broken flows)
— the only verification that proves a frontend change actually works rather than
just compiles. It runs only when the Playwright MCP is wired in. Enable it per
project:

```bash
configs/scripts/setup-browser-verify.sh /path/to/project       # merge config + install Chromium
configs/scripts/setup-browser-verify.sh /path/to/project --remove   # disable
```

This merges the Microsoft Playwright MCP (`@playwright/mcp`) into the project's
`.claude/mcp.json` — the file both orchestrator worker spawns (`worker.py`) and
`/verify` (`start.sh`) already load via `--mcp-config` — and installs the Chromium
binary. Existing MCP servers in the file are preserved. Requires Node (`npx`),
which Claude Code already provides.

Once enabled: `fix`/`test` worker tasks can reach the browser tools (allow-listed
as `mcp__playwright` in `config.py:_TOOL_SUBSETS`), and `/verify` emits
`INTERACTION_RESULT: pass|partial|fail` plus `[BUG]`/`[UX]` findings to
`.claude/playwright-issues.md`, which the loop consumes. Cost note: every worker
on that project then launches a Playwright MCP subprocess — run `--remove` for
projects with no frontend.

**Troubleshooting** (seen live on a real Next.js project):
- The Chromium install may print a Playwright version-mismatch box and `Removing
  unused browser at …chromium-NNNN` — this is normal: `npx playwright install`
  resolves a different Playwright version than `@playwright/mcp` bundles, so it
  swaps the browser build. The setup still succeeds; verify with
  `ls ~/.cache/ms-playwright/` (a `chromium-*` dir present = good).
- The `/verify` browser step (and the worker visual-verify directive) only fires
  when the project is detected as a frontend — detection reads the project's
  `package.json` for a frontend framework (`next`/`react`/`vue`/`svelte`/…) **or**
  a `## Project Type` / `Frontend:` line in CLAUDE.md. A frontend project whose
  CLAUDE.md only describes the stack in prose is still detected via package.json.

## Mutation testing (patrol lane)

Coverage shows a line *ran* during tests; mutation testing shows a test would
*catch a bug*. Enable the lane to surface hollow tests (code that's executed but
never asserted — the real risk for agent-written tests):

```jsonc
// ~/.claude/orchestrator-settings.json
{
  "mutation_scan": true,
  "mutation_targets": ["orchestrator/worker_review.py", "orchestrator/error_classifier.py"]
}
```

Requires `mutmut` (`pip install mutmut`); absent → the lane logs a hint and
no-ops. `mutation_targets` (project-relative paths) is **required** — mutation
targets are project-specific, so with none configured the lane no-ops. It runs
every ~6h (mutmut runs the whole suite once per mutant, so it is the most
expensive lane — never a commit gate); pick a few high-signal modules where a
silently hollow test is most dangerous. **Ratchet:** the first run seeds a survivor baseline at
`.claude/mutation-baseline.json` and creates **no** tasks; later runs create a
`test`-type task only for *newly*-surviving mutants (a regression in test quality),
capped at 10/run. Killed mutants drop from the baseline automatically.

## Add a new hook

1. Create `configs/hooks/your-hook.sh`
2. Add the hook definition to `configs/settings-hooks.json`
3. Run `./install.sh`

## Add a new agent

1. Create `configs/agents/your-agent.md` with frontmatter (name, description, tools, model)
2. Run `./install.sh`

## Add a new skill

1. Create `configs/skills/your-skill/SKILL.md` (frontmatter + description)
2. Create `configs/skills/your-skill/prompt.md` (full skill prompt)
3. Run `./install.sh`
