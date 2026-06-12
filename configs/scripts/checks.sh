#!/usr/bin/env bash
# checks.sh — shared pre-commit / CI checks (local and CI run this same script)
#
# Subcommands:
#   checks.sh staged              staged-secret scan (fail-closed) + shellcheck
#                                 on staged *.sh files. committer.sh calls this
#                                 after staging, before committing.
#   checks.sh commit-msg "MSG"    conventional-commit format validation —
#                                 single source of the regex committer.sh uses
#   checks.sh shellcheck FILE...  shellcheck --severity=error; skips with a
#                                 notice when shellcheck is not installed
#                                 (CI installs it; local machines may not)
#
# Escape hatches:
#   CLADE_ALLOW_SECRETS=1     skip the staged-secret scan (known-fake fixtures)
#   CLADE_SKIP_SHELLCHECK=1   skip shellcheck (e.g. a pre-existing error in a
#                             script you didn't touch is blocking your commit)
#
# The secret scan is FAIL-CLOSED: any hit aborts with exit 1. Canonical
# patterns live in redact.py (sibling copy first, then the deployed copy);
# the inline ERE below is the fallback when redact.py / python3 are missing.
# Only ADDED diff lines are scanned — removing a leaked secret must not be
# blocked by the very gate that should have prevented it.

set -uo pipefail

SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Conventional-commit pattern — shared with committer.sh (which delegates here
# when checks.sh is resolvable, and falls back to its own inline copy).
CONVENTIONAL_RE='^(feat|fix|refactor|test|chore|docs|perf|style|ci|build)(\(.+\))?: .+'

# Fallback secret patterns (POSIX ERE) — mirrors redact.py's high-signal set:
# PEM private-key blocks, AWS AKIA ids, GitHub ghp_/gho_/ghu_/ghs_/ghr_ and
# github_pat_ tokens, Anthropic sk-ant keys, Google AIza keys, Slack xox tokens.
SECRET_ERE='-----BEGIN [A-Z ]*PRIVATE KEY-----|AKIA[0-9A-Z]{16}|gh[pousr]_[A-Za-z0-9]{36}|github_pat_[A-Za-z0-9_]{22}|sk-ant-[A-Za-z0-9_-]{40}|AIza[0-9A-Za-z_-]{35}|xox[baprs]-[A-Za-z0-9-]{10}'

_redact_py() {
  if [[ -f "$SELF_DIR/redact.py" ]]; then
    echo "$SELF_DIR/redact.py"
  elif [[ -f "$HOME/.claude/scripts/redact.py" ]]; then
    echo "$HOME/.claude/scripts/redact.py"
  fi
}

_secret_abort_msg() {
  echo "checks: staged diff contains secret-like content — commit aborted." >&2
  echo "  If these are known-fake fixtures: CLADE_ALLOW_SECRETS=1 committer ..." >&2
}

check_staged_secrets() {
  if [[ "${CLADE_ALLOW_SECRETS:-0}" == "1" ]]; then
    echo "checks: CLADE_ALLOW_SECRETS=1 — staged-secret scan skipped" >&2
    return 0
  fi
  local added redact
  # Scan only lines being ADDED ('+' prefix, excluding the '+++' file header)
  added="$(git diff --cached 2>/dev/null | grep -E '^\+' | grep -vE '^\+\+\+' || true)"
  [[ -z "$added" ]] && return 0
  redact="$(_redact_py)"
  if [[ -n "$redact" ]] && command -v python3 &>/dev/null; then
    if ! printf '%s\n' "$added" | python3 "$redact" --check; then
      _secret_abort_msg
      return 1
    fi
  elif printf '%s\n' "$added" | grep -qE -e "$SECRET_ERE"; then  # -e: pattern starts with '-'
    _secret_abort_msg
    return 1
  fi
  return 0
}

check_shellcheck() {
  if [[ "${CLADE_SKIP_SHELLCHECK:-0}" == "1" ]]; then
    echo "checks: CLADE_SKIP_SHELLCHECK=1 — shellcheck skipped" >&2
    return 0
  fi
  if ! command -v shellcheck &>/dev/null; then
    echo "checks: shellcheck not installed — skipped (CI runs it)" >&2
    return 0
  fi
  [[ $# -eq 0 ]] && return 0
  shellcheck --severity=error "$@"
}

check_commit_msg() {
  local msg="${1:-}"
  if ! printf '%s\n' "$msg" | head -1 | grep -qE "$CONVENTIONAL_RE"; then
    echo "checks: commit message must follow conventional commit format." >&2
    echo "  Pattern: <type>(<scope>): <description>" >&2
    echo "  Types:   feat fix refactor test chore docs perf style ci build" >&2
    echo "  Got:     $(printf '%s' "$msg" | head -1)" >&2
    return 1
  fi
}

cmd_staged() {
  check_staged_secrets || return 1
  # Run shellcheck on the staged shell files (working-tree content — committer
  # stages the working tree immediately before this runs, so the two match).
  # No mapfile: macOS ships bash 3.2.
  local f files=()
  while IFS= read -r f; do
    [[ -n "$f" && -f "$f" ]] && files+=("$f")
  done < <(git diff --cached --name-only --diff-filter=ACMR 2>/dev/null | grep -E '\.sh$' || true)
  if [[ ${#files[@]} -gt 0 ]]; then
    check_shellcheck "${files[@]}" || return 1
  fi
  return 0
}

case "${1:-}" in
  staged)
    cmd_staged || exit 1
    ;;
  commit-msg)
    check_commit_msg "${2:-}" || exit 1
    ;;
  shellcheck)
    shift
    check_shellcheck "$@" || exit 1
    ;;
  *)
    echo "Usage: checks.sh staged | commit-msg \"MSG\" | shellcheck FILE..." >&2
    exit 2
    ;;
esac
