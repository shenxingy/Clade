#!/usr/bin/env bash
# test-install.sh — CI executes what install.sh actually ships.
#
# Runs install.sh against a THROWAWAY $HOME under /tmp (never the real home)
# from a THROWAWAY copy of the repo (install.sh's doc-align step writes into
# the source tree). Covers: clean install, idempotent re-run, executable
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

# install.sh's doc-align step writes into the source tree, so run from a
# throwaway copy of the repo (working tree, so uncommitted changes count).
SRC="$SANDBOX/repo"
mkdir -p "$SRC"
tar -C "$REPO_ROOT" \
  --exclude='.git' \
  --exclude='orchestrator/.venv' \
  --exclude='node_modules' \
  --exclude='__pycache__' \
  -cf - . | tar -xf - -C "$SRC"

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

agent_count=$(ls "$CLAUDE_DIR/agents/"*.md 2>/dev/null | wc -l | tr -d ' ')
[[ "$agent_count" -gt 0 ]] && pass "agents installed ($agent_count)" || fail "agents installed"

script_count=$(ls "$CLAUDE_DIR/scripts/"*.sh 2>/dev/null | wc -l | tr -d ' ')
[[ "$script_count" -gt 0 ]] && pass "scripts installed ($script_count)" || fail "scripts installed"

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

cmp -s "$CATALOG" "$CLAUDE_DIR/agents/available-skills.md" \
  && pass "catalog mirrored into agents/ for system prompt" \
  || fail "catalog mirrored into agents/ for system prompt"

# ─── Suite 3: Reinstall preserves learned rules + settings ────────────

section "Reinstall preserves Cross-Project Rules and settings"

SENTINEL_RULE="learned-rule-sentinel-7f3a"
{
  cat "$CLAUDE_DIR/CLAUDE.md"
  echo ""
  echo "## Cross-Project Rules"
  echo "- $SENTINEL_RULE: never delete me"
} > "$CLAUDE_DIR/CLAUDE.md.new"
mv "$CLAUDE_DIR/CLAUDE.md.new" "$CLAUDE_DIR/CLAUDE.md"

if command -v jq &>/dev/null; then
  jq '. + {model: "sentinel-model-keep"}' "$CLAUDE_DIR/settings.json" \
    > "$CLAUDE_DIR/settings.json.new" 2>/dev/null \
    && mv "$CLAUDE_DIR/settings.json.new" "$CLAUDE_DIR/settings.json"
fi

install_log2="$SANDBOX/install-2.log"
if bash "$SRC/install.sh" </dev/null >"$install_log2" 2>&1; then
  pass "second install.sh run exits 0 (idempotent)"
else
  fail "second install.sh run exits 0 (idempotent)" "see $install_log2"
  tail -30 "$install_log2"
fi

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

if command -v jq &>/dev/null; then
  model_val=$(jq -r '.model // ""' "$CLAUDE_DIR/settings.json" 2>/dev/null)
  [[ "$model_val" == "sentinel-model-keep" ]] \
    && pass "settings.json merge preserves unrelated keys" \
    || fail "settings.json merge preserves unrelated keys" "model='$model_val'"

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
else
  echo "  (jq not available — skipping settings merge checks)"
fi

# ─── Suite 4: Idempotency markers ────────────────────────────────────

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

# ─── Suite 5: Symlinks resolve ───────────────────────────────────────

section "Symlinks"

for pair in "committer:committer.sh" "slt:statusline-toggle.sh"; do
  link_name="${pair%%:*}"; target_base="${pair##*:}"
  link="$HOME/.local/bin/$link_name"
  if [[ -L "$link" ]]; then
    resolved=$(readlink -f "$link" 2>/dev/null || true)
    if [[ -f "$resolved" && "$resolved" == "$CLAUDE_DIR/scripts/$target_base" ]]; then
      pass "$link_name symlink resolves to installed $target_base"
    else
      fail "$link_name symlink resolves" "points at '$resolved'"
    fi
  else
    fail "$link_name symlink created"
  fi
done

# ─── Suite 6: Smoke-run installed copies (not the repo copies) ───────

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
