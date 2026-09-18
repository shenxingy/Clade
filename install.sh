#!/usr/bin/env bash
# install.sh — Deploy Claude Code and Codex customizations to user config dirs.
#
# Idempotent: safe to run multiple times.
# Does NOT overwrite user data (corrections/rules.md, corrections/history.jsonl).
# Merges hooks into existing settings.json without losing other fields.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Cross-platform sha256 (Linux: sha256sum, macOS: shasum -a 256)
if command -v sha256sum &>/dev/null; then
  _SHA256=(sha256sum)
else
  _SHA256=(shasum -a 256)
fi
CLAUDE_DIR="$HOME/.claude"
CODEX_DIR="$HOME/.codex"

echo "Installing Claude Code customizations..."
echo "Source: $SCRIPT_DIR"
echo "Target: $CLAUDE_DIR"
echo ""

# ─── 1. Create directories ───────────────────────────────────────────

echo "Creating directories..."
mkdir -p "$CLAUDE_DIR"/{hooks/lib,agents,skills,scripts,corrections,commands,templates,rules}
mkdir -p "$CODEX_DIR/agents"

# ─── 2. Copy hooks (chmod +x) ────────────────────────────────────────

echo "Installing hooks..."
cp "$SCRIPT_DIR/configs/hooks/"*.sh "$CLAUDE_DIR/hooks/"
chmod +x "$CLAUDE_DIR/hooks/"*.sh
echo "  Installed: $(ls "$SCRIPT_DIR/configs/hooks/"*.sh | xargs -I{} basename {} | tr '\n' ' ')"

# Copy hook libraries
if [[ -d "$SCRIPT_DIR/configs/hooks/lib" ]]; then
  cp "$SCRIPT_DIR/configs/hooks/lib/"*.sh "$CLAUDE_DIR/hooks/lib/"
  echo "  Installed lib: $(ls "$SCRIPT_DIR/configs/hooks/lib/"*.sh | xargs -I{} basename {} | tr '\n' ' ')"
fi

# ─── 3. Copy agents ──────────────────────────────────────────────────

echo "Installing agents..."
cp "$SCRIPT_DIR/configs/agents/"*.md "$CLAUDE_DIR/agents/"
echo "  Installed: $(ls "$SCRIPT_DIR/configs/agents/"*.md | xargs -I{} basename {} | tr '\n' ' ')"

echo "Installing Codex agents..."
cp "$SCRIPT_DIR/configs/codex-agents/"*.toml "$CODEX_DIR/agents/"
echo "  Installed: $(ls "$SCRIPT_DIR/configs/codex-agents/"*.toml | xargs -I{} basename {} | tr '\n' ' ')"

# Merge the Clade-managed adaptive-delegation block without replacing any
# user-authored global Codex instructions.
CODEX_AGENTS="$CODEX_DIR/AGENTS.md"
CODEX_BEGIN='<!-- BEGIN CLADE ADAPTIVE DELEGATION -->'
CODEX_END='<!-- END CLADE ADAPTIVE DELEGATION -->'
CODEX_TMP="$(mktemp)"
if [[ -f "$CODEX_AGENTS" ]]; then
  _codex_begin_count=$(grep -Fxc "$CODEX_BEGIN" "$CODEX_AGENTS" || true)
  _codex_end_count=$(grep -Fxc "$CODEX_END" "$CODEX_AGENTS" || true)
  if [[ "$_codex_begin_count" -eq 1 && "$_codex_end_count" -eq 1 ]]; then
    awk -v begin="$CODEX_BEGIN" -v end="$CODEX_END" '
      $0 == begin { skip=1; next }
      $0 == end { skip=0; next }
      !skip { print }
    ' "$CODEX_AGENTS" > "$CODEX_TMP"
  else
    # Malformed/user-authored marker text must never cause content loss.
    cat "$CODEX_AGENTS" > "$CODEX_TMP"
  fi
fi
{
  cat "$CODEX_TMP"
  [[ ! -s "$CODEX_TMP" ]] || printf '\n'
  printf '%s\n' "$CODEX_BEGIN"
  cat "$SCRIPT_DIR/configs/CODEX_AGENTS.md"
  printf '%s\n' "$CODEX_END"
} > "$CODEX_AGENTS"
rm -f "$CODEX_TMP"

# Codex resolves agent instructions first-filename-wins with NO merge:
# AGENTS.override.md is probed BEFORE AGENTS.md at home scope
# (codex-rs/codex-home/src/instructions/mod.rs:10) and at project scope
# (codex-rs/core/src/agents_md.rs:42), verified at rust-v0.153.4. An override
# sitting beside the file merged just above means Codex reads that instead and
# never sees a byte of the managed block — silently, because every other
# signal, this installer included, reports success.
#
# Report only, the same policy as the unowned-file sweep further down: this is
# the user's own global instruction file. Name the conflict, leave the file
# alone, and still write AGENTS.md so removing the override is the whole fix.
CODEX_OVERRIDE="$CODEX_DIR/AGENTS.override.md"
# -f as well as -s: `[[ -s dir ]]` is true for a directory, and Codex resolves
# a candidate only when its metadata says is_file(). A size test alone warns
# about a directory Codex would never read.
if [[ -f "$CODEX_OVERRIDE" && -s "$CODEX_OVERRIDE" ]]; then
  echo ""
  echo "WARNING: $CODEX_OVERRIDE shadows $CODEX_AGENTS"
  echo "  Codex resolves AGENTS.override.md before AGENTS.md at this scope and"
  echo "  does not merge the two, so the Clade managed block just written to"
  echo "  AGENTS.md will not load while that override file exists."
  echo "  Clade never deletes or moves it. To activate the block, copy it into"
  echo "  AGENTS.override.md or remove that file."
  echo ""
fi

# ─── 4b. Install MCP Server ─────────────────────────────────────────────
_echo() { printf '%s\n' "$*"; }

# Install mcp package in orchestrator venv (if venv exists)
ORCH_VENV_PY="$SCRIPT_DIR/orchestrator/.venv/bin/python"
if [[ -x "$ORCH_VENV_PY" ]]; then
  "$ORCH_VENV_PY" -m pip install --quiet mcp 2>/dev/null && echo "  Installed: mcp (orchestrator venv)" || true
fi

# Copy MCP server script
if [[ -f "$SCRIPT_DIR/orchestrator/mcp_server.py" ]]; then
  cp "$SCRIPT_DIR/orchestrator/mcp_server.py" "$CLAUDE_DIR/scripts/mcp_server.py"
  chmod +x "$CLAUDE_DIR/scripts/mcp_server.py"
  echo "  Installed: MCP server (mcp_server.py)"
  echo ""
  echo "  MCP server — for EXTERNAL clients only (Cursor, Cline, Claude Desktop):"
  echo "    { \"mcpServers\": { \"clade\": { \"command\": \"python\", \"args\": [\"$CLAUDE_DIR/scripts/mcp_server.py\"] } } }"
  echo ""
  echo "  Do NOT register it inside Claude Code or Codex. Skills are already"
  echo "  native there; mounting this duplicates every one of them and spawns"
  echo "  nested agent sessions."
fi

# ─── 4. Mirror repo-managed skills; preserve unrelated user skills ─────

echo "Installing skills..."
for skill_dir in "$SCRIPT_DIR/configs/skills/"/*/; do
  skill_name=$(basename "$skill_dir")
  skill_target="$CLAUDE_DIR/skills/$skill_name"
  case "$skill_target" in
    "$CLAUDE_DIR"/skills/*) ;;
    *) echo "FATAL: unsafe skill target: $skill_target" >&2; exit 1 ;;
  esac
  rm -rf "$skill_target"
  mkdir -p "$skill_target"
  cp -r "$skill_dir". "$skill_target/"
  # Never deploy interpreter caches from a developer checkout. Python will
  # recreate valid bytecode for the installed source when useful.
  find "$skill_target" -type d -name __pycache__ -prune -exec rm -rf {} + 2>/dev/null || true
  find "$skill_target" -type f \( -name '*.pyc' -o -name '*.pyo' \) -delete 2>/dev/null || true
  echo "  Installed skill: $skill_name"
done

# Python resolution: on Windows, `python3` resolves to the Microsoft Store
# stub — it EXISTS on PATH but exits "Permission denied", so `command -v`
# alone is not enough. Probe with an actual run; real Windows installs ship
# `python`, not `python3`.
PYTHON=""
if python3 -c pass &>/dev/null; then
  PYTHON="python3"
elif python -c pass &>/dev/null; then
  PYTHON="python"
fi

# Preflight: validate skill frontmatter (warn-only — CI is the hard gate)
if [[ -n "$PYTHON" ]]; then
  "$PYTHON" "$SCRIPT_DIR/configs/scripts/validate-skills.py" "$SCRIPT_DIR/configs/skills" --quiet \
    || echo "  WARNING: skill frontmatter validation failed (run configs/scripts/validate-skills.py --fix)"
fi

# Generate available_skills.md from installed SKILL.md files
# This file lists all skills with name + description for LLM auto-discovery.
# Uses the shared parser (skill_frontmatter.py — same one mcp_server.py and
# validate-skills.py use); the awk path is a python3-less fallback only.
echo "Generating available_skills.md..."
if [[ -n "$PYTHON" ]]; then
  "$PYTHON" "$SCRIPT_DIR/configs/scripts/skill_frontmatter.py" catalog "$CLAUDE_DIR/skills" \
    > "$CLAUDE_DIR/available_skills.md"
else
  {
    echo "# Available Skills"
    echo ""
    echo "These skills are installed. Use them by mentioning their name naturally."
    echo ""
    for skill_md in "$CLAUDE_DIR/skills/"*/SKILL.md; do
      [[ -f "$skill_md" ]] || continue
      name=$(awk '/^name:/{print $2}' "$skill_md" | tr -d '"' | tr -d "'")
      description=$(awk '/^description:/{print substr($0, index($0,$2))}' "$skill_md" | sed 's/^["'\''"]//;s/["'\''"]$//')
      # Accept both spellings: first-party skills use user_invocable, upstream-synced ones user-invokable
      user_invocable=$(awk '/^user_invocable:|^user-invokable:/{print $2}' "$skill_md" | tr -d '"' | tr -d "'")
      echo "## $name"
      echo "$description"
      if [[ "$user_invocable" == "true" ]]; then
        echo "(can be invoked with /$name)"
      fi
      echo ""
    done
  } > "$CLAUDE_DIR/available_skills.md"
fi
echo "  Generated: $CLAUDE_DIR/available_skills.md"

# Migration (2026-07-10): we used to copy available_skills.md into agents/
# hoping Claude Code would include it in the system prompt. It never did —
# agents/*.md without agent frontmatter are ignored, and native skill
# discovery already surfaces name/description/when_to_use. Remove stale copy.
rm -f "$CLAUDE_DIR/agents/available-skills.md"

# ─── 5. Copy scripts (chmod +x) ──────────────────────────────────────

echo "Installing scripts..."
cp "$SCRIPT_DIR/configs/scripts/"*.sh "$CLAUDE_DIR/scripts/"
chmod +x "$CLAUDE_DIR/scripts/"*.sh
# Also copy Python utility scripts
for f in "$SCRIPT_DIR/configs/scripts/"*.py; do
  [[ -f "$f" ]] && cp "$f" "$CLAUDE_DIR/scripts/" && chmod +x "$CLAUDE_DIR/scripts/$(basename "$f")"
done
echo "  Installed: $(ls "$SCRIPT_DIR/configs/scripts/"*.sh "$SCRIPT_DIR/configs/scripts/"*.py 2>/dev/null | xargs -I{} basename {} | tr '\n' ' ')"

# Explicit named install for design-lint.py: the frontend-design skill's
# completion checklist requires `design-lint html <artifact>` before
# reporting done, so its presence at this path is load-bearing, not
# incidental to the generic *.py sweep above.
if [[ -f "$SCRIPT_DIR/configs/scripts/design-lint.py" ]]; then
  cp "$SCRIPT_DIR/configs/scripts/design-lint.py" "$CLAUDE_DIR/scripts/design-lint.py"
  chmod +x "$CLAUDE_DIR/scripts/design-lint.py"
  echo "  Installed design-lint.py (frontend-design completion-checklist validator)"
fi

# Copy scripts/ subdirectories (e.g. seo/)
for sub_dir in "$SCRIPT_DIR/configs/scripts/"/*/; do
  [[ -d "$sub_dir" ]] || continue
  sub_name=$(basename "$sub_dir")
  [[ "$sub_name" == "__pycache__" ]] && continue
  mkdir -p "$CLAUDE_DIR/scripts/$sub_name"
  cp -r "$sub_dir"* "$CLAUDE_DIR/scripts/$sub_name/" 2>/dev/null || true
  find "$CLAUDE_DIR/scripts/$sub_name" -type d -name __pycache__ -prune -exec rm -rf {} + 2>/dev/null || true
  find "$CLAUDE_DIR/scripts/$sub_name" -type f \( -name '*.pyc' -o -name '*.pyo' \) -delete 2>/dev/null || true
  echo "  Installed scripts/$sub_name/: $(ls "$sub_dir" | wc -l | tr -d ' ') files"
done

# Deploy path-scoped rules. rule-injector.sh (PostToolUse Edit|Write) reads
# ~/.claude/rules/*.md and injects the bodies of the files whose `paths:` glob
# matches what is being edited — so a rule that only matters for shell scripts
# reaches the session at the moment a shell script is written, instead of
# sitting in a 750-line CLAUDE.md that is read once at session start.
#
# This block is why it works at all. install.sh:29 has created ~/.claude/rules
# since the hook landed, nothing ever wrote into it, and the channel sat wired
# and EMPTY — a hook with no content, silent by design, indistinguishable from a
# hook that is working. Found 2026-09-17.
if [[ -d "$SCRIPT_DIR/configs/rules" ]]; then
  cp "$SCRIPT_DIR/configs/rules/"*.md "$CLAUDE_DIR/rules/" 2>/dev/null || true
  echo "  Installed rules/: $(ls "$SCRIPT_DIR/configs/rules/"*.md 2>/dev/null | wc -l | tr -d ' ') path-scoped rule files"
fi

# Deploy models.env (canonical model IDs)
if [[ -f "$SCRIPT_DIR/configs/models.env" ]]; then
  cp "$SCRIPT_DIR/configs/models.env" "$CLAUDE_DIR/models.env"
  echo "  Installed models.env (canonical model IDs)"
fi

# Deploy global CLAUDE.md (agent ground rules).
# Preserve learning-system sections appended locally by auto-audit.sh
# (## Cross-Project Rules) — a plain cp would clobber them on every install.
if [[ -f "$SCRIPT_DIR/configs/CLAUDE.md" ]]; then
  _XPR_TMP=""
  if [[ -f "$CLAUDE_DIR/CLAUDE.md" ]] && grep -q '^## Cross-Project Rules' "$CLAUDE_DIR/CLAUDE.md"; then
    _XPR_TMP=$(mktemp)
    awk '/^## Cross-Project Rules/{found=1} found' "$CLAUDE_DIR/CLAUDE.md" > "$_XPR_TMP"
  fi
  cp "$SCRIPT_DIR/configs/CLAUDE.md" "$CLAUDE_DIR/CLAUDE.md"
  if [[ -n "$_XPR_TMP" && -s "$_XPR_TMP" ]]; then
    printf '\n' >> "$CLAUDE_DIR/CLAUDE.md"
    cat "$_XPR_TMP" >> "$CLAUDE_DIR/CLAUDE.md"
    rm -f "$_XPR_TMP"
    echo "  Installed CLAUDE.md (agent ground rules; preserved Cross-Project Rules)"
  else
    echo "  Installed CLAUDE.md (agent ground rules)"
  fi
fi

# ─── 6. Copy commands ────────────────────────────────────────────────

echo "Installing commands..."
if compgen -G "$SCRIPT_DIR/configs/commands/*.md" > /dev/null 2>&1; then
  cp "$SCRIPT_DIR/configs/commands/"*.md "$CLAUDE_DIR/commands/"
  echo "  Installed: $(ls "$SCRIPT_DIR/configs/commands/"*.md | xargs -I{} basename {} | tr '\n' ' ')"
else
  echo "  (no commands to install)"
fi

# ─── 6b. Symlink committer to ~/.local/bin (for PATH access) ─────────

if [[ -f "$CLAUDE_DIR/scripts/committer.sh" ]]; then
  mkdir -p "$HOME/.local/bin"
  ln -sf "$CLAUDE_DIR/scripts/committer.sh" "$HOME/.local/bin/committer"
  echo "  Symlinked committer → ~/.local/bin/committer"
  # Remind if ~/.local/bin is not in PATH
  if ! echo "$PATH" | grep -q "$HOME/.local/bin"; then
    echo "  WARNING: ~/.local/bin is not in your PATH."
    echo "  Add this to ~/.zshrc or ~/.bashrc:"
    echo '    export PATH="$HOME/.local/bin:$PATH"'
  fi
fi

if [[ -f "$CLAUDE_DIR/scripts/statusline-toggle.sh" ]]; then
  mkdir -p "$HOME/.local/bin"
  ln -sf "$CLAUDE_DIR/scripts/statusline-toggle.sh" "$HOME/.local/bin/slt"
  echo "  Symlinked statusline-toggle → ~/.local/bin/slt  (usage: slt to cycle modes)"
fi

if [[ -f "$CLAUDE_DIR/scripts/devmode.sh" ]]; then
  mkdir -p "$HOME/.local/bin"
  ln -sf "$CLAUDE_DIR/scripts/devmode.sh" "$HOME/.local/bin/devmode"
  chmod +x "$CLAUDE_DIR/scripts/devmode.sh"
  echo "  Symlinked devmode → ~/.local/bin/devmode  (usage: devmode [on|off|status])"
fi

# ─── 6c. Deploy templates ────────────────────────────────────────────

echo "Installing templates..."
if [[ -d "$SCRIPT_DIR/configs/templates" ]]; then
  cp -r "$SCRIPT_DIR/configs/templates/"* "$CLAUDE_DIR/templates/"
  echo "  Installed: $(ls "$SCRIPT_DIR/configs/templates/" | tr '\n' ' ')"
fi

# ─── 6c-2. Deploy output styles ──────────────────────────────────────
# Output styles are the one Claude Code primitive that edits the SYSTEM prompt
# rather than appending a user message, so they reach turns CLAUDE.md cannot.
# Copied by name, never mirrored: ~/.claude/output-styles/ is also where a user
# keeps their own, and this installer has no business deleting those.
# None is activated here — selection is the user's, via /config or the
# `outputStyle` setting.

echo "Installing output styles..."
if compgen -G "$SCRIPT_DIR/configs/output-styles/*.md" > /dev/null 2>&1; then
  mkdir -p "$CLAUDE_DIR/output-styles"
  cp "$SCRIPT_DIR/configs/output-styles/"*.md "$CLAUDE_DIR/output-styles/"
  echo "  Installed: $(ls "$SCRIPT_DIR/configs/output-styles/"*.md | xargs -I{} basename {} | tr '\n' ' ')"
  echo "  Activate with /config → Output style (none is enabled by default)"
else
  echo "  (no output styles to install)"
fi

# ─── 6d. Deploy + configure status line ──────────────────────────────

echo "Configuring status line..."
cp "$SCRIPT_DIR/configs/scripts/statusline-command.sh" "$CLAUDE_DIR/statusline-command.sh"
chmod +x "$CLAUDE_DIR/statusline-command.sh"
echo "  Installed statusline-command.sh"

# ─── 7. Initialize corrections (don't overwrite existing) ────────────

if [[ ! -f "$CLAUDE_DIR/corrections/rules.md" ]]; then
  echo "Initializing corrections/rules.md..."
  cp "$SCRIPT_DIR/templates/corrections/rules.md" "$CLAUDE_DIR/corrections/"
else
  echo "Corrections rules.md already exists — skipping"
fi

if [[ ! -f "$CLAUDE_DIR/corrections/stats.json" ]]; then
  cp "$SCRIPT_DIR/templates/corrections/stats.json" "$CLAUDE_DIR/corrections/"
fi

# ─── 7b. Deploy orchestrator-settings.example.json (reference copy) ──
# Always overwrites the .example file so it tracks _SETTINGS_DEFAULTS. That
# claim used to be false: this copies templates/orchestrator-settings.example.json,
# which was hand-maintained and had drifted to 33 of 75 keys (one of them no
# longer a setting). The template is now GENERATED by
# configs/scripts/regen-settings-example.py with a CI drift gate, so the copy
# really does track the defaults.
# The real ~/.claude/orchestrator-settings.json is left untouched — users
# copy keys they want to override out of the .example.
if [[ -f "$SCRIPT_DIR/templates/orchestrator-settings.example.json" ]]; then
  cp "$SCRIPT_DIR/templates/orchestrator-settings.example.json" \
     "$CLAUDE_DIR/orchestrator-settings.example.json"
  echo "  Installed orchestrator-settings.example.json (reference; copy keys to orchestrator-settings.json to override)"
fi

# ─── 8a. Windows (Git Bash) hook-command shim detection ──────────────
# On Unix, Claude Code expands ~ and runs hook commands via /bin/sh, so a bare
# "~/.claude/hooks/x.sh" works. On Windows the hook runs via cmd.exe, which can
# neither expand ~ nor execute a .sh — so every hook silently no-ops. Detect
# Git Bash (MSYS/MINGW) and, in §8 below, rewrite each command to run through
# bash.exe as `-c "exec ~/..."` (bash -c DOES expand ~; `bash ~/x.sh` would NOT,
# because the script-path argument is not tilde-expanded). Unix is unaffected.
HOOK_BASH=""
case "$(uname -s 2>/dev/null)" in
  MINGW*|MSYS*|CYGWIN*)
    if command -v cygpath &>/dev/null && command -v bash &>/dev/null; then
      HOOK_BASH="$(cygpath -w "$(command -v bash)" 2>/dev/null)"
    fi
    [[ -n "$HOOK_BASH" ]] && echo "  Windows/Git Bash detected — hooks will run via: $HOOK_BASH"
    ;;
esac

# ─── 8. Merge hooks into settings.json ───────────────────────────────

echo "Configuring settings.json..."

if ! command -v jq &>/dev/null; then
  echo "WARNING: jq not found. Cannot merge hooks into settings.json."
  echo "Please install jq and re-run, or manually copy hooks from configs/settings-hooks.json."
else
  HOOKS=$(jq '.hooks' "$SCRIPT_DIR/configs/settings-hooks.json")
  STATUSLINE='{"type":"command","command":"bash ~/.claude/statusline-command.sh"}'

  # Git Bash (Windows): rewrite every hook + statusLine command to run via
  # bash.exe so cmd.exe doesn't choke on bare "~/.claude/..." .sh commands (§8a).
  if [[ -n "$HOOK_BASH" ]]; then
    HOOKS=$(printf '%s' "$HOOKS" | jq --arg bash "$HOOK_BASH" '
      walk(
        if type == "object" and has("command") then
          .command |= ( (if startswith("bash ") then .[5:] else . end) as $i
                        | "\"\($bash)\" -c \"exec \($i)\"" )
        else . end
      )')
    STATUSLINE=$(jq -n --arg bash "$HOOK_BASH" \
      '{type:"command", command:("\"\($bash)\" -c \"exec ~/.claude/statusline-command.sh\"")}')
    echo "  Rewrote hook + statusLine commands to run via Git Bash"
  fi

  # templates/settings.json ships a deny list — Read(~/.ssh/**), Read(~/.aws/**),
  # Read(~/**/.env). Until 2026-08-29 the merge path below wrote only .hooks and
  # .statusLine, so those rules reached fresh installs only: every machine that
  # had ever run install.sh before the deny list existed kept `permissions: null`
  # forever. That is the wrong half to skip. Clade spawns workers with
  # --dangerously-skip-permissions, and deny rules are the one control that still
  # binds under it — they are checked before the bypass, so they are the last
  # thing standing between an autonomous worker and ~/.ssh.
  TEMPLATE_DENY=$(jq -c '.permissions.deny // []' "$SCRIPT_DIR/templates/settings.json")

  if [[ -f "$CLAUDE_DIR/settings.json" ]]; then
    # Merge: hooks + statusLine, and UNION the template's deny rules into
    # whatever the user already has. Deny-only on purpose — a deny is strictly
    # more restrictive, so adding one can never silently widen what an agent may
    # do, whereas quietly unioning `allow` would grant capability the user never
    # opted into. Existing user deny entries are preserved and de-duplicated.
    jq --argjson hooks "$HOOKS" --argjson sl "$STATUSLINE" --argjson deny "$TEMPLATE_DENY" \
      '.hooks = $hooks
       | .statusLine = $sl
       | .permissions = ((.permissions // {})
                         | .deny = ((.deny // []) + $deny | unique))' \
      "$CLAUDE_DIR/settings.json" > "$CLAUDE_DIR/.settings.json.$$"
    mv "$CLAUDE_DIR/.settings.json.$$" "$CLAUDE_DIR/settings.json"
    echo "  Merged hooks + statusLine + deny rules into existing settings.json"
  else
    # Fresh install: retain template defaults, but inject the same computed
    # hook/status-line commands as the merge path (including Windows wrappers).
    jq --argjson hooks "$HOOKS" --argjson sl "$STATUSLINE" \
      '.hooks = $hooks | .statusLine = $sl' \
      "$SCRIPT_DIR/templates/settings.json" > "$CLAUDE_DIR/.settings.json.$$"
    mv "$CLAUDE_DIR/.settings.json.$$" "$CLAUDE_DIR/settings.json"
    echo "  Created settings.json from template"
    echo ""
    echo "  IMPORTANT: Configure these in ~/.claude/settings.json:"
    echo "    - TG_BOT_TOKEN: Your Telegram bot token (for notifications)"
    echo "    - TG_CHAT_ID: Your Telegram chat ID"
  fi
fi

# ─── 8b. Enforce the subagent recursion limit ────────────────────────
# "Subagents must not delegate recursively" (Agent Ground Rules) was an
# unenforced convention. Claude Code 2.1.221 raised the default subagent spawn
# depth from 1 to 3, so the rule now needs a real control behind it.
#
# The control is the CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH env var, which
# settings.json `env` supplies to every session. Verified against the 2.1.227
# binary: the Agent tool is offered only while `agentDepth < maxSpawnDepth`, so
# depth 1 = the main loop may spawn, a subagent may not. There is no
# `maxSubagentDepth` settings key — see .claude/decisions.md.
#
# MERGE, never replace. §8 above may replace `.hooks` wholesale because that
# section is entirely repo-managed; `env` is not — it is where users keep
# TG_BOT_TOKEN, TG_CHAT_ID and their own variables. Read, add one key, write back.
if command -v jq &>/dev/null && [[ -f "$CLAUDE_DIR/settings.json" ]]; then
  if jq '.env = ((.env // {}) + {"CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH": "1"})' \
      "$CLAUDE_DIR/settings.json" > "$CLAUDE_DIR/.settings.json.$$" 2>/dev/null; then
    mv "$CLAUDE_DIR/.settings.json.$$" "$CLAUDE_DIR/settings.json"
    echo "  Capped subagent spawn depth at 1 (env.CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH)"
  else
    rm -f "$CLAUDE_DIR/.settings.json.$$"
    echo "  WARNING: could not set CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH in settings.json"
  fi
fi

# ─── 8c. Optional: standing multi-agent orchestration (--ultracode) ──
# Off unless asked for. `ultracode: true` makes Claude Code plan a Workflow for
# every substantive task instead of waiting to be asked — the difference between
# "I told it to open agents" and "it opens them". Verified in the 2.1.258
# settings schema: "Enable ultracode for the session: xhigh effort plus standing
# dynamic-workflow orchestration. Requires workflows to be enabled and an
# xhigh-capable model."
#
# NOT a default, deliberately. It raises effort to xhigh and authorises
# multi-agent fan-out on ordinary tasks, so it spends materially more per turn.
# That is the right trade for someone driving a fleet from the terminal and the
# wrong one for someone who installed this to get a commit hook.
#
# workflowSizeGuideline bounds the blast radius: small <5 agents, medium <15
# (the default when unset), large <50.
_ultracode_requested=false
_ultracode_size="medium"
for arg in "$@"; do
  [[ "$arg" == "--ultracode" ]] && _ultracode_requested=true
  if [[ "$arg" == --ultracode=* ]]; then
    _ultracode_requested=true
    _ultracode_size="${arg#--ultracode=}"
  fi
done
if [[ "$_ultracode_requested" == true ]]; then
  case "$_ultracode_size" in
    small|medium|large) ;;
    *) echo "  WARNING: --ultracode=$_ultracode_size is not small|medium|large; using medium"
       _ultracode_size="medium" ;;
  esac
  if command -v jq &>/dev/null && [[ -f "$CLAUDE_DIR/settings.json" ]]; then
    # Merge, never replace: settings.json holds the user's own keys.
    if jq --arg sz "$_ultracode_size" \
         '. + {ultracode: true, workflowSizeGuideline: $sz}' \
         "$CLAUDE_DIR/settings.json" > "$CLAUDE_DIR/.settings.json.$$" 2>/dev/null; then
      mv "$CLAUDE_DIR/.settings.json.$$" "$CLAUDE_DIR/settings.json"
      echo "  Standing multi-agent orchestration ON (ultracode, workflowSizeGuideline=$_ultracode_size)"
      echo "    Turn it off with: jq 'del(.ultracode)' ~/.claude/settings.json"
    else
      rm -f "$CLAUDE_DIR/.settings.json.$$"
      echo "  WARNING: could not set ultracode in settings.json"
    fi
  else
    echo "  WARNING: --ultracode needs jq and an existing $CLAUDE_DIR/settings.json"
  fi
fi

# ─── 9. Set up shell aliases (cc + claude bypass) ────────────────────

echo "Configuring shell aliases..."

setup_alias() {
  local rc_file="$1"
  # return 0, not bare return: under `set -e` a missing rc file (fresh
  # machine without ~/.zshrc) would otherwise abort the whole install here,
  # silently skipping ground rules, doc-align, and kit version markers.
  [[ -f "$rc_file" ]] || return 0
  if grep -q "dangerously-skip-permissions" "$rc_file" 2>/dev/null; then
    echo "  Aliases already in $rc_file — skipping"
    return 0
  fi
  cat >> "$rc_file" << 'SHELLEOF'

# Claude Code: skip permission prompts (added by clade)
alias claude='claude --dangerously-skip-permissions'
alias cc='claude --dangerously-skip-permissions'
SHELLEOF
  echo "  Added aliases to $rc_file"
}

setup_alias "$HOME/.zshrc"
setup_alias "$HOME/.bashrc"
echo "  Run: source ~/.zshrc  (or open a new terminal) to activate"

# ─── 10. (removed) Agent Ground Rules deployment ─────────────────────
# Section 8 already deploys configs/CLAUDE.md — the maintained source — to
# ~/.claude/CLAUDE.md, preserving the Cross-Project Rules tail. This section
# copied templates/CLAUDE.md instead, a frozen 2026-02 snapshot, and only when
# the target did not already contain "Agent Ground Rules". On any machine that
# had ever installed, it printed "already has ... skipping" and did nothing; on
# a fresh one it raced §8 with stale content. Removed 2026-09-12.

# ─── 10b. Verify doc-align facts ─────────────────────────────────────
# Installation must not mutate its source checkout. Report stale derived
# facts, but leave repository updates to the normal branch/commit/PR flow.
if [[ -f "$SCRIPT_DIR/docs/facts.json" ]] && [[ -n "$PYTHON" ]]; then
  "$PYTHON" "$CLAUDE_DIR/scripts/doc-align.py" verify --root "$SCRIPT_DIR" --quiet 2>/dev/null || true
fi

# ─── 11. Write staleness detection markers ───────────────────────────

echo "Writing kit version markers..."
echo "$SCRIPT_DIR" > "$CLAUDE_DIR/.kit-source-dir"
# Combined checksum of all source configs — session-context.sh and start.sh compare against this
source "$SCRIPT_DIR/configs/hooks/lib/kit-checksum.sh"
kit_checksum "$SCRIPT_DIR/configs" > "$CLAUDE_DIR/.kit-checksum"
echo "  Written .kit-source-dir + .kit-checksum for stale-script detection"

# ─── 11b. Report installed files this repo does not install ──────────
# Skills are MIRRORED (rm -rf per skill dir, see the skills loop above), but
# hooks and scripts are plain copies — nothing ever prunes them. A file an
# older version of this repo deployed, or one dropped in by hand, therefore
# survives every reinstall unseen.
#
# Report only, never delete: 0164075 backported iloop-hook.sh after 909092f
# had deleted it, so "absent from the repo today" is not the same as "safe to
# remove", and ~/.claude/hooks is shared with whatever else the user installs.
#
# The expected set is what install.sh DEPLOYS, not what configs/ contains.
# Deriving it from configs/ alone reports ~/.claude/scripts/mcp_server.py —
# installed above from orchestrator/mcp_server.py — as an orphan.
{
  _clade_unowned() {
    local dir="$1"
    local expected="$2"
    local installed
    [[ -d "$dir" ]] || return 0
    installed=$(
      for _f in "$dir"/*; do
        [[ -f "$_f" ]] && printf '%s\n' "${_f##*/}"
      done
    )
    comm -23 \
      <(printf '%s\n' "$installed" | grep -v '^$' | LC_ALL=C sort) \
      <(printf '%s\n' "$expected" | grep -v '^$' | LC_ALL=C sort -u)
  }

  _expected_hooks=$(
    for _f in "$SCRIPT_DIR/configs/hooks/"*.sh; do
      [[ -f "$_f" ]] && printf '%s\n' "${_f##*/}"
    done
  )
  _expected_scripts=$(
    for _f in "$SCRIPT_DIR/configs/scripts/"*.sh "$SCRIPT_DIR/configs/scripts/"*.py; do
      [[ -f "$_f" ]] && printf '%s\n' "${_f##*/}"
    done
    # Installed out of configs/ — keep in step with the mcp_server.py copy above.
    printf '%s\n' "mcp_server.py"
  )

  _unowned=""
  while IFS= read -r _name; do
    [[ -n "$_name" ]] && _unowned+="  hooks/$_name"$'\n'
  done < <(_clade_unowned "$CLAUDE_DIR/hooks" "$_expected_hooks")
  while IFS= read -r _name; do
    [[ -n "$_name" ]] && _unowned+="  scripts/$_name"$'\n'
  done < <(_clade_unowned "$CLAUDE_DIR/scripts" "$_expected_scripts")

  if [[ -n "$_unowned" ]]; then
    _unowned_count=$(printf '%s' "$_unowned" | grep -c '^')
    echo ""
    echo "Files in ~/.claude/hooks and ~/.claude/scripts that Clade does not install:"
    printf '%s' "$_unowned" | head -20
    if [[ "$_unowned_count" -gt 20 ]]; then
      echo "  ... and $((_unowned_count - 20)) more"
    fi
    echo "  Clade never removes these. Review and delete manually if unwanted."
  fi

  unset -f _clade_unowned
  unset _expected_hooks _expected_scripts _unowned _unowned_count _name _f
} || true

# ─── 11c. Kimi Code CLI bridge (opportunistic) ────────────────────────
# Moonshot AI's Kimi Code CLI (package @moonshot-ai/kimi-code, bin `kimi`,
# https://moonshotai.github.io/kimi-code/) is a third agent runtime alongside
# Claude Code and Codex. Only act
# if the user has already run it at least once on this machine (its own
# first-run creates ~/.kimi-code) — never fabricate its config from nothing,
# since region/oauth/device_id are Kimi's own bootstrap state, not ours.
KIMI_DIR="$HOME/.kimi-code"
if [[ -d "$KIMI_DIR" ]]; then
  echo "Installing Kimi Code bridge agents..."
  mkdir -p "$KIMI_DIR/agents"
  cp "$SCRIPT_DIR/configs/kimi-agents/"*.md "$KIMI_DIR/agents/"
  echo "  Installed: $(ls "$SCRIPT_DIR/configs/kimi-agents/"*.md | xargs -I{} basename {} | tr '\n' ' ')"

  echo "Installing Kimi Code bridge hooks..."
  mkdir -p "$KIMI_DIR/hooks"
  cp "$SCRIPT_DIR/configs/kimi-hooks/"*.sh "$KIMI_DIR/hooks/"
  chmod +x "$KIMI_DIR/hooks/"*.sh
  echo "  Installed: $(ls "$SCRIPT_DIR/configs/kimi-hooks/"*.sh | xargs -I{} basename {} | tr '\n' ' ')"

  KIMI_CONFIG="$KIMI_DIR/config.toml"
  if [[ -f "$KIMI_CONFIG" ]]; then
    # Insert a root-level `key = value` line only if that key is not already
    # present ANYWHERE in the file (never overwrite a value the user or Kimi
    # itself set) and only BEFORE the first `[table]` header — TOML resolves
    # a bare key to whichever table most recently opened, so appending at EOF
    # would silently nest it under the last `[section]` instead of the root.
    _kimi_root_insert() {
      local line="$1"
      local key="${line%%=*}"
      key="${key% }"
      grep -qE "^${key}[[:space:]]*=" "$KIMI_CONFIG" && return 0
      awk -v line="$line" '
        !inserted && /^\[/ { print line; inserted=1 }
        { print }
        END { if (!inserted) print line }
      ' "$KIMI_CONFIG" > "$KIMI_CONFIG.clade-tmp" && mv "$KIMI_CONFIG.clade-tmp" "$KIMI_CONFIG"
    }
    _kimi_root_insert 'default_permission_mode = "yolo"'
    _kimi_root_insert "extra_skill_dirs = [\"$CLAUDE_DIR/skills\"]"
    unset -f _kimi_root_insert

    # [[hooks]] is an array-of-tables, not a root scalar: a new entry is
    # always safe to APPEND at EOF (unlike the bare keys above, a `[[hooks]]`
    # header always starts its own table regardless of what precedes it).
    # Idempotency is keyed on the exact `command` value — never re-append the
    # same hook, and never touch a hooks entry the user added by hand.
    _KIMI_GUARDIAN_CMD="$KIMI_DIR/hooks/decision-to-kimi.sh $CLAUDE_DIR/hooks/pre-tool-guardian.sh"
    if ! grep -qF "command = \"$_KIMI_GUARDIAN_CMD\"" "$KIMI_CONFIG"; then
      {
        printf '\n[[hooks]]\n'
        printf 'event = "PreToolUse"\n'
        printf 'matcher = "Bash"\n'
        printf 'command = "%s"\n' "$_KIMI_GUARDIAN_CMD"
        printf 'timeout = 5\n'
      } >> "$KIMI_CONFIG"
      echo "  Configured: PreToolUse/Bash hook -> Clade's dangerous-command guardian (translated via decision-to-kimi.sh)"
    fi
    unset _KIMI_GUARDIAN_CMD

    echo "  Configured: default_permission_mode (yolo if unset), extra_skill_dirs -> $CLAUDE_DIR/skills"
  fi
  unset KIMI_CONFIG

  # Footer line 1 -> Clade's quota pace indicator: the Kimi counterpart of
  # the Claude Code statusLine wired in §8 and of `codex-usage setup`. Kimi
  # reads `[status_line] command` from ~/.kimi-code/tui.toml and runs it
  # with a 300 ms deadline; the launcher deployed above hands off to the
  # kimi-usage skill's helper, which renders from a cache and refreshes it
  # through Kimi's own documented local API (`kimi web`, GET
  # /api/v1/oauth/usage) — never from the OAuth credential file. The helper
  # edits that one key only: a command that is not ours is reported and
  # left alone, and `kimi-usage setup off` (or deleting the line) restores
  # the built-in footer. Wiring only — nothing here boots a Kimi server.
  # Not wired under Git Bash: Kimi runs the command through cmd.exe there,
  # which cannot execute a bash launcher.
  _KIMI_USAGE_HELPER="$CLAUDE_DIR/skills/kimi-usage/scripts/kimi_usage.py"
  if [[ -n "$HOOK_BASH" ]]; then
    echo "  Skipped: Kimi status line (Git Bash: Kimi runs status_line.command via cmd.exe)"
  elif [[ -z "$PYTHON" ]]; then
    echo "  Skipped: Kimi status line (no python3 on PATH)"
  elif [[ ! -f "$KIMI_DIR/tui.toml" ]]; then
    # Kimi writes tui.toml on its first TUI run; same rule as config.toml
    # above — patch Kimi's file, never fabricate it.
    echo "  Skipped: Kimi status line (no tui.toml yet — run kimi once, then re-run install.sh or /kimi-usage setup)"
  elif [[ -f "$_KIMI_USAGE_HELPER" ]]; then
    if _kimi_sl_out=$("$PYTHON" "$_KIMI_USAGE_HELPER" setup 2>&1); then
      echo "  Configured: tui.toml [status_line] -> $KIMI_DIR/hooks/statusline.sh (quota pace; \`kimi-usage setup off\` restores the built-in footer)"
    else
      echo "  Skipped: Kimi status line — ${_kimi_sl_out#kimi-usage: }"
    fi
    unset _kimi_sl_out
  fi
  unset _KIMI_USAGE_HELPER
else
  echo "Kimi Code CLI not detected (~/.kimi-code missing) — skipping Kimi bridge"
  echo "  (install Kimi Code (@moonshot-ai/kimi-code) globally, then re-run install.sh, to enable it)"
fi
unset KIMI_DIR

# ─── 12. Summary ─────────────────────────────────────────────────────

echo ""
# ─── 13. Optional: set up sync (--sync flag) ─────────────────────────────────

for arg in "$@"; do
  if [[ "$arg" == "--sync" ]]; then
    echo ""
    echo "Setting up sync..."
    bash "$SCRIPT_DIR/configs/scripts/sync-setup.sh"
    break
  fi
  if [[ "$arg" == --sync=* ]]; then
    SYNC_BACKEND="${arg#--sync=}"
    echo ""
    echo "Setting up sync (backend: $SYNC_BACKEND)..."
    if [[ "$SYNC_BACKEND" == nfs:* ]]; then
      NFS_PATH="${SYNC_BACKEND#nfs:}"
      bash "$SCRIPT_DIR/configs/scripts/sync-setup.sh" --nfs "$NFS_PATH"
    else
      bash "$SCRIPT_DIR/configs/scripts/sync-setup.sh" "--$SYNC_BACKEND"
    fi
    break
  fi
done

# ─── 14. Sync prompt (if not already handled by --sync flag) ─────────────────

_sync_requested=false
for arg in "$@"; do
  [[ "$arg" == "--sync" || "$arg" == --sync=* ]] && _sync_requested=true && break
done

if [[ "$_sync_requested" == false && ! -f "$CLAUDE_DIR/.sync-config" ]]; then
  # Detect available backend
  _sync_available=""
  if [[ -d "$HOME/shared-nfs" ]]; then
    _sync_available="NFS detected at ~/shared-nfs"
  elif command -v gh &>/dev/null && gh auth status &>/dev/null 2>&1; then
    _sync_available="gh CLI detected"
  fi

  if [[ -n "$_sync_available" ]]; then
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "Sync available ($_sync_available)"
    echo "Enable memory + skills sync across machines? [y/N] "
    read -r _sync_reply 2>/dev/null || _sync_reply="n"
    if [[ "$_sync_reply" =~ ^[Yy]$ ]]; then
      bash "$SCRIPT_DIR/configs/scripts/sync-setup.sh"
    else
      echo "  Skipped. Run './install.sh --sync' anytime to enable."
    fi
  fi
fi

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Installation complete!"
echo ""
echo "Installed components:"
echo "  Hooks:    $(ls "$CLAUDE_DIR/hooks/"*.sh 2>/dev/null | wc -l) scripts"
echo "  Agents:   $(ls "$CLAUDE_DIR/agents/"*.md 2>/dev/null | wc -l) definitions"
echo "  Codex:    $(ls "$CODEX_DIR/agents/"*.toml 2>/dev/null | wc -l) agent definitions"
echo "  Skills:   $(ls -d "$CLAUDE_DIR/skills/"*/ 2>/dev/null | wc -l) skills"
echo "  Scripts:  $(ls "$CLAUDE_DIR/scripts/"*.sh 2>/dev/null | wc -l) scripts"
echo "  Commands: $(ls "$CLAUDE_DIR/commands/"*.md 2>/dev/null | wc -l) commands"
if [[ -d "$HOME/.kimi-code" ]]; then
  echo "  Kimi:     $(ls "$HOME/.kimi-code/agents/"*.md 2>/dev/null | wc -l) bridge agents, $(ls "$HOME/.kimi-code/hooks/"*.sh 2>/dev/null | wc -l) bridge hooks (+ all $(ls -d "$CLAUDE_DIR/skills/"*/ 2>/dev/null | wc -l) skills via extra_skill_dirs)"
fi
echo ""
echo "Next steps:"
echo "  1. source ~/.zshrc   (or ~/.bashrc) to activate shell aliases"
echo "  2. Start a new Claude Code session to activate all hooks"
echo "  3. Use 'cc' to launch Claude Code in fully autonomous mode"
echo "  4. Run ./orchestrator/start.sh to open the Orchestrator Web UI"
echo ""
echo "Optional — enable memory sync across machines:"
echo "  ./install.sh --sync                       # auto-detect NFS or GitHub"
echo "  ./install.sh --sync=nfs:/path/to/nfs      # specify NFS path"
echo "  ./install.sh --sync=github                # force GitHub backend"
echo ""
echo "Optional — standing multi-agent orchestration (spends materially more):"
echo "  ./install.sh --ultracode                   # plan a workflow per task, <15 agents"
echo "  ./install.sh --ultracode=large             # same, up to 50 agents"
echo "  ./install.sh --ultracode=small             # same, under 5 agents"
echo ""
echo "If Clade saves you time, a star helps others find it:"
echo "  https://github.com/shenxingy/Clade"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
