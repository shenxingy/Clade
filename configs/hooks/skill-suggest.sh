#!/usr/bin/env bash
# skill-suggest.sh — Context-aware skill suggestion after file edits
#
# PostToolUse hook (Edit|Write) — checks what was just edited and suggests
# relevant skills the user might want to run next.
#
# Covers: blog, API routes, security, infra/CI, frontend components,
# DB migrations, ML configs, LaTeX, schema, sitemap, tests, meta.

INPUT=$(cat)
FILE_PATH=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty')

[[ -z "$FILE_PATH" ]] && exit 0

SUGGESTIONS=""

# ─── Blog content ────────────────────────────────────────────────────
if echo "$FILE_PATH" | grep -qiE '(blog|posts|articles)/.*\.(md|mdx|html)$'; then
  SUGGESTIONS="${SUGGESTIONS}Blog content edited. Consider: /blog-seo-check and /blog geo for SEO + AI citation audit\n"
fi

# ─── API route / endpoint ───────────────────────────────────────────
if echo "$FILE_PATH" | grep -qiE '(routes|views|controllers|endpoints|handlers|api)/.*\.(py|ts|js|go|rs|rb)$' \
   || echo "$FILE_PATH" | grep -qiE '(router|handler|controller|endpoint)\.(py|ts|js|go|rs|rb)$'; then
  SUGGESTIONS="${SUGGESTIONS}API route edited. Consider: /verify to test endpoints, /cso if auth-related\n"
fi

# ─── Security-sensitive files ────────────────────────────────────────
if echo "$FILE_PATH" | grep -qiE '(auth|crypto|password|secret|token|credential|jwt|oauth|session|middleware.auth|security)'; then
  SUGGESTIONS="${SUGGESTIONS}Security-sensitive file edited. Run /cso for security audit\n"
fi

# ─── Infrastructure / CI ────────────────────────────────────────────
if echo "$FILE_PATH" | grep -qiE '(Dockerfile|docker-compose|\.github/workflows|\.gitlab-ci|Jenkinsfile|\.circleci|\.tf$|terraform|k8s|kubernetes|helm)'; then
  SUGGESTIONS="${SUGGESTIONS}Infrastructure config edited. Run /verify to validate deployment pipeline\n"
fi

# ─── Frontend components ────────────────────────────────────────────
if echo "$FILE_PATH" | grep -qiE '\.(tsx|jsx|vue|svelte)$' \
   && ! echo "$FILE_PATH" | grep -qiE '(test|spec|story)'; then
  SUGGESTIONS="${SUGGESTIONS}UI component edited. Consider browser testing or /review for visual verification\n"
fi

# ─── Database migrations ────────────────────────────────────────────
if echo "$FILE_PATH" | grep -qiE '(migration|migrate|alembic|drizzle/|prisma/migrations|knex)'; then
  SUGGESTIONS="${SUGGESTIONS}DB migration edited. Run /verify — check migration tests and rollback strategy\n"
fi

# ─── ML / notebook ──────────────────────────────────────────────────
if echo "$FILE_PATH" | grep -qiE '\.(ipynb)$' \
   || echo "$FILE_PATH" | grep -qiE '(training|hyperparameter|experiment|model.config)'; then
  SUGGESTIONS="${SUGGESTIONS}ML artifact edited. Verify model pipeline and check resource usage\n"
fi

# ─── LaTeX / academic ───────────────────────────────────────────────
if echo "$FILE_PATH" | grep -qiE '\.(tex|bib|cls|sty)$'; then
  SUGGESTIONS="${SUGGESTIONS}LaTeX edited. Run latexmk to rebuild, chktex for lint\n"
fi

# ─── Schema / structured data ───────────────────────────────────────
if echo "$FILE_PATH" | grep -qiE '(schema|structured-data|json-ld)' \
   || grep -q 'application/ld+json' "$FILE_PATH" 2>/dev/null; then
  SUGGESTIONS="${SUGGESTIONS}Schema markup edited. Run /seo schema <url> to validate\n"
fi

# ─── Sitemap ─────────────────────────────────────────────────────────
if echo "$FILE_PATH" | grep -qiE 'sitemap.*\.xml'; then
  SUGGESTIONS="${SUGGESTIONS}Sitemap edited. Run /seo sitemap <url> to validate\n"
fi

# ─── CLAUDE.md / VERIFY.md ──────────────────────────────────────────
if echo "$FILE_PATH" | grep -qE '(CLAUDE|VERIFY)\.md$'; then
  SUGGESTIONS="${SUGGESTIONS}Project config updated. Run /review to re-test VERIFY.md checkpoints\n"
fi

# ─── Hook/skill editing (meta) ──────────────────────────────────────
if echo "$FILE_PATH" | grep -qE 'configs/(hooks|skills)/'; then
  SUGGESTIONS="${SUGGESTIONS}Clade config edited. Run ./install.sh to deploy changes\n"
fi

# ─── Test files ──────────────────────────────────────────────────────
if echo "$FILE_PATH" | grep -qiE '(test|spec|_test)\.(py|ts|js|go|rs|rb)$'; then
  SUGGESTIONS="${SUGGESTIONS}Test file edited. Run the test suite to verify\n"
fi

[[ -z "$SUGGESTIONS" ]] && exit 0

# ─── Throttle by suggestion category (not file extension) ───────────
THROTTLE_DIR="/tmp/claude-skill-suggest"
mkdir -p "$THROTTLE_DIR"
# Use first matched suggestion type as throttle key
CATEGORY=$(echo -n "$SUGGESTIONS" | head -1 | cut -d' ' -f1-2 | tr ' /' '_' | tr '[:upper:]' '[:lower:]')
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
