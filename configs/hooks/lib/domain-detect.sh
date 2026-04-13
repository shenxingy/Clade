#!/usr/bin/env bash
# domain-detect.sh — Shared domain detection from git diff file extensions
# Source this file, then call detect_domain [FILES_STRING]
#
# Usage:
#   source "$LIBDIR/domain-detect.sh"
#   detect_domain                    # auto-detect from git diff HEAD
#   detect_domain "$FILE_LIST"       # pass explicit file list
#   echo "$DOMAIN"                   # result in $DOMAIN

detect_domain() {
  local files="${1:-}"

  if [[ -z "$files" ]]; then
    files=$(git diff --name-only --diff-filter=ACMR HEAD 2>/dev/null \
         || git diff --name-only --cached 2>/dev/null \
         || echo "")
  fi

  DOMAIN="unknown"

  # ─── Infrastructure / DevOps (check first — Dockerfile, CI, terraform) ──
  if echo "$files" | grep -qiE '(Dockerfile|docker-compose|\.github/workflows|\.gitlab-ci|Jenkinsfile|\.circleci|\.tf$|terraform|k8s|kubernetes|helm|ansible)'; then
    DOMAIN="devops"
    return
  fi

  # ─── Security / Auth ──────────────────────────────────────────────────
  if echo "$files" | grep -qiE '(auth|crypto|security|jwt|oauth|session|credential|password)'; then
    DOMAIN="security"
    return
  fi

  # ─── Frontend (React/Vue/Svelte/Angular components) ──────────────────
  if echo "$files" | grep -qE '\.(tsx|jsx|vue|svelte)$'; then
    DOMAIN="frontend"
    return
  fi

  # ─── TypeScript/JavaScript (non-component — could be backend Node.js) ─
  if echo "$files" | grep -qE '\.(ts|js)$'; then
    # Check if it looks like backend (routes, server, api) or frontend
    if echo "$files" | grep -qiE '(routes|server|api|controller|middleware|handler)'; then
      DOMAIN="backend"
    else
      DOMAIN="frontend"
    fi
    return
  fi

  # ─── Python ──────────────────────────────────────────────────────────
  if echo "$files" | grep -qE '\.(py|ipynb)$'; then
    if echo "$files" | grep -qiE '(train|model|dataset|experiment|notebook|transformer|torch|sklearn)'; then
      DOMAIN="ml"
    else
      DOMAIN="backend"
    fi
    return
  fi

  # ─── Database / Schema ──────────────────────────────────────────────
  if echo "$files" | grep -qiE '(schema|migration|drizzle|prisma|alembic|knex)'; then
    DOMAIN="schema"
    return
  fi

  # ─── Mobile — iOS ──────────────────────────────────────────────────
  if echo "$files" | grep -qE '\.swift$|\.xib$|\.storyboard$|Podfile|\.xcodeproj'; then
    DOMAIN="ios"
    return
  fi

  # ─── Mobile — Android ─────────────────────────────────────────────
  if echo "$files" | grep -qE '\.(kt|java)$|\.gradle'; then
    DOMAIN="android"
    return
  fi

  # ─── Go ─────────────────────────────────────────────────────────────
  if echo "$files" | grep -qE '\.go$'; then
    if echo "$files" | grep -qiE '(handler|server|router|api|http|grpc|middleware)'; then
      DOMAIN="backend"
    else
      DOMAIN="systems"
    fi
    return
  fi

  # ─── Rust ───────────────────────────────────────────────────────────
  if echo "$files" | grep -qE '\.rs$'; then
    if echo "$files" | grep -qiE '(handler|server|router|api|http|actix|axum|rocket|warp)'; then
      DOMAIN="backend"
    else
      DOMAIN="systems"
    fi
    return
  fi

  # ─── Ruby ───────────────────────────────────────────────────────────
  if echo "$files" | grep -qE '\.rb$|Gemfile'; then
    DOMAIN="backend"
    return
  fi

  # ─── PHP ────────────────────────────────────────────────────────────
  if echo "$files" | grep -qE '\.php$'; then
    DOMAIN="backend"
    return
  fi

  # ─── Dart / Flutter ────────────────────────────────────────────────
  if echo "$files" | grep -qE '\.dart$'; then
    DOMAIN="mobile"
    return
  fi

  # ─── C / C++ ────────────────────────────────────────────────────────
  if echo "$files" | grep -qE '\.(c|cpp|h|hpp|cc)$'; then
    DOMAIN="systems"
    return
  fi

  # ─── Academic / LaTeX ──────────────────────────────────────────────
  if echo "$files" | grep -qE '\.(tex|bib|cls|sty)$'; then
    DOMAIN="academic"
    return
  fi

  # ─── Shell scripts (CLI tools) ─────────────────────────────────────
  if echo "$files" | grep -qE '\.(sh|bash|zsh)$'; then
    DOMAIN="cli"
    return
  fi
}
