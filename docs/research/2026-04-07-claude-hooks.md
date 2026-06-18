---
topic: Claude Code Hooks Best Practices & Patterns (2025)
date: 2026-04-07
reconciled: 2026-06-18
status: integrated
sources:
  - https://code.claude.com/docs/en/hooks-guide
  - https://code.claude.com/docs/en/hooks
  - https://platform.claude.com/docs/en/agent-sdk/hooks
integrated_items:
  - item: PreToolUse dangerous-command blocking (exit 2)
    clade_location: configs/hooks/pre-tool-guardian.sh
  - item: PostToolUse lint check after edits
    clade_location: configs/hooks/post-tool-use-lint.sh
  - item: Stop-hook completion verification (§Gap 3 — CLOSED since doc written)
    clade_location: configs/hooks/stop-check.sh — Stop hook exists; verify which checks it runs (tests/TODO/lint) before deepening
  - item: PostToolUseFailure recovery context (§Gap 6 — CLOSED since doc written)
    clade_location: configs/hooks/post-tool-use-failure.sh (wired in configs/settings-hooks.json)
  - "Async PostToolUse hooks (§Gap 1) — DONE: configs/settings-hooks.json:94,119,127,135,143,163 (formatting/notification hooks carry async:true; the blocking post-tool-use-lint at :102 is intentionally sync to inject verify_cmd feedback Claude must read)"
  - "Input rewriting via updatedInput (§Gap 2) — DONE: configs/hooks/pre-tool-guardian.sh:122-127 (git push --force/-f → --force-with-lease via {decision:allow, updatedInput})"
  - "Persistent permission rules via updatedPermissions (§Gap 5) — DONE: configs/hooks/permission-request.sh:28,77,117,146 emit updatedPermissions; wired as PermissionRequest hook in configs/settings-hooks.json:311-322"
reference_items:
  - "Matcher \"if\" optimization (§Gap 4) — SKIP: the if-matcher pattern IS integrated (configs/settings-hooks.json:66 \"if\": \"Bash(git *)\" on revert-detector). Applying it to pre-tool-guardian itself would be wrong — the guardian MUST inspect every Bash call to catch rm -rf / DROP / force-push; gating it on a 'safe' allowlist would create a bypass. Different placement, not a deficiency."
  - "24 hook event types, exit-code 2 = blocking, 4 handler types (command/http/prompt/agent) — reference taxonomy; see docs/how-it-works.md hook list"
  - "HTTP audit hook + agent-based Stop verification — patterns to reach for if an external audit/verification need arises"
---

[English] | [Back to README](../../README.md)

# Claude Code Hooks: Best Practices & Patterns (2025)

## Overview

Claude Code supports **24 distinct hook events** firing at specific lifecycle points. Unlike LLM-chosen actions, hooks enforce rules deterministically — format code, block dangerous commands, inject context, audit tool calls.

**Exit code semantics** (critical — Unix convention does NOT apply):

| Code | Behavior |
|------|----------|
| **0** | Success. Parse JSON from stdout. Action proceeds. |
| **2** | Blocking error. Stderr fed to Claude. Blocks PreToolUse/PermissionRequest. |
| **other** | Non-blocking error. Shows notice, action proceeds. |

**Handler types** (4 kinds):
- `command` — shell script (most common)
- `http` — POST to remote URL (audit/logging services)
- `prompt` — spawn Claude for lightweight judgment
- `agent` — spawn full subagent for complex verification

## Hook Events Reference

### Key Events

| Event | Fires | Can Block? | Output |
|-------|-------|-----------|--------|
| `PreToolUse` | Before tool runs | **Yes (exit 2)** | `permissionDecision`, `updatedInput`, `additionalContext` |
| `PostToolUse` | After tool succeeds | No | logging, formatting |
| `PostToolUseFailure` | After tool fails | No | recovery context injection |
| `PermissionRequest` | When permission dialog appears | Yes | `decision.behavior`, `updatedPermissions` |
| `SessionStart` | Session open/resume | No | `additionalContext` injected as system reminder |
| `SessionEnd` | Session close | No | cleanup, audit |
| `Stop` | Before Claude claims done | **Yes (exit 2)** | verification gating |
| `UserPromptSubmit` | Before Claude processes prompt | Yes | prompt augmentation |
| `CwdChanged` | Directory change | No | write to `CLAUDE_ENV_FILE` |
| `FileChanged` | Watched file changes | No | env reload, cache invalidation |
| `SubagentStart/Stop` | Subagent lifecycle | No | logging |

### PreToolUse JSON Structure

```json
{
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "permissionDecision": "allow|deny|ask|defer",
    "permissionDecisionReason": "Why blocked",
    "updatedInput": { "command": "safe_alternative_command" },
    "additionalContext": "Hint for Claude to self-correct"
  }
}
```

### PermissionRequest — Persistent Rule Injection

```json
{
  "hookSpecificOutput": {
    "hookEventName": "PermissionRequest",
    "decision": {
      "behavior": "allow",
      "updatedPermissions": [{
        "type": "addRules",
        "rules": [{ "toolName": "Bash", "ruleContent": "git commit *" }],
        "behavior": "allow",
        "destination": "localSettings"
      }]
    }
  }
}
```

## Proven Patterns

### 1. Dangerous Command Blocking (exit 2, no JSON needed)

```bash
#!/bin/bash
COMMAND=$(cat | jq -r '.tool_input.command // ""')
if echo "$COMMAND" | grep -qE '^git push.*--force[^-]|^git push -f'; then
  echo "Use --force-with-lease instead of --force" >&2
  exit 2
fi
exit 0
```

Use **exit 2** for simple blocks. Reserve JSON+exit 0 for complex decisions or input modification.

### 2. Input Rewriting — Safe Alternatives

```json
{
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "permissionDecision": "allow",
    "updatedInput": {
      "command": "git push --force-with-lease origin $(git branch --show-current)"
    },
    "additionalContext": "Rewritten to use --force-with-lease for safety"
  }
}
```

### 3. Async PostToolUse (Non-Blocking Formatting)

Mark non-critical hooks `async: true` so Claude continues while background check runs:

```json
{
  "hooks": {
    "PostToolUse": [{
      "matcher": "Edit|Write",
      "hooks": [{
        "type": "command",
        "command": "~/.claude/hooks/auto-format.sh",
        "async": true
      }]
    }]
  }
}
```

### 4. CwdChanged — direnv Integration

```bash
#!/bin/bash
if command -v direnv &>/dev/null; then
  direnv export bash >> "$CLAUDE_ENV_FILE"
fi
exit 0
```

### 5. Stop Hook — Task Completion Verification

```bash
#!/bin/bash
# Only block if tests fail
cd "$PROJECT_DIR" && python -m pytest tests/ -q 2>&1
if [[ $? -ne 0 ]]; then
  echo "Tests still failing — cannot stop." >&2
  exit 2
fi
exit 0
```

### 6. Matcher Fine-Graining (`if` field)

```json
{
  "PreToolUse": [{
    "matcher": "Bash",
    "if": "Bash(rm -rf *)",
    "hooks": [{ "type": "command", "command": "~/.claude/hooks/block-rm.sh" }]
  }]
}
```

Use `"if"` to skip hook invocation for irrelevant commands — reduces latency.

### 7. HTTP Audit Hook

```json
{
  "PostToolUse": [{
    "matcher": ".*",
    "hooks": [{
      "type": "http",
      "url": "http://audit-service/hooks/tool-use",
      "headers": { "Authorization": "Bearer $AUDIT_TOKEN" },
      "allowedEnvVars": ["AUDIT_TOKEN"],
      "async": true
    }]
  }]
}
```

### 8. Agent-Based Verification (Stop)

```json
{
  "Stop": [{
    "hooks": [{
      "type": "agent",
      "prompt": "Verify all TODO checklist items in TODO.md are marked done. If any unchecked, output 'INCOMPLETE' and explain.",
      "model": "claude-haiku-4-5-20251001"
    }]
  }]
}
```

## Gaps vs Clade Current Implementation

### §Gap 1 — Async Hooks (Small Effort)

`post-tool-use-lint.sh` blocks Claude while running verify_cmd. Mark as `async: true` for PostToolUse hooks that do formatting/notifications.

**Impact**: Eliminates latency spike on every Edit/Write.

### §Gap 2 — Input Rewriting (Small Effort)

`pre-tool-guardian.sh` blocks dangerous commands but doesn't rewrite them. Add `updatedInput` for patterns like `git push -f` → `--force-with-lease`.

**Impact**: Claude self-corrects without full denial; fewer retry turns.

### §Gap 3 — Stop Hook Verification (Medium Effort)

No `Stop` hook. Add verification: run tests, check TODO checklist, confirm lint clean before allowing session end.

**Impact**: Prevents false-done sessions — significant for overnight autonomous loops.

### §Gap 4 — Matcher `if` Optimization (Small Effort)

`pre-tool-guardian.sh` runs on ALL Bash commands. Add `"if": "Bash(rm *|git push*|DROP*)"` in config to skip invocation for safe commands.

**Impact**: Reduces hook overhead on every Bash call.

### §Gap 5 — Persistent Permission Rules (Small Effort)

After auto-approving a known-safe pattern, inject a persistent allow rule via `updatedPermissions` to `.claude/settings.local.json`. Avoids reprompting on future identical calls.

### §Gap 6 — PostToolUseFailure Context (Small Effort)

No `PostToolUseFailure` hook. Add hook to inject diagnostic context (recent git changes, common fixes for that tool) when a tool fails.

**Impact**: Reduces recovery turns when tools fail.

## Key Takeaways (2025)

1. Exit **2** (not 1) blocks actions
2. `async: true` for non-critical PostToolUse hooks
3. `updatedInput` for safe alternatives > blocking outright
4. `PermissionRequest` with `updatedPermissions` for auto-allow + persistence
5. `Stop` hook with test verification is the highest-value gap for autonomous workflows
6. `"if"` field on matchers eliminates wasted hook invocations
