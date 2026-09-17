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
#   checks.sh pr-body "BODY"      AGENTS.md honeypot check (see AGENTS.md) —
#                                 flags PRs whose body echoes the compliance
#                                 token verbatim, a signal of a fully-
#                                 unsupervised AI submission nobody read
#                                 before opening. Called by the PR honeypot
#                                 CI workflow, not by committer.sh (this is a
#                                 PR-description check, not a commit check).
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
# github_pat_ tokens, Anthropic sk-ant keys, Google AIza keys, Slack xox tokens,
# and underscore-prefixed provider keys (sk_/rk_/ak_), which carry an explicit
# leading-boundary group because POSIX ERE has no portable \b and `sk_` sits
# inside the perfectly ordinary word `task_`. That last one is why the
# "mirrors" claim is load-bearing rather than decorative: this ERE is what runs
# when python3 is unavailable, and a pattern that exists only in redact.py is a
# pattern the commit gate does not have.
SECRET_ERE='-----BEGIN [A-Z ]*PRIVATE KEY-----|AKIA[0-9A-Z]{16,}|gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{22,}|sk-ant-[A-Za-z0-9_-]{40,}|(^|[^A-Za-z0-9_-])sk-(proj-)?[A-Za-z0-9_-]{20,}|AIza[0-9A-Za-z_-]{35,}|xox[baprs]-[A-Za-z0-9-]{10,}|(^|[^A-Za-z0-9_])(sk|rk|pk)_(live|test)_[A-Za-z0-9]{20,}|(^|[^A-Za-z0-9_])(sk|rk|ak)_[A-Za-z0-9]{32,}|eyJ[A-Za-z0-9_=-]{10,}[.]eyJ[A-Za-z0-9_=-]{10,}[.][A-Za-z0-9_=-]{10,}|(^|[^A-Za-z0-9_])[A-Z_]*(API_?KEY|SECRET|PASSWORD|PASSWD|TOKEN|AUTH)[A-Z_]*[[:space:]:=]+["'"'"']?[^[:space:]"'"'"']{12,}'

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

# AGENTS.md honeypot (Mitchell Hashimoto/Ghostty pattern): unlike the secret
# scanner above, PRESENCE of this token is the bad signal, not absence — a
# human who actually read/wrote their own PR text is very unlikely to blindly
# echo a "confirm you read this" token into it; a fully-unsupervised AI
# mechanically following AGENTS.md's instructions will. Flag, don't reject —
# this is a maintainer-attention signal, not proof of a bad PR.
HONEYPOT_TOKEN='CLD-AGENTS-7f2b91e4'

check_pr_body_honeypot() {
  local body="${1:-}"
  if printf '%s' "$body" | grep -qF "$HONEYPOT_TOKEN"; then
    echo "checks: PR body contains the AGENTS.md compliance token verbatim." >&2
    echo "  Likely signal: a fully-unsupervised AI agent generated this PR and no" >&2
    echo "  human read its own description before submission. Flagging for a" >&2
    echo "  maintainer to look closer — not an automatic rejection." >&2
    return 1
  fi
  return 0
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

# A repository may add its OWN pre-commit gates without any of them landing in
# this file or in committer.sh. Both ship globally — committer.sh runs in 40+
# repositories on this account — so a Clade-specific drift check wired here
# would fire in every unrelated repo on the machine. Instead: if the repo being
# committed to carries an executable .claude/pre-commit.sh, run it.
#
# Why this is worth a hook at all, measured on Clade's own CI history: of the
# last 200 runs, 27 failed, and 7 of those 27 (26%) failed on a drift gate and
# nothing else — a red run, a push, and a round trip for a check that takes
# about a second locally. Those are the cheapest possible failures and the only
# thing standing between them and green was that nobody ran the command.
run_repo_pre_commit() {
  local root hook
  root=$(git rev-parse --show-toplevel 2>/dev/null) || return 0
  hook="$root/.claude/pre-commit.sh"
  [[ -x "$hook" ]] || return 0
  # The commit message is passed through as $1 so a repo's own gate can look at
  # it. PLUMBING ONLY — committer.sh ships to 40+ repositories on this account
  # and to every public install, so no message CHECK belongs here; that lives in
  # the repo's own .claude/pre-commit.sh, which is the whole point of the
  # dispatch. A hook that ignores $1 is unaffected.
  if ! (cd "$root" && bash "$hook" "${1:-}"); then
    echo "  → blocked by $hook (the repo's own pre-commit gate)" >&2
    return 1
  fi
  return 0
}

cmd_staged() {
  check_staged_secrets || return 1
  run_repo_pre_commit "${1:-}" || return 1
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
    cmd_staged "${2:-}" || exit 1
    ;;
  commit-msg)
    check_commit_msg "${2:-}" || exit 1
    ;;
  shellcheck)
    shift
    check_shellcheck "$@" || exit 1
    ;;
  pr-body)
    check_pr_body_honeypot "${2:-}" || exit 1
    ;;
  *)
    echo "Usage: checks.sh staged | commit-msg \"MSG\" | shellcheck FILE... | pr-body \"BODY\"" >&2
    exit 2
    ;;
esac
