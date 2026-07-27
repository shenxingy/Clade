#!/usr/bin/env bash
# Regression guard for atomic PR delivery across planning, commit, PR creation,
# review, release, and merge workflows.

set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PASSED=0
FAILED=0

assert_contains() {
  local file="$1" needle="$2" label="$3"
  if grep -qF "$needle" "$ROOT/$file"; then
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
  "configs/skills/create-pr/SKILL.md" \
  "One PR = one independently reviewable and reversible delivery unit." \
  "create-pr defines the invariant"
assert_contains \
  "configs/skills/create-pr/SKILL.md" \
  "Each PR targets its immediate predecessor." \
  "create-pr defines stacked bases"
assert_contains \
  "configs/skills/create-pr/SKILL.md" \
  "Each branch must have its own evidence" \
  "create-pr requires per-branch verification"
assert_contains \
  "configs/skills/orchestrate/prompt.md" \
  "Treat each \`VERTICAL\` task as one pull-request delivery unit." \
  "orchestrate maps tasks to PRs"
assert_contains \
  "configs/skills/commit/prompt.md" \
  "splitting commits is not enough" \
  "commit distinguishes commits from PR boundaries"
assert_contains \
  "configs/skills/review-pr/prompt.md" \
  "verdict is **❌ Needs changes**" \
  "review rejects multi-scope PRs"
assert_contains \
  "configs/skills/merge-pr/prompt.md" \
  "Never merge a multi-feature PR" \
  "merge blocks multi-feature PRs"
assert_contains \
  "configs/skills/ship/prompt.md" \
  "features already reviewed in" \
  "release cannot bypass feature review"
assert_contains \
  "plugins/clade/skills/create-pr/SKILL.md" \
  "One PR = one independently reviewable and reversible delivery unit." \
  "generated Codex skill carries policy"

echo ""
echo "── Results: $PASSED/$((PASSED + FAILED)) passed ──"
[[ "$FAILED" -eq 0 ]]
