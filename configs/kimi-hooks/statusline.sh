#!/usr/bin/env bash
# statusline.sh — Kimi Code footer line 1, Clade's quota pace indicator.
#
# Wired by install.sh as `[status_line] command` in ~/.kimi-code/tui.toml
# (Kimi's own docs suggest exactly this file name). Kimi runs the command
# under `sh -c` with a 300 ms deadline, feeds a JSON snapshot (model, cwd,
# gitBranch, permissionMode, planMode, contextTokens, sessionId, ...) on
# stdin, and takes only the FIRST stdout line; a non-zero exit or an empty
# line falls back to the built-in footer. The render lives in the kimi-usage
# skill's helper, which reads a cache and never touches the network on this
# path — a refresh it decides is due runs detached, in its own session, so
# the 300 ms reaper (a process-group kill) cannot take the fetch down with it.
#
# Measured on Kimi 2.0.1: an IDLE session re-runs the command once a second
# (30 invocations in 30 s), and the helper costs ~40 ms of Python start-up
# each time — 4% of a core per open session, for a line that does not
# change. So the launcher memoises: while the snapshot, the cache, and the
# style/theme files are unchanged, and the memo is under a minute old, it
# replays the last line without starting Python. Keyed per session, because
# every session's snapshot differs (sessionId, cwd) and one shared memo would
# thrash. Sixty seconds bounds the staleness of the reset countdown, whose
# finest unit is a minute.
#
# Exit 0 with no output on any missing prerequisite: that is the documented
# "use the built-in footer" signal, and a footer must never break a session.
#
# Bash 3.2 / BSD userland clean: no arrays, no mapfile, `stat -c || stat -f`.

helper="${CLADE_KIMI_USAGE_HELPER:-$HOME/.claude/skills/kimi-usage/scripts/kimi_usage.py}"
[ -f "$helper" ] || exit 0

if command -v python3 >/dev/null 2>&1; then
  py=python3
elif command -v python >/dev/null 2>&1; then
  py=python
else
  exit 0
fi

payload=$(cat)
home="${KIMI_CODE_HOME:-$HOME/.kimi-code}"

_mtime() { stat -c %Y "$1" 2>/dev/null || stat -f %m "$1" 2>/dev/null || echo 0; }

# Session id straight out of the JSON text — no jq on this path. Kimi's
# JSON.stringify writes `"sessionId":"..."`; the spaced form is tolerated for
# hand-fed snapshots. A snapshot without one shares the "-" memo, which is
# merely a memo that misses more.
sid=${payload#*\"sessionId\":\"}
[ "$sid" = "$payload" ] && sid=${payload#*\"sessionId\": \"}
if [ "$sid" = "$payload" ]; then sid="-"; else sid=${sid%%\"*}; fi
sid=$(printf '%s' "$sid" | tr -cd 'A-Za-z0-9_-' | cut -c1-64)
memo="$home/.clade-usage-memo-${sid:--}"

key="$(printf '%s' "$payload" | cksum | cut -d' ' -f1)"
key="$key-$(_mtime "$home/.clade-usage-cache.json")-$(_mtime "$home/.clade-usage-style")-$(_mtime "$home/.clade-usage-theme")"

if [ -f "$memo" ] && [ $(( $(date +%s) - $(_mtime "$memo") )) -lt 60 ] \
   && [ "$(sed -n '1p' "$memo")" = "$key" ]; then
  sed -n '2p' "$memo"
  exit 0
fi

line=$(printf '%s' "$payload" | "$py" "$helper" statusline) || exit 0
{ printf '%s\n' "$key"; printf '%s\n' "$line"; } > "$memo.tmp" 2>/dev/null && mv "$memo.tmp" "$memo" 2>/dev/null
printf '%s\n' "$line"
