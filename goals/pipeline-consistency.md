# Goal: Pipeline Consistency — Single Source of Truth

Eliminate scattered, duplicated knowledge across the claude-code-kit infrastructure. Every rule/standard/config should have ONE canonical source, and all consumers (CLAUDE.md, agents, hooks, skills, orchestrator) should derive from it.

## Success Criteria

All items below must be true. Check each off as completed:

- [x] **Shared type-check library**: `configs/hooks/lib/typecheck.sh` contains ALL language detection + type-check logic. Both `post-edit-check.sh` and `verify-task-completed.sh` source it instead of duplicating. Supported languages: TypeScript/JS, Python, Rust, Go, Swift, Kotlin/Java, LaTeX.
- [x] **Centralized model ID mapping**: `configs/models.env` defines MODEL_HAIKU, MODEL_SONNET, MODEL_OPUS as env vars. `loop-runner.sh` sources this file. (`run-tasks.sh` and `run-tasks-parallel.sh` pass short names to `claude -p` which resolves internally — no hardcoded IDs to replace. `session-context.sh` has no model IDs.)
- [x] **Orchestrator standards**: `configs/skills/orchestrate/prompt.md` includes a "Code Architecture Standards" section (file size <1500 lines, 4-6 modules, DAG imports, section markers, cohesion). Orchestrator-planned tasks must follow these rules.
- [x] **Corrections graduation mechanism**: New `/audit` skill (`configs/skills/audit/SKILL.md` + `configs/skills/audit/prompt.md`) scans `~/.claude/corrections/rules.md`, compares against CLAUDE.md and hooks, and reports: rules that should be promoted to CLAUDE.md/hooks, rules that are already covered (redundant), rules that contradict existing configs. Confirmation count derived from `history.jsonl` timestamps.
- [x] **PROGRESS.md pruning in /sync**: `configs/skills/sync/prompt.md` includes instructions to archive entries older than 30 days (move to `docs/progress-archive/YYYY-MM.md`) unless marked `[ACTIVE]`. Keep PROGRESS.md under 100 lines.
- [x] **install.sh deploys models.env**: `install.sh` copies `configs/models.env` to `~/.claude/models.env` and deploys `hooks/lib/` directory.
- [x] **No duplicate type-check implementations**: grep for `tsc --noEmit`, `pyright`, `cargo check`, `go vet` — these patterns appear ONLY in `configs/hooks/lib/typecheck.sh`, NOT in `post-edit-check.sh` or `verify-task-completed.sh` directly (they call functions from the lib).
- [x] **No hardcoded model IDs in scripts**: grep for `claude-haiku-4-5`, `claude-sonnet-4-6`, `claude-opus-4-6` — these appear ONLY in `configs/models.env`, nowhere else in `configs/scripts/` or `configs/hooks/`.
- [ ] **All files pass shellcheck**: shellcheck not installed on this system — skipped. All files pass `bash -n` syntax check.
- [x] **install.sh still works**: Running `bash install.sh` completes successfully and deploys all new files (15 skills, 8 hooks, 5 agents).

## Constraints

- Do NOT modify `~/.claude/CLAUDE.md` (user's personal config — only templates and configs in the repo)
- Do NOT delete existing functionality — only refactor to eliminate duplication
- Keep shell scripts POSIX-compatible where possible (bash is OK for complex scripts)
- Do NOT change the public interface of any skill (same /command names, same flags)
- Preserve all existing hook behavior — refactoring internals only
- Each commit should be one logical unit (don't mix unrelated changes)
- Use `committer "type: message" file1 file2` for all commits

## Non-Goals (do NOT do these)

- Do NOT implement the full `{{include:}}` template system yet — that's a future task
- Do NOT refactor the orchestrator server.py
- Do NOT change TODO.md format assumptions in batch-tasks (separate task)
- Do NOT touch the Orchestrator Web UI (index.html, styles.css)
