#!/usr/bin/env bash
# test-install.sh — CI executes what install.sh actually ships.
#
# Runs install.sh against a THROWAWAY $HOME under /tmp (never the real home)
# from a THROWAWAY copy of the repo. Covers: clean install, source immutability,
# bytecode exclusion, idempotent re-run, executable
# hooks, generated skill catalog, Cross-Project Rules preservation across
# reinstall (regression for commit ab06c33), settings.json hook-merge
# preserving unrelated keys, and symlink resolution.
#
# Usage: bash tests/test-install.sh

set -uo pipefail

# ─── Harness ──────────────────────────────────────────────────────────

TESTS_RUN=0
TESTS_PASSED=0
TESTS_FAILED=0

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
NC='\033[0m'

pass() {
  TESTS_RUN=$((TESTS_RUN + 1)); TESTS_PASSED=$((TESTS_PASSED + 1))
  echo -e "  ${GREEN}✓${NC} $1"
}

fail() {
  TESTS_RUN=$((TESTS_RUN + 1)); TESTS_FAILED=$((TESTS_FAILED + 1))
  echo -e "  ${RED}✗${NC} $1"
  [[ -n "${2:-}" ]] && echo -e "    ${RED}→ $2${NC}"
}

section() { echo ""; echo -e "${YELLOW}━━━ $1 ━━━${NC}"; }

# ─── Sandbox setup ───────────────────────────────────────────────────

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REAL_HOME="$HOME"

SANDBOX="$(mktemp -d /tmp/clade-install-test-XXXXXX)"

# HARD SAFETY GATE: everything below operates on $HOME — refuse to continue
# unless the sandbox (and therefore the fake HOME) is provably under /tmp.
case "$SANDBOX" in
  /tmp/clade-install-test-*) : ;;
  *) echo "FATAL: sandbox '$SANDBOX' is not under /tmp — aborting before any write"; exit 1 ;;
esac

export HOME="$SANDBOX/home"
mkdir -p "$HOME"
case "$HOME" in
  /tmp/*) : ;;
  *) echo "FATAL: \$HOME '$HOME' is not under /tmp — aborting"; exit 1 ;;
esac
if [[ "$HOME" == "$REAL_HOME" ]]; then
  echo "FATAL: fake HOME equals real HOME — aborting"
  exit 1
fi

cleanup() { rm -rf "$SANDBOX"; }
trap cleanup EXIT

# Run from a throwaway copy of the repo (working tree, so uncommitted changes
# count) and seed artifacts that must never be deployed.
SRC="$SANDBOX/repo"
mkdir -p "$SRC"
tar -C "$REPO_ROOT" \
  --exclude='.git' \
  --exclude='orchestrator/.venv' \
  --exclude='node_modules' \
  --exclude='__pycache__' \
  -cf - . | tar -xf - -C "$SRC"

mkdir -p "$SRC/configs/scripts/__pycache__"
mkdir -p "$SRC/configs/skills/delivery/scripts/__pycache__"
printf 'stale bytecode\n' > "$SRC/configs/scripts/__pycache__/stale.cpython-312.pyc"
printf 'stale bytecode\n' > "$SRC/configs/skills/delivery/scripts/__pycache__/stale.cpython-312.pyc"

# A local install may diagnose stale repository facts, but must never rewrite
# the checkout. Make the copied fact intentionally stale to exercise that path.
python3 - "$SRC/docs/facts.json" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
data = json.loads(path.read_text())
data["facts"][0]["value"] = 0
path.write_text(json.dumps(data, indent=2) + "\n")
PY
cp "$SRC/docs/facts.json" "$SANDBOX/facts-before-install.json"

echo "Sandbox: $SANDBOX"
echo "Fake HOME: $HOME"

# A shell rc file so the alias step has something to append to
touch "$HOME/.bashrc"

# ─── Suite 1: Fresh install ───────────────────────────────────────────

section "Fresh install into empty \$HOME"

install_log="$SANDBOX/install-1.log"
if bash "$SRC/install.sh" </dev/null >"$install_log" 2>&1; then
  pass "install.sh exits 0 on fresh install"
else
  fail "install.sh exits 0 on fresh install" "see $install_log"
  tail -30 "$install_log"
fi

CLAUDE_DIR="$HOME/.claude"

[[ -d "$CLAUDE_DIR/hooks" ]] && pass "hooks dir created" || fail "hooks dir created"

hook_count=0; nonexec=0
for hook in "$CLAUDE_DIR/hooks/"*.sh; do
  [[ -f "$hook" ]] || continue
  hook_count=$((hook_count + 1))
  [[ -x "$hook" ]] || nonexec=$((nonexec + 1))
done
if [[ $hook_count -gt 0 && $nonexec -eq 0 ]]; then
  pass "all $hook_count installed hooks are executable"
else
  fail "all installed hooks are executable" "$hook_count hooks, $nonexec not executable"
fi

# Path-scoped rules: rule-injector.sh ships and its global rules dir exists
[[ -d "$CLAUDE_DIR/rules" ]] \
  && pass "global rules dir created (~/.claude/rules)" \
  || fail "global rules dir created (~/.claude/rules)"
[[ -x "$CLAUDE_DIR/hooks/rule-injector.sh" ]] \
  && pass "rule-injector.sh installed and executable" \
  || fail "rule-injector.sh installed and executable"

# Output styles: the one primitive that edits the SYSTEM prompt, so CLAUDE.md
# cannot substitute for it. Shipped but never auto-activated.
[[ -d "$CLAUDE_DIR/output-styles" ]] \
  && pass "output-styles dir created (~/.claude/output-styles)" \
  || fail "output-styles dir created (~/.claude/output-styles)"

style_count=0; style_bad=0
for style in "$CLAUDE_DIR/output-styles/"*.md; do
  [[ -f "$style" ]] || continue
  style_count=$((style_count + 1))
  # A style missing keep-coding-instructions silently DROPS Claude Code's
  # built-in engineering instructions — catastrophic for a coding toolkit.
  head -1 "$style" | grep -q '^---$' || style_bad=$((style_bad + 1))
  grep -q '^description:' "$style" || style_bad=$((style_bad + 1))
  grep -q '^keep-coding-instructions: true$' "$style" || style_bad=$((style_bad + 1))
done
if [[ $style_count -gt 0 && $style_bad -eq 0 ]]; then
  pass "all $style_count output styles have frontmatter and keep coding instructions"
else
  fail "output styles well-formed" "$style_count styles, $style_bad frontmatter problems"
fi

# Shipping a style must not silently change how every session talks.
if grep -q '"outputStyle"' "$CLAUDE_DIR/settings.json" 2>/dev/null; then
  fail "install does not activate an output style" "settings.json sets outputStyle"
else
  pass "install ships output styles without activating one"
fi

# Mid-flight worker steering: mailbox-drain.sh ships with the hook set
[[ -x "$CLAUDE_DIR/hooks/mailbox-drain.sh" ]] \
  && pass "mailbox-drain.sh installed and executable" \
  || fail "mailbox-drain.sh installed and executable"

agent_count=$(ls "$CLAUDE_DIR/agents/"*.md 2>/dev/null | wc -l | tr -d ' ')
[[ "$agent_count" -gt 0 ]] && pass "agents installed ($agent_count)" || fail "agents installed"

CODEX_DIR="$HOME/.codex"
codex_agent_count=$(ls "$CODEX_DIR/agents/"*.toml 2>/dev/null | wc -l | tr -d ' ')
[[ "$codex_agent_count" -eq 2 ]] \
  && pass "Codex cheap-tier agents installed ($codex_agent_count)" \
  || fail "Codex cheap-tier agents installed" "found $codex_agent_count, want 2"
grep -q '^## Adaptive Delegation$' "$CODEX_DIR/AGENTS.md" \
  && pass "Codex adaptive-delegation instructions installed" \
  || fail "Codex adaptive-delegation instructions installed"
grep -q '^## Delivery Completion$' "$CODEX_DIR/AGENTS.md" \
  && pass "Codex delivery-completion instructions installed" \
  || fail "Codex delivery-completion instructions installed"
grep -q 'Never report `DONE` while task-owned changes are uncommitted' "$CODEX_DIR/AGENTS.md" \
  && pass "Codex dirty-DONE guard installed" \
  || fail "Codex dirty-DONE guard installed"

script_count=$(ls "$CLAUDE_DIR/scripts/"*.sh 2>/dev/null | wc -l | tr -d ' ')
[[ "$script_count" -gt 0 ]] && pass "scripts installed ($script_count)" || fail "scripts installed"

if find "$CLAUDE_DIR/scripts" "$CLAUDE_DIR/skills" \
    \( -type d -name __pycache__ -o -type f \( -name '*.pyc' -o -name '*.pyo' \) \) \
    -print -quit | grep -q .; then
  fail "install excludes Python bytecode caches"
else
  pass "install excludes Python bytecode caches"
fi

if cmp -s "$SRC/docs/facts.json" "$SANDBOX/facts-before-install.json"; then
  pass "install leaves source checkout facts unchanged"
else
  fail "install leaves source checkout facts unchanged"
fi

# SessionEnd shadow cleanup ships with the hook set
[[ -x "$CLAUDE_DIR/hooks/session-end-cleanup.sh" ]] \
  && pass "session-end-cleanup.sh installed and executable" \
  || fail "session-end-cleanup.sh installed and executable"

# Subagent recursion cap — "subagents must not delegate recursively" needs a
# real control now that Claude Code 2.1.221 defaults the spawn depth to 3.
if command -v jq &>/dev/null; then
  depth=$(jq -r '.env.CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH // ""' \
    "$CLAUDE_DIR/settings.json" 2>/dev/null)
  [[ "$depth" == "1" ]] \
    && pass "fresh install caps subagent spawn depth at 1" \
    || fail "fresh install caps subagent spawn depth at 1" "got '$depth'"

  # The depth merge must not have wiped the template's own env keys.
  if jq -e '.env | has("TG_BOT_TOKEN") and has("TG_CHAT_ID")' \
      "$CLAUDE_DIR/settings.json" >/dev/null 2>&1; then
    pass "depth merge preserves the template's env keys"
  else
    fail "depth merge preserves the template's env keys"
  fi
fi

# ─── Suite 2: Generated skill catalog ────────────────────────────────

section "Generated skill catalog (available_skills.md)"

CATALOG="$CLAUDE_DIR/available_skills.md"
if [[ -s "$CATALOG" ]]; then
  pass "available_skills.md generated and non-empty"
else
  fail "available_skills.md generated and non-empty"
fi

skill_entries=$(grep -c '^## ' "$CATALOG" 2>/dev/null || true)
skill_entries=${skill_entries:-0}
if [[ "$skill_entries" -gt 0 ]]; then
  pass "catalog lists $skill_entries skills (>0)"
else
  fail "catalog lists >0 skills"
fi

grep -q '^## commit$' "$CATALOG" \
  && pass "catalog contains the commit skill" \
  || fail "catalog contains the commit skill"

# Regression: folded `description: >` frontmatter used to surface as a bare
# '>' line in the catalog (line-based awk parser)
if grep -qx '>' "$CATALOG"; then
  fail "catalog has no mangled '>' description lines"
else
  pass "catalog has no mangled '>' description lines"
fi

# Migration (2026-07-10): the agents/ mirror was dropped — CC native skill
# discovery replaced it and the 20KB copy overflowed the hook inline limit.
# install.sh now removes any stale copy; assert the cleanup actually runs.
if [[ -e "$CLAUDE_DIR/agents/available-skills.md" ]]; then
  fail "stale agents/available-skills.md mirror removed by install"
else
  pass "stale agents/available-skills.md mirror removed by install"
fi

# ─── Suite 3: Reinstall preserves learned rules + settings ────────────

section "Reinstall preserves Cross-Project Rules and settings"

SENTINEL_RULE="learned-rule-sentinel-7f3a"
CODEX_SENTINEL="codex-user-rule-sentinel-28c1"
{
  cat "$CLAUDE_DIR/CLAUDE.md"
  echo ""
  echo "## Cross-Project Rules"
  echo "- $SENTINEL_RULE: never delete me"
} > "$CLAUDE_DIR/CLAUDE.md.new"
mv "$CLAUDE_DIR/CLAUDE.md.new" "$CLAUDE_DIR/CLAUDE.md"
printf '\n## User Rules\n- %s\n' "$CODEX_SENTINEL" >> "$CODEX_DIR/AGENTS.md"

ENV_SENTINEL="user-env-sentinel-4b9d"
if command -v jq &>/dev/null; then
  # Seed BOTH a top-level user key and a user-authored key inside `env`. The
  # depth cap lands in `env`, which — unlike `.hooks` — is user-owned territory,
  # so it must be merged into rather than replaced.
  jq --arg s "$ENV_SENTINEL" \
    '. + {model: "sentinel-model-keep"}
     | .env = ((.env // {}) + {MY_OWN_VAR: $s})' \
    "$CLAUDE_DIR/settings.json" \
    > "$CLAUDE_DIR/settings.json.new" 2>/dev/null \
    && mv "$CLAUDE_DIR/settings.json.new" "$CLAUDE_DIR/settings.json"

  # Reproduce the real upgrade state: every machine installed before the deny
  # list shipped carries settings.json with NO permissions key at all, because
  # the merge path only ever wrote .hooks and .statusLine. Seed a user-authored
  # allow + deny alongside it so the union is exercised, not just the empty case.
  jq '.permissions = {allow: ["Bash(mytool:*)"], deny: ["Read(~/my-secrets/**)"]}' \
    "$CLAUDE_DIR/settings.json" \
    > "$CLAUDE_DIR/settings.json.new" 2>/dev/null \
    && mv "$CLAUDE_DIR/settings.json.new" "$CLAUDE_DIR/settings.json"
fi

# Seed a stale pre-migration mirror so the reinstall exercises the cleanup path
echo "stale pre-2026-07-10 mirror" > "$CLAUDE_DIR/agents/available-skills.md"
mkdir -p "$CLAUDE_DIR/skills/ads/references/references" "$CLAUDE_DIR/skills/private"
echo "stale nested copy" > "$CLAUDE_DIR/skills/ads/references/references/stale.md"
printf '%s\n' '---' 'name: private' 'description: User-owned test skill.' '---' > "$CLAUDE_DIR/skills/private/SKILL.md"

# ~/.claude/output-styles/ is shared with the user's own styles, so the installer
# copies by name instead of mirroring the directory — a mirror would delete these.
mkdir -p "$CLAUDE_DIR/output-styles"
printf '%s\n' '---' 'name: My Own Style' 'description: User-authored.' '---' \
  > "$CLAUDE_DIR/output-styles/my-own.md"

install_log2="$SANDBOX/install-2.log"
if bash "$SRC/install.sh" </dev/null >"$install_log2" 2>&1; then
  pass "second install.sh run exits 0 (idempotent)"
else
  fail "second install.sh run exits 0 (idempotent)" "see $install_log2"
  tail -30 "$install_log2"
fi

if [[ -e "$CLAUDE_DIR/agents/available-skills.md" ]]; then
  fail "reinstall migrates away stale agents/available-skills.md"
else
  pass "reinstall migrates away stale agents/available-skills.md"
fi

if [[ -e "$CLAUDE_DIR/skills/ads/references/references" ]]; then
  fail "reinstall removes stale nested repo-managed skill content"
else
  pass "reinstall removes stale nested repo-managed skill content"
fi
[[ -f "$CLAUDE_DIR/skills/private/SKILL.md" ]] \
  && pass "reinstall preserves unrelated user-owned skills" \
  || fail "reinstall preserves unrelated user-owned skills"

[[ -f "$CLAUDE_DIR/output-styles/my-own.md" ]] \
  && pass "reinstall preserves user-authored output styles" \
  || fail "reinstall preserves user-authored output styles"

# Regression for ab06c33: plain cp used to clobber the learned-rules section
sentinel_count=$(grep -c "$SENTINEL_RULE" "$CLAUDE_DIR/CLAUDE.md" 2>/dev/null || true)
sentinel_count=${sentinel_count:-0}
if [[ "$sentinel_count" -eq 1 ]]; then
  pass "Cross-Project Rules survive reinstall (exactly once)"
else
  fail "Cross-Project Rules survive reinstall" "sentinel found $sentinel_count times (want 1)"
fi

grep -q "Agent Ground Rules" "$CLAUDE_DIR/CLAUDE.md" \
  && pass "Agent Ground Rules present after reinstall" \
  || fail "Agent Ground Rules present after reinstall"

codex_sentinel_count=$(grep -c "$CODEX_SENTINEL" "$CODEX_DIR/AGENTS.md" 2>/dev/null || true)
codex_block_count=$(grep -c '<!-- BEGIN CLADE ADAPTIVE DELEGATION -->' "$CODEX_DIR/AGENTS.md" 2>/dev/null || true)
codex_delivery_count=$(grep -c '^## Delivery Completion$' "$CODEX_DIR/AGENTS.md" 2>/dev/null || true)
[[ "$codex_sentinel_count" -eq 1 ]] \
  && pass "Codex user instructions survive reinstall" \
  || fail "Codex user instructions survive reinstall" "sentinel found $codex_sentinel_count times"
[[ "$codex_block_count" -eq 1 ]] \
  && pass "Codex managed instructions remain idempotent" \
  || fail "Codex managed instructions remain idempotent" "block found $codex_block_count times"
[[ "$codex_delivery_count" -eq 1 ]] \
  && pass "Codex delivery instructions remain idempotent" \
  || fail "Codex delivery instructions remain idempotent" "section found $codex_delivery_count times"

if command -v jq &>/dev/null; then
  model_val=$(jq -r '.model // ""' "$CLAUDE_DIR/settings.json" 2>/dev/null)
  [[ "$model_val" == "sentinel-model-keep" ]] \
    && pass "settings.json merge preserves unrelated keys" \
    || fail "settings.json merge preserves unrelated keys" "model='$model_val'"

  # The deny list is the only permission control that still binds under
  # --dangerously-skip-permissions, which is how every Clade worker spawns.
  # Before 2026-08-29 the merge path never wrote .permissions, so these rules
  # reached fresh installs only and every upgraded machine ran without them.
  missing_deny=""
  while read -r rule; do
    jq -e --arg r "$rule" '.permissions.deny | index($r)' \
      "$CLAUDE_DIR/settings.json" >/dev/null 2>&1 || missing_deny="$missing_deny $rule"
  done < <(jq -r '.permissions.deny[]' "$SRC/templates/settings.json")
  [[ -z "$missing_deny" ]] \
    && pass "reinstall merges the template deny rules into existing settings.json" \
    || fail "reinstall merges the template deny rules into existing settings.json" \
            "missing:$missing_deny"

  jq -e '.permissions.deny | index("Read(~/my-secrets/**)")' \
    "$CLAUDE_DIR/settings.json" >/dev/null 2>&1 \
    && pass "reinstall preserves a user-authored deny rule" \
    || fail "reinstall preserves a user-authored deny rule"

  jq -e '.permissions.allow | index("Bash(mytool:*)")' \
    "$CLAUDE_DIR/settings.json" >/dev/null 2>&1 \
    && pass "reinstall preserves a user-authored allow rule" \
    || fail "reinstall preserves a user-authored allow rule"

  # Deny-only union on purpose: silently adopting the template's allow list
  # would grant an autonomous worker capability the user never opted into.
  jq -e '.permissions.allow | index("Bash(pytest:*)")' \
    "$CLAUDE_DIR/settings.json" >/dev/null 2>&1 \
    && fail "reinstall does not silently widen the allow list" \
            "template allow rule leaked into an existing settings.json" \
    || pass "reinstall does not silently widen the allow list"

  dup_deny=$(jq -r '.permissions.deny | length as $n | (unique | length) as $u
                    | if $n == $u then "ok" else "dupes" end' \
             "$CLAUDE_DIR/settings.json" 2>/dev/null)
  [[ "$dup_deny" == "ok" ]] \
    && pass "deny union de-duplicates across reinstalls" \
    || fail "deny union de-duplicates across reinstalls" "$dup_deny"

  hooks_type=$(jq -r '.hooks | type' "$CLAUDE_DIR/settings.json" 2>/dev/null)
  [[ "$hooks_type" == "object" ]] \
    && pass "settings.json has hooks after merge" \
    || fail "settings.json has hooks after merge" "hooks type='$hooks_type'"

  if jq -e '[.hooks.PostToolUse[].hooks[].id] | index("rule-injector")' \
      "$CLAUDE_DIR/settings.json" >/dev/null 2>&1; then
    pass "rule-injector wired into PostToolUse hooks"
  else
    fail "rule-injector wired into PostToolUse hooks"
  fi

  if jq -e '[.hooks.PostToolUse[].hooks[].id] | index("mailbox-drain")' \
      "$CLAUDE_DIR/settings.json" >/dev/null 2>&1; then
    pass "mailbox-drain wired into PostToolUse hooks"
  else
    fail "mailbox-drain wired into PostToolUse hooks"
  fi

  if jq -e '[.hooks.SessionEnd[].hooks[].id] | index("session-end-cleanup")' \
      "$CLAUDE_DIR/settings.json" >/dev/null 2>&1; then
    pass "session-end-cleanup wired into SessionEnd hooks"
  else
    fail "session-end-cleanup wired into SessionEnd hooks"
  fi

  # ── Subagent depth: idempotent, and non-destructive to user env keys ──
  depth=$(jq -r '.env.CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH // ""' \
    "$CLAUDE_DIR/settings.json" 2>/dev/null)
  [[ "$depth" == "1" ]] \
    && pass "subagent depth cap survives reinstall (idempotent)" \
    || fail "subagent depth cap survives reinstall" "got '$depth'"

  env_sentinel_val=$(jq -r '.env.MY_OWN_VAR // ""' "$CLAUDE_DIR/settings.json" 2>/dev/null)
  [[ "$env_sentinel_val" == "$ENV_SENTINEL" ]] \
    && pass "depth merge preserves user-authored keys in env" \
    || fail "depth merge preserves user-authored keys in env" "got '$env_sentinel_val'"

  # A merge that replaced `env` wholesale would also have dropped these.
  if jq -e '.env | has("TG_BOT_TOKEN") and has("TG_CHAT_ID")' \
      "$CLAUDE_DIR/settings.json" >/dev/null 2>&1; then
    pass "reinstall preserves the template env keys alongside the cap"
  else
    fail "reinstall preserves the template env keys alongside the cap"
  fi

  # The cap is a real Claude Code control, not an invented settings key: the
  # 2.1.227 binary reads CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH from the process
  # env (settings `env` feeds it) and has no `maxSubagentDepth` key at all.
  if jq -e 'has("maxSubagentDepth")' "$CLAUDE_DIR/settings.json" >/dev/null 2>&1; then
    fail "no inert maxSubagentDepth key written" "that key does not exist in Claude Code"
  else
    pass "no inert maxSubagentDepth key written"
  fi
else
  echo "  (jq not available — skipping settings merge checks)"
fi

# ─── Suite 4: Windows/Git Bash settings commands ────────────────────

section "Windows/Git Bash fresh + existing settings"

if command -v jq &>/dev/null; then
  WINDOWS_HOME="$SANDBOX/windows-home"
  WINDOWS_BIN="$SANDBOX/windows-bin"
  mkdir -p "$WINDOWS_HOME" "$WINDOWS_BIN"
  touch "$WINDOWS_HOME/.bashrc"

  cat > "$WINDOWS_BIN/uname" <<'SH'
#!/bin/sh
printf '%s\n' 'MINGW64_NT-10.0'
SH
  cat > "$WINDOWS_BIN/cygpath" <<'SH'
#!/bin/sh
printf '%s\n' 'C:\Program Files\Git\bin\bash.exe'
SH
  cat > "$WINDOWS_BIN/bash" <<'SH'
#!/bin/sh
exec /bin/bash "$@"
SH
  chmod +x "$WINDOWS_BIN/uname" "$WINDOWS_BIN/cygpath" "$WINDOWS_BIN/bash"

  windows_install_log="$SANDBOX/install-windows-1.log"
  if HOME="$WINDOWS_HOME" PATH="$WINDOWS_BIN:$PATH" \
      /bin/bash "$SRC/install.sh" </dev/null >"$windows_install_log" 2>&1; then
    pass "Windows/Git Bash fresh install exits 0"
  else
    fail "Windows/Git Bash fresh install exits 0" "see $windows_install_log"
    tail -30 "$windows_install_log"
  fi

  WINDOWS_SETTINGS="$WINDOWS_HOME/.claude/settings.json"
  WINDOWS_PREFIX='"C:\Program Files\Git\bin\bash.exe" -c "exec '
  if jq -e --arg prefix "$WINDOWS_PREFIX" '
      [.. | objects | select(has("command")) | .command
       | startswith($prefix)] | length > 0 and all
    ' "$WINDOWS_SETTINGS" >/dev/null 2>&1; then
    pass "fresh Windows settings wrap every hook + statusLine command"
  else
    fail "fresh Windows settings wrap every hook + statusLine command"
  fi

  jq '. + {model: "windows-sentinel-keep"}' "$WINDOWS_SETTINGS" \
    > "$WINDOWS_SETTINGS.new"
  mv "$WINDOWS_SETTINGS.new" "$WINDOWS_SETTINGS"
  windows_install_log2="$SANDBOX/install-windows-2.log"
  if HOME="$WINDOWS_HOME" PATH="$WINDOWS_BIN:$PATH" \
      /bin/bash "$SRC/install.sh" </dev/null >"$windows_install_log2" 2>&1; then
    pass "Windows/Git Bash reinstall exits 0"
  else
    fail "Windows/Git Bash reinstall exits 0" "see $windows_install_log2"
    tail -30 "$windows_install_log2"
  fi

  if jq -e --arg prefix "$WINDOWS_PREFIX" '
      .model == "windows-sentinel-keep"
      and ([.. | objects | select(has("command")) | .command
            | startswith($prefix)] | length > 0 and all)
    ' "$WINDOWS_SETTINGS" >/dev/null 2>&1; then
    pass "existing Windows settings preserve user keys and wrapped commands"
  else
    fail "existing Windows settings preserve user keys and wrapped commands"
  fi
else
  echo "  (jq not available — skipping Windows settings checks)"
fi

# ─── Suite 5: Idempotency markers ────────────────────────────────────

section "Idempotency markers"

if [[ -f "$CLAUDE_DIR/.kit-checksum" ]]; then
  pass ".kit-checksum written"
  cs1=$(cat "$CLAUDE_DIR/.kit-checksum")
  bash "$SRC/install.sh" </dev/null >/dev/null 2>&1
  cs2=$(cat "$CLAUDE_DIR/.kit-checksum")
  [[ -n "$cs1" && "$cs1" == "$cs2" ]] \
    && pass ".kit-checksum stable across reinstalls" \
    || fail ".kit-checksum stable across reinstalls" "'$cs1' vs '$cs2'"
else
  fail ".kit-checksum written"
fi

[[ "$(cat "$CLAUDE_DIR/.kit-source-dir" 2>/dev/null)" == "$SRC" ]] \
  && pass ".kit-source-dir points at the install source" \
  || fail ".kit-source-dir points at the install source"

# Aliases were appended exactly once across all three install runs
alias_count=$(grep -c "dangerously-skip-permissions" "$HOME/.bashrc" 2>/dev/null || true)
alias_count=${alias_count:-0}
if [[ "$alias_count" -eq 2 ]]; then  # one claude= line + one cc= line
  pass "shell aliases appended exactly once across reinstalls"
else
  fail "shell aliases appended exactly once" "found $alias_count alias lines (want 2)"
fi

# ─── Suite 6: Symlinks resolve ───────────────────────────────────────

section "Symlinks"

for pair in "committer:committer.sh" "slt:statusline-toggle.sh"; do
  link_name="${pair%%:*}"; target_base="${pair##*:}"
  link="$HOME/.local/bin/$link_name"
  if [[ -L "$link" ]]; then
    resolved=$(readlink -f "$link" 2>/dev/null || true)
    # macOS canonicalizes /tmp to /private/tmp, so compare file identity
    # instead of path spelling after readlink -f.
    if [[ -f "$resolved" && "$resolved" -ef "$CLAUDE_DIR/scripts/$target_base" ]]; then
      pass "$link_name symlink resolves to installed $target_base"
    else
      fail "$link_name symlink resolves" "points at '$resolved'"
    fi
  else
    fail "$link_name symlink created"
  fi
done

# ─── Suite 7: Smoke-run installed copies (not the repo copies) ───────

section "Smoke-run installed scripts"

if command -v python3 &>/dev/null; then
  if python3 "$CLAUDE_DIR/scripts/skill_frontmatter.py" catalog "$CLAUDE_DIR/skills" \
      | grep -q '^## commit$'; then
    pass "installed skill_frontmatter.py catalog runs"
  else
    fail "installed skill_frontmatter.py catalog runs"
  fi

  if python3 "$CLAUDE_DIR/scripts/validate-skills.py" "$CLAUDE_DIR/skills" --quiet \
      >/dev/null 2>&1; then
    pass "installed validate-skills.py passes on installed skills"
  else
    fail "installed validate-skills.py passes on installed skills"
  fi

  # Claude Code >=2.1.80 supplies authoritative rate-limit data in the
  # status-line JSON. The installed command must prefer it over its own
  # OAuth/cache fallback so the display tracks the current API response.
  printf 'percent\n' > "$CLAUDE_DIR/.statusline-mode"
  reset_epoch=$(( $(date +%s) + 5 * 86400 ))
  statusline_out=$(printf \
    '{"cwd":"%s","rate_limits":{"seven_day":{"used_percentage":80,"resets_at":%s}}}\n' \
    "$SRC" "$reset_epoch" | bash "$CLAUDE_DIR/statusline-command.sh")
  if [[ "$statusline_out" == *"+53%"* && "$statusline_out" == *"(5d)"* ]]; then
    pass "installed status line prefers native weekly rate-limit data"
  else
    fail "installed status line prefers native weekly rate-limit data" \
      "expected native +53% (5d), got '$statusline_out'"
  fi
else
  echo "  (python3 not available — skipping installed-script smoke runs)"
fi

# committer.sh with no args must print usage and exit non-zero
if bash "$CLAUDE_DIR/scripts/committer.sh" >/dev/null 2>&1; then
  fail "installed committer.sh rejects empty invocation"
else
  pass "installed committer.sh rejects empty invocation"
fi

# ─── Summary ─────────────────────────────────────────────────────────

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
if [[ $TESTS_FAILED -eq 0 ]]; then
  echo -e "  ${GREEN}ALL PASSED${NC} ($TESTS_PASSED/$TESTS_RUN)"
else
  echo -e "  ${RED}$TESTS_FAILED FAILED${NC} / $TESTS_PASSED passed / $TESTS_RUN total"
fi
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

exit "$TESTS_FAILED"
