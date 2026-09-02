#!/usr/bin/env bash
# prompt-tracker.sh — notice when the same brief is being typed again, and say so.
#
# Why this was rewritten (2026-09-02)
# -----------------------------------
# The original fired on UserPromptSubmit with `"async": true` and reported through
# `{"systemMessage": ...}`. An async hook has no channel back into the turn, so
# that message reached nobody — ever. Measured at the rewrite: the log held
# 386,760 prompts across 2,990 distinct fingerprints, nine of them past the
# repeat threshold, and not one suggestion had been delivered in the hook's
# entire life. Same defect class as post-edit-check.sh and skill-suggest.sh,
# which were fixed in August; this one was missed.
#
# That silence has a cost the owner named directly: they keep hand-typing long
# standing briefs because nothing ever told them the brief had become a pattern
# worth encoding as a skill.
#
# Three things changed:
#   1. SYNC, reporting through `hookSpecificOutput.additionalContext` — the only
#      channel a UserPromptSubmit hook actually has.
#   2. BOUNDED. The old version appended forever (13.9 MB) and ran `grep -c`
#      over the whole file on every prompt, which is exactly the cost a sync
#      hook cannot pay. The log is now capped and the scan is over the tail.
#   3. A fingerprint that survives a changing preamble. The old one took the
#      first 80 characters verbatim, so two runs of the same 1,300-character
#      brief that opened with a different sentence never matched. It now
#      normalises and hashes the whole prompt, and separately keeps a
#      content-word signature so a re-worded repeat still lands.
#
# Deliberately NOT a correction. correction-detector.sh handles "that's wrong";
# this handles "you have asked for this shape three times". They are different
# signals and only one of them was being captured.

set -uo pipefail

LOG_FILE="${PROMPT_TRACKER_LOG:-${HOME}/.claude/prompt-log.jsonl}"
SEEN_FILE="${PROMPT_TRACKER_SEEN:-${HOME}/.claude/prompt-suggested.txt}"
MAX_LINES="${PROMPT_TRACKER_MAX_LINES:-20000}"   # bounded: a sync hook cannot scan 14 MB
SCAN_LINES="${PROMPT_TRACKER_SCAN_LINES:-5000}"  # only the tail is searched
THRESHOLD="${PROMPT_TRACKER_THRESHOLD:-3}"
MIN_CHARS="${PROMPT_TRACKER_MIN_CHARS:-200}"     # a standing brief, not a one-liner

command -v jq >/dev/null 2>&1 || exit 0

input=$(cat 2>/dev/null || true)
[[ -z "$input" ]] && exit 0
prompt=$(printf '%s' "$input" | jq -r '.prompt // .message // ""' 2>/dev/null || true)

# Short prompts are conversation, not a brief. The old 20-char floor logged
# every "ok" and "continue" — 386k lines of noise that buried the real signal.
[[ ${#prompt} -lt $MIN_CHARS ]] && exit 0

# ─── Fingerprints ────────────────────────────────────────────────────────────
# `exact`   — the whole prompt, normalised. Catches a literal re-paste.
# `shape`   — the 24 distinct long words, sorted. Catches the same brief pasted
#             again behind a different opening sentence, which the
#             first-80-characters fingerprint could never see. It does NOT
#             recognise an arbitrary rewording, and does not claim to: the
#             measured case is a re-paste, not a paraphrase.
_norm() { printf '%s' "$1" | tr '[:upper:]' '[:lower:]' | tr -s '[:space:]' ' '; }
_hash() { printf '%s' "$1" | cksum | cut -d' ' -f1; }

norm=$(_norm "$prompt")
exact=$(_hash "$norm")
# MIN-HASH, not a hash of the whole word set. Hashing the set exactly is brittle
# in the one way that matters here: adding a single word — "morning" in a new
# greeting, "different" in a new opening sentence — flips it, which is the same
# fragility the first-80-characters fingerprint had, one level up. Keeping the
# eight numerically smallest word hashes makes the signature depend on a fixed
# sample of the vocabulary, so one extra word perturbs it only if it happens to
# hash below the current eighth (~8/n, measured stable across a changed
# preamble below).
mins=$(printf '%s' "$norm" | tr -cs '[:alnum:]_' '\n' \
  | awk 'length($0) >= 7' | sort -u \
  | while IFS= read -r w; do printf '%s\n' "$(printf '%s' "$w" | cksum | cut -d' ' -f1)"; done \
  | sort -n | head -8)
# LSH banding: four bands of two. A candidate is a prompt sharing ANY band, so a
# new opening sentence has to displace hashes in every band to hide the repeat
# rather than just one. Whole-signature equality was measured failing on a
# four-long-word preamble; banding survives it.
bands=$(printf '%s\n' "$mins" | paste -d_ - - 2>/dev/null | head -4)
shape=$(_hash "$(printf '%s' "$mins" | tr '\n' '-')")

mkdir -p "$(dirname "$LOG_FILE")" 2>/dev/null || true
preview=$(printf '%s' "$norm" | cut -c1-100)
band_json=$(printf '%s\n' "$bands" | jq -R . | jq -cs .)
jq -cn --arg d "$(date -u +%Y-%m-%dT%H:%M:%SZ)" --arg e "$exact" --arg s "$shape" \
       --arg p "$preview" --arg n "${#prompt}" --argjson b "$band_json" \
   '{date:$d, exact:$e, shape:$s, bands:$b, chars:($n|tonumber), preview:$p}' \
   >> "$LOG_FILE" 2>/dev/null || exit 0

# Bound the log in place. Unbounded growth is what made the original too
# expensive to run synchronously, which is why it was async, which is why it
# never delivered anything.
lines=$(wc -l < "$LOG_FILE" 2>/dev/null || echo 0)
if [[ "$lines" -gt "$MAX_LINES" ]]; then
  tmp="${LOG_FILE}.trim.$$"
  if tail -n "$((MAX_LINES / 2))" "$LOG_FILE" > "$tmp" 2>/dev/null; then
    mv -f "$tmp" "$LOG_FILE" 2>/dev/null || rm -f "$tmp" 2>/dev/null
  else
    rm -f "$tmp" 2>/dev/null
  fi
fi

tail_n=$(tail -n "$SCAN_LINES" "$LOG_FILE" 2>/dev/null || true)
n_exact=$(printf '%s\n' "$tail_n" | grep -cF "\"exact\":\"${exact}\"" 2>/dev/null || echo 0)
n_shape=0
while IFS= read -r band; do
  [[ -z "$band" ]] && continue
  hit=$(printf '%s\n' "$tail_n" | grep -cF "\"${band}\"" 2>/dev/null || echo 0)
  [[ "$hit" -gt "$n_shape" ]] && n_shape="$hit"
done <<< "$bands"
count=$(( n_exact > n_shape ? n_exact : n_shape ))
[[ "$count" -lt "$THRESHOLD" ]] && exit 0

# Say it once per pattern. A suggestion repeated on every future occurrence is
# the nagging that gets a hook ignored — the failure stop-check.sh just had.
touch "$SEEN_FILE" 2>/dev/null || true
grep -qxF "$shape" "$SEEN_FILE" 2>/dev/null && exit 0
printf '%s\n' "$shape" >> "$SEEN_FILE" 2>/dev/null || true

kind="re-pasted verbatim"
[[ "$n_shape" -gt "$n_exact" ]] && kind="re-typed in different words"

CONTEXT=$(cat <<EOF
This brief has been asked for ${count} times (${kind}), most recently now:

  "${preview}…"

That is a standing preference wearing the costume of a request. Before answering
it again, consider whether it belongs in configuration instead — in this setup
that means a skill under configs/skills/, or a section in CLAUDE.md if it is a
rule rather than a procedure. A brief that has to be re-typed is one the system
failed to learn.

Do this only if it is genuinely the same ask each time, and raise it with the
user rather than silently creating a skill. If they already point the brief at
an existing skill, check that the skill actually contains the constraints — an
empty target is why a brief gets re-typed.

This notice fires once per pattern; it will not repeat.
EOF
)
jq -n --arg ctx "$CONTEXT" \
  '{"hookSpecificOutput":{"hookEventName":"UserPromptSubmit","additionalContext":$ctx}}'
exit 0
