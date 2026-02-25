# Goal: Pipeline Consistency Deep Audit

Deeply audit the entire claude-code-kit pipeline (skills, hooks, scripts, agents, templates) to ensure consistency, correctness, and ideal end state. The guiding principle: **fix the pipeline itself, not keep patching rules/memory/progress**.

## Requirements

### 1. Single Source of Truth
- All rules/conventions should be defined ONCE and referenced elsewhere
- CLAUDE.md (template) is the canonical source for coding standards
- No duplicate or contradictory rules across: `templates/CLAUDE.md`, `~/.claude/CLAUDE.md`, `configs/agents/*.md`, skill prompts
- Action: Audit all config files for conflicting or redundant instructions

### 2. Skills Consistency
- All skills that reference scripts MUST use absolute paths (`~/.claude/scripts/...`), never relative
- All skills must have correct `SKILL.md` metadata (user_invocable, description, argument-hint)
- Skills should not duplicate each other's functionality
- Action: Audit every skill's SKILL.md and prompt.md for path issues, stale references, missing metadata

### 3. Hooks Correctness
- All hooks must correctly use `lib/typecheck.sh` (no inline type-check logic remaining)
- Hook output format must be consistent (JSON via jq for system messages)
- Hooks must handle edge cases (missing tools, empty input, encoding errors)
- Action: Audit every hook for correctness and edge cases

### 4. Script Robustness
- `run-tasks.sh` and `run-tasks-parallel.sh` must handle: missing claude CLI, disk full, encoding errors in task descriptions
- `loop-runner.sh` must correctly source `models.env` and handle missing models
- `committer.sh` must handle: no staged files, merge conflicts, special characters in messages
- Action: Audit each script for edge cases and defensive programming

### 5. Agent Prompts Quality
- `configs/agents/code-reviewer.md` checklist should cover all standards from CLAUDE.md
- Agent prompts should not contain stale references or instructions that conflict with current setup
- Action: Cross-reference agent prompts with current project conventions

### 6. install.sh Completeness
- Must deploy ALL config files that exist in `configs/`
- Must NOT overwrite user customizations silently
- Must be idempotent (safe to run multiple times)
- Action: Verify install.sh covers every deployable file

### 7. Template CLAUDE.md Alignment
- `templates/CLAUDE.md` must reflect the actual project conventions
- Should not contain instructions that are specific to a single project
- Should be generic enough for any project but specific enough to be useful
- Action: Review template for generality and correctness

## Success Criteria
- `bash -n` passes for all shell scripts in configs/
- No relative `scripts/` paths remain in any skill prompt
- No inline type-check logic remains outside of `hooks/lib/typecheck.sh`
- No conflicting rules between template CLAUDE.md and agent prompts
- `install.sh` runs successfully and deploys all files
- grep for common anti-patterns returns 0: `grep -r "scripts/run-tasks" configs/skills/` (should only find `~/.claude/scripts/`)
