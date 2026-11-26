#!/usr/bin/env bash
# source-shape.sh — sourced by the suites whose scripts run under `set -e` and
# load an optional library: test-memory-sync-breaker.sh, test-sync-health.sh,
# test-sync-store.sh.
#
# bash 3.2 (macOS /bin/bash) exits under `set -e` when `source` fails, even
# inside `||` or an `if` test: a missing or unreadable file, or a sourced file
# whose own command fails. bash 5 does not. So `source lib 2>/dev/null || true`
# fails open on CI's bash 5 and aborts the script on a Mac, and no behavioural
# case run under bash 5 can tell the two apart. This pins the shape instead.
# The form that survives both turns errexit off around the source:
#   set +e
#   source "$lib" 2>/dev/null
#   set -e
#
# guarded_source_lines FILE — print, as LINE:TEXT, each line of FILE that
# recovers from a failed `source`/`.` with `||` or by testing it in
# if/elif/while/until. Comment lines are skipped. Prints nothing when clean.
guarded_source_lines() {
  # A command word, then source or ., then a first argument (so jq's
  # `if . == ""` inside a quoted filter is not one).
  local at='(^|[;&|({]|then|do|else)[[:space:]]*' src='(source|\.)[[:space:]]+[^[:space:]=|)]'
  grep -nE "${at}${src}[^;#]*\|\||${at}(if|elif|while|until)[[:space:]]+(![[:space:]]*)?${src}" "$1" \
    | grep -vE '^[0-9]+:[[:space:]]*#' || true
}
