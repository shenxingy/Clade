[English](configuration.md) | [中文](configuration.zh-CN.md)

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
