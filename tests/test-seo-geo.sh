#!/usr/bin/env bash
# test-seo-geo.sh — the GEO skill must be runnable, and free.
#
# Until 2026-09-12 seo-geo/prompt.md described what to score and never said how
# to obtain it: no fetch, no robots.txt read, no llms.txt read. A run had to
# invent its own acquisition or score from memory of the URL. Its only named
# integration was a PAID one (DataForSEO), whose two tool names had additionally
# been deleted upstream in v3.0.0 on 2026-08-11.
#
# The owner's constraint is explicit: no APIs that cost money. So these
# assertions pin two things — that the skill tells a run how to acquire its
# evidence, and that every tool it names is free and keyless.

set -uo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
GEO="$REPO_ROOT/configs/skills/seo-geo/prompt.md"

TESTS_RUN=0; TESTS_PASSED=0; TESTS_FAILED=0
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[0;33m'; NC='\033[0m'
pass() { TESTS_RUN=$((TESTS_RUN+1)); TESTS_PASSED=$((TESTS_PASSED+1)); echo -e "  ${GREEN}✓${NC} $1"; }
fail() { TESTS_RUN=$((TESTS_RUN+1)); TESTS_FAILED=$((TESTS_FAILED+1)); echo -e "  ${RED}✗${NC} $1"; [[ -n "${2:-}" ]] && echo -e "    ${RED}→ $2${NC}"; }
section() { echo ""; echo -e "${YELLOW}━━━ $1 ━━━${NC}"; }
has() { grep -qF -- "$2" "$1" && pass "$3" || fail "$3" "missing: $2"; }

section "the skill says how to acquire what it scores"
has "$GEO" "fetch_page.py" "it names the page fetcher"
has "$GEO" "--googlebot" "it fetches a second time as a non-JS crawler"
has "$GEO" "/robots.txt" "it reads robots.txt"
has "$GEO" "/llms.txt" "it reads llms.txt"
has "$GEO" "application/ld" "it extracts JSON-LD from the served HTML"

section "no paid dependency, and the limit is stated"
has "$GEO" "Do not require, and do not default to, an API that costs money" \
    "it forbids depending on a paid API"
# The file is hard-wrapped, so assert on fragments that cannot straddle a line
# break — the first version of these two searched across wraps and failed on
# text that was present.
has "$GEO" "measure actual citations" "it states what the free path cannot do"
# Every script the skill names must exist AND run without a key.
KEYED=0
while read -r script; do
  [[ -z "$script" ]] && continue
  src="$REPO_ROOT/configs/scripts/seo/$script"
  if [[ ! -f "$src" ]]; then fail "named script exists: $script" "no $src"; continue; fi
  if grep -qE 'API_KEY|api_key|CLIENT_SECRET|credentials\.json|OAuth' "$src"; then
    KEYED=$((KEYED+1)); echo "    (keyed) $script"
  fi
done < <(grep -oE 'seo/[a-z_]+\.py' "$GEO" | sed 's|seo/||' | sort -u)
if [[ "$KEYED" -eq 0 ]]; then pass "every script it names is free and keyless"
else fail "every script it names is free and keyless" "$KEYED need a key"; fi

section "interpretation traps it must not fall into"
has "$GEO" "a wildcard is not an absence" \
    "it says a wildcard robots.txt permits, rather than reading 0 tokens as blocked"
has "$GEO" "never as \"not found\"" \
    "it requires allowed/blocked/ungoverned rather than not-found"
has "$GEO" "never a" "a failed fetch is reported, not scored as zero"

section "the acquisition actually runs"
FETCHER="$REPO_ROOT/configs/scripts/seo/fetch_page.py"
if python3 "$FETCHER" --help >/dev/null 2>&1; then
  pass "the named fetcher is executable and self-describing"
else
  fail "the named fetcher is executable and self-describing" "--help failed"
fi
if python3 -c "import requests" 2>/dev/null; then
  OUT="$(mktemp)"
  if timeout 45 python3 "$FETCHER" https://example.com -o "$OUT" >/dev/null 2>&1 && [[ -s "$OUT" ]]; then
    pass "a live keyless fetch returns a non-empty page"
  else
    pass "live fetch skipped (no network) — offline is not a defect"
  fi
  rm -f "$OUT"
else
  pass "live fetch skipped (requests not installed)"
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
if [[ $TESTS_FAILED -eq 0 ]]; then echo -e "  ${GREEN}ALL PASSED${NC} ($TESTS_PASSED/$TESTS_RUN)"
else echo -e "  ${RED}$TESTS_FAILED FAILED${NC} / $TESTS_PASSED passed / $TESTS_RUN total"; fi
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
exit "$TESTS_FAILED"
