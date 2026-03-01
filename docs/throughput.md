[English](throughput.md) | [中文](throughput.zh-CN.md)

← Back to [README](../README.md)

# Maximize Throughput

## Table of Contents

1. [Skip permission prompts](#1-skip-permission-prompts)
2. [Batch your task input](#2-batch-your-task-input-the-core-habit)
3. [Run parallel agents with worktrees](#3-run-parallel-agents-with-worktrees)
4. [Task queue — sequential tasks, one shot](#4-task-queue--sequential-tasks-one-shot)
5. [Recommended terminal setup](#5-recommended-terminal-setup)

---

The bottleneck for Claude Code is not code generation — it's **how fast you input tasks**. These setups eliminate the friction.

## 1. Skip permission prompts

```bash
# Add to ~/.zshrc or ~/.bashrc
alias cc='claude --dangerously-skip-permissions'
```

With this alias, Claude runs fully autonomously — no approval dialogs, no interruptions. Use `cc` instead of `claude`. Always commit before starting a session (git is your rollback).

## 2. Batch your task input (the core habit)

Write all tasks upfront, then launch agents simultaneously:

```bash
mkdir -p .claude/tasks

# Good task file: specific files, patterns to follow, edge cases to handle
cat > .claude/tasks/task-001.md << 'EOF'
Add rate limiting to all /api/auth/* routes.
Use the existing rateLimiter in lib/middleware.ts.
Set 10 req/min for POST /auth/login, 60/min for GET endpoints.
Return 429 with {"error": "rate_limit_exceeded", "retry_after": N} on breach.
EOF

cat > .claude/tasks/task-002.md << 'EOF'
Write E2E tests for the checkout flow in tests/e2e/checkout.spec.ts.
Follow the pattern in tests/e2e/cart.spec.ts.
Cover: add to cart, apply coupon, checkout success, payment failure (card_declined).
EOF

# Launch agents — one per terminal, fully autonomous
cc -p "$(cat .claude/tasks/task-001.md)"   # Terminal 1 (non-interactive)
cc -p "$(cat .claude/tasks/task-002.md)"   # Terminal 2 (non-interactive)

# Or run interactively if you want to watch/guide:
cc   # Terminal 3 → paste task content
```

> **What makes a good task file:** Name the exact files to edit/create. Reference existing patterns to follow (`"follow the pattern in X"`). Specify edge cases and error formats. Vague tasks ("improve the auth flow") get vague results.

Your thinking decouples from execution — design all tasks in one burst, let agents execute while you do other things.

## 3. Run parallel agents with worktrees

Use `/worktree` to create isolated git worktrees so multiple agents work the same repo without conflicts:

```
/worktree create feat/auth-rework    # Terminal 1
/worktree create feat/rate-limiting  # Terminal 2
```

Each agent works in its own directory. `committer` prevents staging conflicts. Merge when done.

## 4. Task queue — sequential tasks, one shot

Claude processes messages in order — send all tasks at once and go do something else:

```
1. Fix the null pointer in UserService.getUserById()
2. Add input validation to all POST endpoints
3. Update the API docs in README.md
```

No waiting required. You're free from the moment you send.

## 5. Recommended terminal setup

The fastest input experience combines a GPU-accelerated terminal with split panes and voice input.

**Terminal: Ghostty** (recommended)

Ghostty renders at 120fps with near-zero latency — noticeably faster than iTerm2 or the default macOS Terminal. Split panes let you watch multiple agents simultaneously without switching windows.

```
# Ghostty split layout for parallel agents
┌────────────────────────┬────────────────────────┐
│  cc (interactive)      │  cc -p task-002.md     │
│  ↑ your main session   │  ↑ background worker   │
├────────────────────────┼────────────────────────┤
│  cc -p task-001.md     │  git log --oneline -10 │
│  ↑ background worker   │  ↑ monitor commits      │
└────────────────────────┴────────────────────────┘
```

Ghostty keybindings for split panes:
- `Cmd+D` — split right
- `Cmd+Shift+D` — split down
- `Cmd+Option+Arrow` — navigate panes

**Voice input** (reduces typing fatigue significantly)

Instead of typing tasks, dictate them. This is particularly effective for the Orchestrator chat — you can have a natural conversation with the AI.

| Platform | Tool | Setup |
|----------|------|-------|
| macOS | System voice dictation | System Settings → Keyboard → Dictation → enable, set shortcut |
| macOS | [Whisper transcription](https://github.com/openai/whisper) | `brew install whisper-cpp` + configure shortcut |
| Linux | `nerd-dictation` | `pip install nerd-dictation` — uses Vosk offline model |
| All | SuperWhisper / Wispr Flow | GUI apps with hotkey push-to-talk, works in any text field |

Workflow: press hotkey → speak → release → text appears in terminal. Effective for 30–200 word task descriptions.
