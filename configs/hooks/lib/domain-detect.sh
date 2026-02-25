#!/usr/bin/env bash
# domain-detect.sh — Shared domain detection from git diff file extensions
# Source this file, then call detect_domain [FILES_STRING]
#
# Usage:
#   source "$LIBDIR/domain-detect.sh"
#   detect_domain                    # auto-detect from git diff HEAD
#   detect_domain "$FILE_LIST"       # pass explicit file list
#   echo "$DOMAIN"                   # result: frontend|backend|ml|schema|ios|android|systems|academic|unknown

detect_domain() {
  local files="${1:-}"

  if [[ -z "$files" ]]; then
    files=$(git diff --name-only --diff-filter=ACMR HEAD 2>/dev/null \
         || git diff --name-only --cached 2>/dev/null \
         || echo "")
  fi

  DOMAIN="unknown"

  if echo "$files" | grep -qE '\.(tsx?|jsx?)$'; then
    DOMAIN="frontend"
  elif echo "$files" | grep -qE '\.(py|ipynb)$'; then
    if echo "$files" | grep -qE 'train|model|dataset|experiment|notebook'; then
      DOMAIN="ml"
    else
      DOMAIN="backend"
    fi
  elif echo "$files" | grep -qE 'schema|migration|drizzle|prisma'; then
    DOMAIN="schema"
  elif echo "$files" | grep -qE '\.swift$|\.xib$|\.storyboard$|Podfile|\.xcodeproj'; then
    DOMAIN="ios"
  elif echo "$files" | grep -qE '\.(kt|java)$|\.gradle'; then
    DOMAIN="android"
  elif echo "$files" | grep -qE '\.rs$'; then
    DOMAIN="systems"
  elif echo "$files" | grep -qE '\.go$'; then
    DOMAIN="systems"
  elif echo "$files" | grep -qE '\.tex$|\.bib$'; then
    DOMAIN="academic"
  fi
}
