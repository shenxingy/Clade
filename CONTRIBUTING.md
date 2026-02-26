# Contributing to claude-code-kit

Thanks for your interest in contributing! This project has 800+ clones and counting — every contribution helps.

## Ways to Contribute

Contributions aren't just code:

- **Bug reports** — reproducible reports with logs are extremely valuable
- **Documentation** — fix typos, clarify confusing sections, add examples
- **Issue triage** — help confirm and reproduce reported bugs
- **Testing** — try features on different OS/shell combos, report edge cases
- **Features** — new hooks, skills, agents, or workflow improvements

## Local Setup

```bash
# 1. Fork and clone
git clone https://github.com/YOUR_USERNAME/claude-code-kit.git
cd claude-code-kit

# 2. Install (deploys to ~/.claude/)
./install.sh

# 3. Open a new Claude Code session to activate
claude
```

**Requirements:** `jq` for settings merge. Python 3.9+ for the orchestrator. Everything else is optional.

**Test your changes:** After modifying a hook or script, run `./install.sh` to redeploy, then open a fresh Claude Code session to verify it fires correctly.

## Commit Format

We use [Conventional Commits](https://www.conventionalcommits.org/):

```
feat: add retry support to run-tasks.sh
fix: prevent double-firing of correction-detector on short messages
docs: clarify /batch-tasks --parallel usage in README
refactor: extract model detection logic into shared function
test: add unit tests for loop convergence logic
chore: bump orchestrator dependencies
```

**For parallel agent sessions**, use the `committer` script instead of `git add .` to avoid staging conflicts:

```bash
~/.local/bin/committer "feat: your message" file1.sh file2.py
```

`committer` is installed by `./install.sh`. It stages only named files, preventing parallel agents from accidentally staging each other's work.

## PR Process

1. Fork the repo and create a branch: `git checkout -b feat/your-feature`
2. Make your changes following the code style
3. Verify syntax: `bash -n configs/hooks/your-hook.sh`
4. Commit with Conventional Commits format
5. Open a PR against `main`
6. A maintainer will review within a few days

PRs are squash-merged to keep history clean.

## Good First Issues

Look for issues labeled [`good first issue`](https://github.com/shenxingy/claude-code-kit/labels/good%20first%20issue) — these are well-scoped and have clear acceptance criteria.

Good areas for first contributions:
- Adding language support to an existing hook (e.g., adding Zig/Julia detection to `post-edit-check.sh`)
- Improving error messages in shell scripts
- Documentation improvements
- New skill prompts in `configs/skills/`

## Architecture Overview

The kit has two layers:

### CLI Layer (`configs/`)

Shell-based hooks and scripts that run on every Claude Code event:

```
configs/hooks/         # Event-driven shell scripts (SessionStart, PreToolUse, etc.)
configs/scripts/       # Task runners called by /batch-tasks
configs/skills/        # Slash command prompts (Markdown files)
configs/agents/        # Sub-agent definitions (frontmatter + prompt)
```

Hooks are registered in `configs/settings-hooks.json` and merged into `~/.claude/settings.json` by `install.sh`.

### GUI Layer (`orchestrator/`)

A FastAPI + vanilla JS web UI for parallel agent orchestration:

```
orchestrator/server.py      # FastAPI backend (PTY management, SQLite task queue)
orchestrator/web/index.html # Single-file SPA (no build step)
orchestrator/start.sh       # Launch script
```

The GUI is deliberately self-contained — no bundler, no framework. This makes it easy to modify.

For deeper context, see:
- [`docs/research/hooks.md`](docs/research/hooks.md) — hook system internals
- [`docs/research/subagents.md`](docs/research/subagents.md) — custom agent patterns
- [`docs/research/batch-tasks.md`](docs/research/batch-tasks.md) — batch execution details

## Getting Help

- **Questions** → [GitHub Discussions](https://github.com/shenxingy/claude-code-kit/discussions)
- **Bugs** → [Open an issue](https://github.com/shenxingy/claude-code-kit/issues/new/choose) using the Bug Report template
- **Security** → See [SECURITY.md](SECURITY.md)

## Labels Reference

When triaging issues, maintainers use these labels:

| Label | Color | Meaning |
|-------|-------|---------|
| `good first issue` | `#7057ff` | Well-scoped, low complexity |
| `help wanted` | `#008672` | Extra attention needed |
| `triage` | `#e4e669` | Needs reproduction/confirmation |
| `enhancement` | `#a2eeef` | New feature or improvement |
| `documentation` | `#0075ca` | Docs-only change |
| `blocked` | `#B60205` | Waiting on external dependency |
