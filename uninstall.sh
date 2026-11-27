#!/usr/bin/env bash
# uninstall.sh — Remove Claude Code customizations deployed by install.sh
#
# Mirrors install.sh: removal lists are DERIVED from configs/ at runtime
# (never hardcoded), so the two scripts cannot drift apart.
#
# Removes only files managed by this repo. Does NOT delete:
#   - corrections/ (user data)
#   - ~/.claude/CLAUDE.md (may contain user content + auto-promoted rules)
#   - ~/.claude/orchestrator-settings.json (user overrides; only the .example is removed)
#   - Skills/agents/hooks not shipped by this repo
#   - Non-hook settings in settings.json (env, permissions), and an
#     autoCompactWindow the user set (only a Clade-owned one is retracted, §3b)
#   - Codex/Kimi hook entries that are not Clade's: §9b/§9c take out only the
#     ones that run Clade's adapter and leave the rest of those files alone
#   - Codex/Kimi agents, AGENTS.md blocks and Kimi's other settings, which this
#     script does not remove yet

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CLAUDE_DIR="$HOME/.claude"

# Python resolution, as in install.sh: on Windows `python3` can be the Store
# stub, which is on PATH and fails, so probe with a real run.
PYTHON=""
if python3 -c pass &>/dev/null; then
  PYTHON="python3"
elif python -c pass &>/dev/null; then
  PYTHON="python"
fi

echo "Uninstalling Claude Code customizations (derived from $SCRIPT_DIR/configs)..."
echo ""

# ─── 1. Remove hooks (mirror of install.sh §2) ───────────────────────

echo "Removing hooks..."
removed=0
for src in "$SCRIPT_DIR/configs/hooks/"*.sh; do
  [[ -f "$src" ]] || continue
  hook=$(basename "$src")
  if [[ -f "$CLAUDE_DIR/hooks/$hook" ]]; then
    rm "$CLAUDE_DIR/hooks/$hook"
    removed=$((removed + 1))
  fi
done
echo "  Removed: $removed hooks"

# Hook libraries
if [[ -d "$SCRIPT_DIR/configs/hooks/lib" && -d "$CLAUDE_DIR/hooks/lib" ]]; then
  for src in "$SCRIPT_DIR/configs/hooks/lib/"*.sh; do
    [[ -f "$src" ]] || continue
    rm -f "$CLAUDE_DIR/hooks/lib/$(basename "$src")"
  done
  rmdir "$CLAUDE_DIR/hooks/lib" 2>/dev/null || true
  echo "  Removed: hooks/lib/"
fi

# ─── 2. Remove agents (mirror of install.sh §3) ──────────────────────

echo "Removing agents..."
removed=0
for src in "$SCRIPT_DIR/configs/agents/"*.md; do
  [[ -f "$src" ]] || continue
  agent=$(basename "$src")
  if [[ -f "$CLAUDE_DIR/agents/$agent" ]]; then
    rm "$CLAUDE_DIR/agents/$agent"
    removed=$((removed + 1))
  fi
done
rm -f "$CLAUDE_DIR/agents/available-skills.md"
echo "  Removed: $removed agents (+ available-skills.md)"

# ─── 3. Remove skills (mirror of install.sh §4) ──────────────────────

echo "Removing skills..."
removed=0
for src in "$SCRIPT_DIR/configs/skills/"*/; do
  [[ -d "$src" ]] || continue
  skill=$(basename "$src")
  if [[ -d "$CLAUDE_DIR/skills/$skill" ]]; then
    rm -rf "$CLAUDE_DIR/skills/$skill"
    removed=$((removed + 1))
  fi
done
rm -f "$CLAUDE_DIR/available_skills.md" "$CLAUDE_DIR/agents/available-skills.md"
echo "  Removed: $removed skills (+ available_skills.md)"

# ─── 3b. Retract the context policy (mirror of install.sh §8d) ───────
# Before step 4 removes the scripts. `context-policy.py uninstall` removes
# autoCompactWindow only if Clade wrote it and settings.json still holds exactly
# that (a value the user set stays), then deletes the sidecar — unless the
# Claude Code version was unreadable, which retracts nothing: the sidecar is
# then kept as the only record that the value is Clade's.

echo "Retracting the context policy..."
if [[ ! -f "$CLAUDE_DIR/.clade-context-state.json" ]]; then
  echo "  Nothing to retract (never applied)"
elif command -v python3 &>/dev/null; then
  python3 "$SCRIPT_DIR/configs/scripts/context-policy.py" uninstall --claude-dir "$CLAUDE_DIR" \
    --policy "$SCRIPT_DIR/configs/context-policy.json" \
    || echo "  WARNING: context policy retract failed; settings.json left as it was"
else
  echo "  Skipped (no python3): autoCompactWindow and ~/.claude/.clade-context-state.json left in place"
fi
rm -f "$CLAUDE_DIR/context-policy.json"

# ─── 4. Remove scripts + symlinks (mirror of install.sh §5, §6b) ─────

echo "Removing scripts..."
removed=0
for src in "$SCRIPT_DIR/configs/scripts/"*.sh "$SCRIPT_DIR/configs/scripts/"*.py; do
  [[ -f "$src" ]] || continue
  script=$(basename "$src")
  if [[ -f "$CLAUDE_DIR/scripts/$script" ]]; then
    rm "$CLAUDE_DIR/scripts/$script"
    removed=$((removed + 1))
  fi
done
echo "  Removed: $removed scripts"

# Script subdirectories (e.g. seo/, ads/, blog/)
for src in "$SCRIPT_DIR/configs/scripts/"*/; do
  [[ -d "$src" ]] || continue
  sub=$(basename "$src")
  [[ "$sub" == "__pycache__" ]] && continue
  if [[ -d "$CLAUDE_DIR/scripts/$sub" ]]; then
    rm -rf "$CLAUDE_DIR/scripts/$sub"
    echo "  Removed: scripts/$sub/"
  fi
done
rm -rf "$CLAUDE_DIR/scripts/__pycache__"

# MCP server (installed from orchestrator/ by install.sh §4b)
rm -f "$CLAUDE_DIR/scripts/mcp_server.py"

# Symlinks created by install.sh (committer, slt, devmode)
for link in committer slt devmode; do
  if [[ -L "$HOME/.local/bin/$link" ]]; then
    rm "$HOME/.local/bin/$link"
    echo "  Removed: ~/.local/bin/$link symlink"
  fi
done

# ─── 5. Remove commands (mirror of install.sh §6) ────────────────────

if compgen -G "$SCRIPT_DIR/configs/commands/*.md" > /dev/null 2>&1; then
  echo "Removing commands..."
  for src in "$SCRIPT_DIR/configs/commands/"*.md; do
    rm -f "$CLAUDE_DIR/commands/$(basename "$src")"
  done
fi

# ─── 6. Remove templates (mirror of install.sh §6c) ──────────────────

echo "Removing templates..."
if [[ -d "$SCRIPT_DIR/configs/templates" && -d "$CLAUDE_DIR/templates" ]]; then
  for src in "$SCRIPT_DIR/configs/templates/"*; do
    [[ -e "$src" ]] || continue
    rm -rf "$CLAUDE_DIR/templates/$(basename "$src")"
  done
  rmdir "$CLAUDE_DIR/templates" 2>/dev/null || true
  echo "  Removed: templates/"
fi

# ─── 6b. Remove output styles (mirror of install.sh §6c-2) ───────────
# Named files only, never the directory: it is the one place a user keeps
# hand-authored styles beside the shipped ones, and install.sh deliberately
# activates none of them. Missing entirely until 2026-09-12, so an uninstall
# left every shipped style behind while claiming to remove what was deployed.

echo "Removing output styles..."
if [[ -d "$SCRIPT_DIR/configs/output-styles" && -d "$CLAUDE_DIR/output-styles" ]]; then
  _removed_styles=0
  for src in "$SCRIPT_DIR/configs/output-styles/"*.md; do
    [[ -e "$src" ]] || continue
    if rm -f "$CLAUDE_DIR/output-styles/$(basename "$src")" 2>/dev/null; then
      _removed_styles=$((_removed_styles + 1))
    fi
  done
  rmdir "$CLAUDE_DIR/output-styles" 2>/dev/null || true
  echo "  Removed: $_removed_styles output style(s)"
fi

# ─── 7. Remove models.env + statusline (install.sh §5, §6d) ──────────

rm -f "$CLAUDE_DIR/models.env" && echo "Removed models.env" || true
rm -f "$CLAUDE_DIR/statusline-command.sh" && echo "Removed statusline-command.sh" || true

# ─── 8. Remove reference copies + kit markers (§7b, §11) ─────────────

rm -f "$CLAUDE_DIR/orchestrator-settings.example.json"
rm -f "$CLAUDE_DIR/.kit-source-dir" "$CLAUDE_DIR/.kit-checksum"
echo "Removed orchestrator-settings.example.json + kit markers"

# ─── 9. Remove hooks + statusLine from settings.json (§8) ────────────

echo "Cleaning settings.json..."
if [[ -f "$CLAUDE_DIR/settings.json" ]] && command -v jq &>/dev/null; then
  # The candidate is a private file beside the target, as in install.sh, not
  # a fixed /tmp path another account can hold or two runs can share. Guarded
  # like the Kimi edit below: under `set -e` a settings.json jq cannot parse
  # ended the whole uninstall here, with the Codex, Kimi and alias steps not
  # run. The write-back goes through the file, keeping its mode and a link.
  if ! _settings_candidate=$(mktemp "$CLAUDE_DIR/.settings.json.XXXXXX" 2>/dev/null); then
    echo "  WARNING: settings.json unchanged (cannot create a temporary file in $CLAUDE_DIR)"
  elif ! jq 'del(.hooks) | del(.statusLine)' "$CLAUDE_DIR/settings.json" > "$_settings_candidate" 2>/dev/null; then
    echo "  WARNING: settings.json unchanged (jq cannot parse it); remove its hooks and statusLine by hand"
  elif { cat "$_settings_candidate" > "$CLAUDE_DIR/settings.json"; } 2>/dev/null; then
    echo "  Removed hooks + statusLine from settings.json"
  else
    echo "  WARNING: settings.json unchanged (cannot write it)"
  fi
  [[ -z "${_settings_candidate:-}" ]] || rm -f "$_settings_candidate"
  unset _settings_candidate
else
  echo "  Skipped (no settings.json or jq not available)"
fi

# ─── 9b. Unwire Clade's Codex hooks (mirror of install.sh's Codex hooks) ─
# install.sh appends ten groups to ~/.codex/hooks.json, every one running
# "$HOME/.codex/clade-hooks/decision-to-codex.sh". The merger's --remove takes
# out each handler whose command starts with that quoted path, and any group or
# event list that emptied; user groups keep their order and fields, and a file
# with nothing of Clade's is not rewritten. Codex keys hook trust by position
# (<path>:<event>:<group>:<handler>), so a user handler that sat behind a
# removed one moves onto a key it was never trusted under; the merger names
# each one for review in /hooks. A profile (CODEX_HOME=
# ~/.codex-profiles/<name>) holding its own hooks.json is cleaned the same way;
# one linked to ~/.codex/hooks.json was cleaned through it. The adapter goes
# only once no hooks.json names it, so a file that could not be cleaned keeps
# a command that still runs instead of one that fails on every event.

echo "Unwiring Codex hooks..."
CODEX_DIR="$HOME/.codex"
CODEX_ADAPTER="$CODEX_DIR/clade-hooks/decision-to-codex.sh"
for _codex_hooks in "$CODEX_DIR/hooks.json" "$HOME/.codex-profiles/"*/hooks.json; do
  [[ -f "$_codex_hooks" ]] || continue
  [[ "$_codex_hooks" == "$CODEX_DIR/hooks.json" || ! -L "$_codex_hooks" ]] || continue
  if [[ -z "$PYTHON" ]]; then
    if grep -qF 'clade-hooks/decision-to-codex.sh' "$_codex_hooks"; then
      echo "  WARNING: Codex hooks unchanged in $_codex_hooks (no working Python)"
    fi
  elif _codex_out=$("$PYTHON" "$SCRIPT_DIR/configs/scripts/codex-hooks-merge.py" --remove \
      --target "$_codex_hooks" --adapter "$CODEX_ADAPTER" 2>&1); then
    printf '%s\n' "$_codex_out" | sed 's/^/  /'
  else
    echo "  WARNING: Codex hooks unchanged in $_codex_hooks (merger failed)"
  fi
done
_codex_still=""
for _codex_hooks in "$CODEX_DIR/hooks.json" "$HOME/.codex-profiles/"*/hooks.json; do
  if [[ -f "$_codex_hooks" ]] && grep -qF 'clade-hooks/decision-to-codex.sh' "$_codex_hooks"; then
    _codex_still="$_codex_hooks"
    break
  fi
done
if [[ -n "$_codex_still" ]]; then
  echo "  Kept $CODEX_DIR/clade-hooks/: $_codex_still still runs its adapter"
elif [[ -d "$CODEX_DIR/clade-hooks" ]]; then
  for src in "$SCRIPT_DIR/configs/codex-hooks/"*.sh; do
    [[ -f "$src" ]] || continue
    rm -f "$CODEX_DIR/clade-hooks/$(basename "$src")"
  done
  if rmdir "$CODEX_DIR/clade-hooks" 2>/dev/null; then
    echo "  Removed: ~/.codex/clade-hooks/"
  else
    echo "  Kept $CODEX_DIR/clade-hooks/: it holds files Clade did not install"
  fi
fi
unset _codex_hooks _codex_out _codex_still

# ─── 9c. Unwire Clade's Kimi hooks (mirror of install.sh §11c) ───────
# install.sh appends twelve [[hooks]] tables to ~/.kimi-code/config.toml, each
# as a blank line, the header and four key lines, every command starting with
# "$HOME/.kimi-code/hooks/decision-to-kimi.sh ". Remove each table whose command
# starts so (header through its last key line, plus the one blank line before
# it) and nothing else: a comment or blank line after a table stays with what
# follows. Where tomllib exists (Python 3.11+) the result must parse to the
# original minus exactly those entries, or the file is left alone, as
# install.sh's subagent-timeout edit does. It is written back with `cat >`, so
# the file keeps its mode (it can hold provider keys) and a symlink stays one.
# The adapter goes once the file no longer names it. statusline.sh stays:
# tui.toml may still run it, and with the kimi-usage helper gone it prints
# nothing, which Kimi takes as "use the built-in footer".

KIMI_DIR="$HOME/.kimi-code"
KIMI_CONFIG="$KIMI_DIR/config.toml"
KIMI_ADAPTER="$KIMI_DIR/hooks/decision-to-kimi.sh"
if [[ -f "$KIMI_CONFIG" ]] && grep -qF "\"$KIMI_ADAPTER " "$KIMI_CONFIG"; then
  echo "Unwiring Kimi hooks..."
  # Guarded, not bare: under `set -e` a failed mktemp, awk or write-back
  # would end the whole uninstall here, with the shell aliases below still in
  # place and the candidate, a full copy of config.toml, left beside it.
  _kimi_problem=""
  _kimi_removed=0
  if ! _kimi_candidate=$(mktemp "$KIMI_DIR/.config.toml.XXXXXX" 2>/dev/null); then
    _kimi_candidate=""
    _kimi_problem="cannot create a temporary file in $KIMI_DIR"
  elif ! CLADE_KIMI_COMMAND_PREFIX="\"$KIMI_ADAPTER " awk '
    function is_header(s) { return s ~ /^[[:space:]]*\[/ }
    function is_content(s) { return s !~ /^[[:space:]]*(#.*)?$/ }
    { line[NR] = $0 }
    END {
      want = ENVIRON["CLADE_KIMI_COMMAND_PREFIX"]
      for (i = 1; i <= NR; i = stop) {
        stop = i + 1
        if (line[i] !~ /^[[:space:]]*\[\[[[:space:]]*hooks[[:space:]]*\]\][[:space:]]*(#.*)?$/) continue
        while (stop <= NR && !is_header(line[stop])) stop++
        clade = 0
        last = i
        for (k = i + 1; k < stop; k++) {
          if (line[k] ~ /^[[:space:]]*command[[:space:]]*=/) {
            value = line[k]
            sub(/^[^=]*=[[:space:]]*/, "", value)
            if (index(value, want) == 1) clade = 1
          }
          if (is_content(line[k])) last = k
        }
        if (!clade) continue
        for (k = i; k <= last; k++) drop[k] = 1
        if (i > 1 && line[i - 1] == "") drop[i - 1] = 1
      }
      for (i = 1; i <= NR; i++) if (!(i in drop)) print line[i]
    }' "$KIMI_CONFIG" > "$_kimi_candidate"; then
    _kimi_problem="the line edit failed"
  else
    _kimi_removed=$(( $(grep -cF "\"$KIMI_ADAPTER " "$KIMI_CONFIG") - $(grep -cF "\"$KIMI_ADAPTER " "$_kimi_candidate" || true) ))
  fi
  # The verdict is the exit status, not the output: a check killed before it
  # prints (a signal, OOM) must refuse the edit, not pass it unchecked.
  if [[ -z "$_kimi_problem" && -n "$PYTHON" ]] && "$PYTHON" -c 'import tomllib' >/dev/null 2>&1 \
      && ! _kimi_problem=$("$PYTHON" - "$KIMI_CONFIG" "$_kimi_candidate" "$KIMI_ADAPTER " 2>&1 <<'PY'
from pathlib import Path
import sys
import tomllib


def load(path, label):
    try:
        with Path(path).open("rb") as handle:
            return tomllib.load(handle)
    except Exception as exc:
        print(f"{label} config.toml does not parse: {exc}")
        raise SystemExit(1)


original = load(sys.argv[1], "original")
candidate = load(sys.argv[2], "candidate")
prefix = sys.argv[3]
expected = dict(original)
if isinstance(original.get("hooks"), list):
    kept = [
        entry for entry in original["hooks"]
        if not (isinstance(entry, dict) and str(entry.get("command", "")).startswith(prefix))
    ]
    if kept:
        expected["hooks"] = kept
    else:
        del expected["hooks"]
if candidate != expected:
    print("the edit would change more than Clade's [[hooks]] entries")
    raise SystemExit(1)
PY
      ); then
    _kimi_problem="${_kimi_problem:-the parse check exited without a verdict}"
  fi
  if [[ -n "$_kimi_problem" ]]; then
    echo "  WARNING: Kimi hooks unchanged ($_kimi_problem)"
  elif [[ "$_kimi_removed" -gt 0 ]]; then
    if { cat "$_kimi_candidate" > "$KIMI_CONFIG"; } 2>/dev/null; then
      echo "  Kimi hooks: $_kimi_removed removed from $KIMI_CONFIG"
    else
      echo "  WARNING: Kimi hooks unchanged (cannot write $KIMI_CONFIG)"
    fi
  fi
  [[ -z "$_kimi_candidate" ]] || rm -f "$_kimi_candidate"
  unset _kimi_candidate _kimi_removed _kimi_problem
fi
if [[ -f "$KIMI_ADAPTER" ]]; then
  if [[ -f "$KIMI_CONFIG" ]] && grep -qF 'hooks/decision-to-kimi.sh' "$KIMI_CONFIG"; then
    echo "  Kept $KIMI_ADAPTER: $KIMI_CONFIG still runs it"
  else
    rm -f "$KIMI_ADAPTER"
    echo "  Removed: ~/.kimi-code/hooks/decision-to-kimi.sh"
  fi
fi
unset KIMI_DIR KIMI_CONFIG KIMI_ADAPTER

# ─── 10. Remove shell aliases (§9) ───────────────────────────────────

echo "Removing shell aliases..."
for rc_file in "$HOME/.zshrc" "$HOME/.bashrc"; do
  [[ -f "$rc_file" ]] || continue
  if grep -q "dangerously-skip-permissions" "$rc_file" 2>/dev/null; then
    # Remove the block added by install.sh (comment + 2 alias lines). Not
    # `sed -i`: BSD sed reads the script as its backup suffix and fails, which
    # under `set -e` ended the uninstall on macOS. The write-back goes through
    # the file, so a linked or 0600 rc file stays as it was.
    if ! _rc_candidate=$(mktemp "$rc_file.clade.XXXXXX" 2>/dev/null); then
      echo "  WARNING: aliases left in $rc_file (cannot create a temporary file beside it)"
    elif sed '/# Claude Code: skip permission prompts (added by clade)/,/^alias cc=/d' "$rc_file" > "$_rc_candidate" \
        && { cat "$_rc_candidate" > "$rc_file"; } 2>/dev/null; then
      echo "  Removed aliases from $rc_file"
    else
      echo "  WARNING: aliases left in $rc_file (cannot rewrite it)"
    fi
    [[ -z "${_rc_candidate:-}" ]] || rm -f "$_rc_candidate"
    unset _rc_candidate
  fi
done

# ─── 11. Clean up empty directories ──────────────────────────────────

for dir in hooks agents scripts commands skills templates; do
  rmdir "$CLAUDE_DIR/$dir" 2>/dev/null && echo "  Removed empty dir: $dir" || true
done

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Uninstall complete."
echo ""
echo "Preserved:"
echo "  - ~/.claude/corrections/ (user data)"
echo "  - ~/.claude/CLAUDE.md (may contain user content + auto-promoted rules)"
echo "  - ~/.claude/orchestrator-settings.json (user overrides)"
echo "  - ~/.claude/settings.json (env, permissions — hooks/statusLine removed;"
echo "    autoCompactWindow removed only if Clade wrote it, kept if you set it)"
echo "  - Skills/agents/hooks not shipped by this repo"
echo "  - ~/.codex/hooks.json and ~/.kimi-code/config.toml (only Clade's hook"
echo "    entries removed; ~/.kimi-code/hooks/statusline.sh kept for tui.toml)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
