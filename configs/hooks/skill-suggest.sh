#!/usr/bin/env bash
# skill-suggest.sh — Context-aware skill suggestion after file edits
#
# PostToolUse hook (Edit|Write) — checks what was just edited and suggests
# relevant skills the user might want to run next.
#
# This is SUGGESTION only — never auto-invokes skills.
# Integrates with the self-improvement pipeline by tracking which suggestions
# the user follows (via prompt-tracker.sh) → recurring patterns become rules.

INPUT=$(cat)
TOOL_NAME=$(echo "$INPUT" | jq -r '.tool_name // empty')
FILE_PATH=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty')

[[ -z "$FILE_PATH" ]] && exit 0

# ─── Blog content detection ──────────────────────────────────────────
# After editing blog content → suggest SEO check + GEO audit
BLOG_SUGGEST=""
if echo "$FILE_PATH" | grep -qiE '(blog|posts|articles|content)/.*\.(md|mdx|html)$'; then
  BLOG_SUGGEST="Blog content edited. Consider running:
  - /blog-seo-check $FILE_PATH — validate on-page SEO (title, meta, headings, links)
  - /blog geo $FILE_PATH — AI citation readiness audit (ChatGPT, Perplexity, AI Overviews)"
fi

# ─── Schema/structured data detection ────────────────────────────────
SCHEMA_SUGGEST=""
if echo "$FILE_PATH" | grep -qiE '(schema|structured-data|json-ld|markup)' \
   || grep -q 'application/ld+json' "$FILE_PATH" 2>/dev/null; then
  SCHEMA_SUGGEST="Schema markup edited. Consider: /seo schema <url> — validate structured data"
fi

# ─── Sitemap detection ───────────────────────────────────────────────
SITEMAP_SUGGEST=""
if echo "$FILE_PATH" | grep -qiE 'sitemap.*\.xml'; then
  SITEMAP_SUGGEST="Sitemap edited. Consider: /seo sitemap <url> — validate XML sitemap"
fi

# ─── CLAUDE.md / VERIFY.md detection ─────────────────────────────────
REVIEW_SUGGEST=""
if echo "$FILE_PATH" | grep -qE '(CLAUDE|VERIFY)\.md$'; then
  REVIEW_SUGGEST="Project config updated. Consider: /review — re-test VERIFY.md checkpoints"
fi

# ─── Hook/skill editing (meta) ───────────────────────────────────────
META_SUGGEST=""
if echo "$FILE_PATH" | grep -qE 'configs/(hooks|skills)/'; then
  META_SUGGEST="Clade config edited. Run: ./install.sh to deploy changes"
fi

# ─── Test file detection ─────────────────────────────────────────────
TEST_SUGGEST=""
if echo "$FILE_PATH" | grep -qiE '(test|spec|_test)\.(py|ts|js|go|rs)$'; then
  TEST_SUGGEST="Test file edited. Consider running the test suite to verify"
fi

# ─── Build suggestion output ─────────────────────────────────────────
SUGGESTIONS=""
for s in "$BLOG_SUGGEST" "$SCHEMA_SUGGEST" "$SITEMAP_SUGGEST" "$REVIEW_SUGGEST" "$META_SUGGEST" "$TEST_SUGGEST"; do
  [[ -n "$s" ]] && SUGGESTIONS="${SUGGESTIONS}${s}\n"
done

[[ -z "$SUGGESTIONS" ]] && exit 0

# Throttle: don't suggest for the same file type more than once per 5 minutes
THROTTLE_DIR="/tmp/claude-skill-suggest"
mkdir -p "$THROTTLE_DIR"
CATEGORY=$(echo "$FILE_PATH" | sed 's/.*\.//' | tr '[:upper:]' '[:lower:]')
THROTTLE_FILE="$THROTTLE_DIR/$CATEGORY"

if [[ -f "$THROTTLE_FILE" ]]; then
  LAST=$(cat "$THROTTLE_FILE" 2>/dev/null || echo 0)
  NOW=$(date +%s)
  if [[ $((NOW - LAST)) -lt 300 ]]; then
    exit 0
  fi
fi
date +%s > "$THROTTLE_FILE"

jq -n --arg ctx "$SUGGESTIONS" \
  '{"hookSpecificOutput":{"additionalContext":$ctx}}'

exit 0
