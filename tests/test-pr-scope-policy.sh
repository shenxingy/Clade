#!/usr/bin/env bash
# Regression guard for adaptive atomic delivery across planning, checkpoint,
# PR creation, review, integration, cleanup, and every distribution.

set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PASSED=0
FAILED=0

assert_contains() {
  local file="$1" needle="$2" label="$3"
  if grep -qF -- "$needle" "$ROOT/$file"; then
    PASSED=$((PASSED + 1))
    printf '  ✓ %s\n' "$label"
  else
    FAILED=$((FAILED + 1))
    printf '  ✗ %s — missing %q in %s\n' "$label" "$needle" "$file"
  fi
}

echo "── atomic PR delivery policy ──"

assert_contains \
  "plugins/clade/skills.list" \
  "create-pr" \
  "native plugin ships create-pr"
assert_contains \
  "plugins/clade/skills.list" \
  "delivery" \
  "native plugin ships delivery controller"
assert_contains \
  "mcp-package/skills.list" \
  "create-pr" \
  "MCP distribution ships create-pr"
assert_contains \
  "mcp-package/skills.list" \
  "delivery" \
  "MCP distribution ships delivery controller"
assert_contains \
  "configs/skills/create-pr/SKILL.md" \
  "One PR = one independently reviewable and reversible delivery unit." \
  "create-pr defines the invariant"
assert_contains \
  "configs/skills/create-pr/prompt.md" \
  "Each stacked PR targets its" \
  "create-pr defines stacked bases"
assert_contains \
  "configs/skills/create-pr/prompt.md" \
  "owns its own candidate/remote evidence" \
  "create-pr requires per-branch verification"
assert_contains \
  "configs/skills/orchestrate/prompt.md" \
  "Treat each \`VERTICAL\` task as one pull-request delivery unit." \
  "orchestrate maps tasks to PRs"
assert_contains \
  "configs/skills/commit/SKILL.md" \
  "A commit preserves work; it does not automatically authorize push" \
  "commit separates preservation from publication"
assert_contains \
  "configs/skills/review-pr/prompt.md" \
  "Independent behavior is Needs changes" \
  "review rejects multi-scope PRs"
assert_contains \
  "configs/skills/merge-pr/prompt.md" \
  "Never merge a multi-feature PR" \
  "merge blocks multi-feature PRs"
assert_contains \
  "configs/skills/merge-pr/prompt.md" \
  "--match-head-commit <reviewed-head-sha>" \
  "merge locks reviewed head SHA"
assert_contains \
  "configs/skills/merge-pr/prompt.md" \
  "Block—not warn" \
  "merge blocks pending and failed gates"
assert_contains \
  "configs/skills/delivery/prompt.md" \
  "verify-clean --id" \
  "delivery makes cleanup a verified transition"
assert_contains \
  "configs/skills/ship/prompt.md" \
  "features already reviewed in" \
  "release cannot bypass feature review"
assert_contains \
  "plugins/clade/skills/create-pr/SKILL.md" \
  "One PR = one independently reviewable and reversible delivery unit." \
  "generated Codex skill carries policy"
assert_contains \
  "configs/CLAUDE.md" \
  "Multiple commits do not make a multi-feature branch acceptable." \
  "installed global rules carry PR invariant"
assert_contains \
  "templates/CLAUDE.md" \
  "use stacked PRs and require each branch" \
  "project template carries stacked-PR rule"

echo ""
echo "── Results: $PASSED/$((PASSED + FAILED)) passed ──"
[[ "$FAILED" -eq 0 ]]
