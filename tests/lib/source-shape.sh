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
# guarded_source_lines FILE — print, as LINE:TEXT, each logical line of FILE
# where a `source`/`.` (also after `builtin`, `command` or an assignment) is
# followed by `||` or `&&`, sits in a `{ … }` group followed by one, follows
# `!`, or is tested in if/elif/while/until. A line ending in `\`, `||`, `&&`
# or `|` is joined to the next first, and LINE is where the joined line
# starts. Comment lines are skipped. Prints nothing when clean.
# It reads syntax, not calls: `f() { source lib; }; f || true` also exits
# under bash 3.2 and is NOT flagged, nor is an if condition split over lines.
# `( source lib ) || true` survives bash 3.2 and IS flagged (it loads nothing),
# as is a jq `then . …` or `else . …` on a line a shell `||` follows: both are
# false positives, which fail a suite loudly rather than pass a bug silently.
guarded_source_lines() {
  # A command word, then source or ., then a first argument (so jq's
  # `if . == ""` inside a quoted filter is not one).
  local at='(^[0-9]+:|[;&|({!]|then|do|else)[[:space:]]*'
  local pre='((builtin|command)[[:space:]]+|[A-Za-z_][A-Za-z0-9_]*=[^[:space:]()`]*[[:space:]]+)*'
  local src="${pre}(source|\\.)[[:space:]]+[^[:space:]=|)]"
  local test='(if|elif|while|until)[[:space:]]+([^#;]*(&&|\|\||!|\{))?[[:space:]]*'
  awk '
    /^[[:space:]]*#/ && buf == "" { print NR ":" $0; next }
    {
      if (buf == "") start = NR
      if ($0 ~ /\\$/) { buf = buf substr($0, 1, length($0) - 1) " "; next }
      if ($0 ~ /(\|\||&&|\|)[[:space:]]*$/) { buf = buf $0 " "; next }
      print start ":" buf $0; buf = ""
    }
    END { if (buf != "") print start ":" buf }' "$1" \
    | grep -E "${at}${src}[^;#]*(\|\||&&)|${at}${test}${src}|${at}![[:space:]]+${src}|\{[[:space:]]*${src}.*\}[^;#]*(\|\||&&)" \
    | grep -vE '^[0-9]+:[[:space:]]*#' || true
}

# Forms that exit under bash 3.2's set -e when $lib is missing, measured in
# macOS's /bin/bash and the bash:3.2 image (both 3.2.57): guarded_source_lines
# must flag every one.
SOURCE_SHAPE_FATAL=(
  'source "$lib" 2>/dev/null || true'
  'source "$lib" 2>/dev/null \
  || true'
  'source "$lib" 2>/dev/null ||
  true'
  '{ source "$lib"; } 2>/dev/null || true'
  'builtin source "$lib" 2>/dev/null || true'
  'x=1 source "$lib" 2>/dev/null || true'
  'source "$lib" 2>/dev/null && :'
  '! source "$lib" 2>/dev/null'
  'if source "$lib" 2>/dev/null; then :; fi'
  'if ! . "$lib" 2>/dev/null; then :; fi'
  'if true && source "$lib" 2>/dev/null; then :; fi'
  'f() { . "$lib" 2>/dev/null || return 0; }; f'
  'if true &&
  source "$lib" 2>/dev/null; then :; fi'
  '# a comment that ends in a pipe |
source "$lib" 2>/dev/null || true'
)
# Forms it must flag although one bash 3.2 build survives them: the bash:3.2
# image exits on `command .`, macOS's /bin/bash does not.
SOURCE_SHAPE_STRICT=(
  'command . "$lib" 2>/dev/null || true'
)
# Forms that survive it: guarded_source_lines must flag none.
SOURCE_SHAPE_SAFE=(
  'set +e
# shellcheck source=/dev/null
source "$lib" 2>/dev/null
set -e'
  '[ -r "$lib" ] && . "$lib"'
  'if [ -r "$lib" ]; then . "$lib"; fi'
  ": '.x | if . == \"\" then empty end' || true"
  'out=$(echo . 2>/dev/null || true)'
  '# a fallback; source "$lib" 2>/dev/null || true'
)

# source_shape_self_check DIR — print each fixture form guarded_source_lines
# gets wrong ("missed: …" or "flagged: …"). Prints nothing when it is right.
source_shape_self_check() {
  local dir="$1" form
  mkdir -p "$dir"
  for form in "${SOURCE_SHAPE_FATAL[@]}" "${SOURCE_SHAPE_STRICT[@]}"; do
    printf '%s\n' "$form" > "$dir/form.sh"
    [[ -n "$(guarded_source_lines "$dir/form.sh")" ]] || printf 'missed: %s\n' "$form"
  done
  for form in "${SOURCE_SHAPE_SAFE[@]}"; do
    printf '%s\n' "$form" > "$dir/form.sh"
    [[ -z "$(guarded_source_lines "$dir/form.sh")" ]] || printf 'flagged: %s\n' "$form"
  done
}

# source_shape_bash32 — print a bash 3.x to run the fixture under: the first of
# $CLADE_TEST_BASH32 and /bin/bash (macOS) that is one. Prints nothing if none.
source_shape_bash32() {
  local b
  for b in "${CLADE_TEST_BASH32:-}" /bin/bash; do
    [[ -n "$b" && -x "$b" ]] || continue
    [[ "$("$b" -c 'echo "${BASH_VERSINFO[0]}"' 2>/dev/null)" == 3 ]] && { printf '%s\n' "$b"; return 0; }
  done
  return 0
}

# source_shape_fixture_check BASH — run the fatal and safe fixture forms under
# BASH with set -e and $lib missing; print each whose outcome contradicts its list.
source_shape_fixture_check() {
  local bash32="$1" form out
  for form in "${SOURCE_SHAPE_FATAL[@]}"; do
    out=$("$bash32" -c "set -e; lib=/nonexistent/clade-lib.sh
$form
echo SURVIVED" 2>/dev/null)
    [[ "$out" != *SURVIVED* ]] || printf 'survived (listed fatal): %s\n' "$form"
  done
  for form in "${SOURCE_SHAPE_SAFE[@]}"; do
    out=$("$bash32" -c "set -e; lib=/nonexistent/clade-lib.sh
$form
echo SURVIVED" 2>/dev/null)
    [[ "$out" == *SURVIVED* ]] || printf 'exited (listed safe): %s\n' "$form"
  done
}
