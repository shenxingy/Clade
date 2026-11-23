#!/usr/bin/env bash
# test-statusline-eta.sh — the status line's task-time segment, end to end.
#
# configs/scripts/task-eta.py prints "20m workflow" (and, with --forms, the
# shorter "20m" too); configs/scripts/statusline-command.sh calls it
# inline with the status-line JSON and fits the whole line to COLUMNS, the pane's
# width; install.sh adds statusLine.refreshInterval so the line keeps
# refreshing while the main thread is idle. This runs install.sh against a
# THROWAWAY $HOME under /tmp, writes SYNTHETIC transcripts only (the self-test's
# own builders, never a real transcript), and pins:
#
#   install: a fresh install sets refreshInterval 10 and installs task-eta.py; a
#   reinstall keeps a refreshInterval the user set and adds 10 where it is
#   absent (the Windows/Git Bash rewrite is pinned in tests/test-install.sh);
#   the line: a Workflow in flight after its turn reads "20m workflow", and
#   still does after a later prompt; a Workflow stopped with TaskStop, or one
#   whose launch was refused, is not shown (idle prints nothing); no estimate
#   past 4 h; the fit to a pane 94, 80, 70, 46, 35 and 29 columns wide (at 80
#   the drop-in alone is too much), with no "git:(" label and the task time
#   last to go;
#   a missing model prints elapsed time only and starts ONE detached refit
#   that writes the model; five concurrent calls start one refit, not five;
#   fail soft: no transcript, an empty one, a directory, malformed lines, stdin
#   that is not JSON and a corrupt model each print the other segments, no
#   traceback, exit 0, and a missing config dir still prints elapsed time; `slt eta off|on`; no python3 drops only this segment;
#   a backslash in the segment is not read as an escape.
#
# The last suite removes each guard in turn from a COPY (statusline-command.sh,
# install.sh, the installed task-eta.py) and requires this suite to go red,
# beside a no-op control that must stay green. task-eta.py's own guards are
# mutated by orchestrator/tests/can_fire/task_eta.py against its --self-test.
#
# Usage: bash tests/test-statusline-eta.sh
# Internal (the mutation suite sets these for each mutant run):
#   SE_SRC=DIR          a repository copy to install from (skips making one)
#   SE_INSTALL=PATH     run this install.sh (it must sit at the root of SE_SRC)
#   SE_STATUSLINE=PATH  test this statusline-command.sh instead of the installed one
#   SE_TASK_ETA=PATH    copy this task-eta.py over the installed one
#   SE_MUTANT=1         stop at the first failure; skip the mutation suite

set -uo pipefail

# ─── Harness ──────────────────────────────────────────────────────────

TESTS_RUN=0
TESTS_PASSED=0
TESTS_FAILED=0

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
NC='\033[0m'

SE_MUTANT="${SE_MUTANT:-}"

pass() {
  TESTS_RUN=$((TESTS_RUN + 1)); TESTS_PASSED=$((TESTS_PASSED + 1))
  echo -e "  ${GREEN}✓${NC} $1"
}

fail() {
  TESTS_RUN=$((TESTS_RUN + 1)); TESTS_FAILED=$((TESTS_FAILED + 1))
  echo -e "  ${RED}✗${NC} $1"
  [[ -n "${2:-}" ]] && echo -e "    ${RED}→ $2${NC}"
  [[ -n "$SE_MUTANT" ]] && exit 1
  return 0
}

section() { echo ""; echo -e "${YELLOW}━━━ $1 ━━━${NC}"; }

summary() {
  echo ""
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  if [[ $TESTS_FAILED -eq 0 ]]; then
    echo -e "  ${GREEN}ALL PASSED${NC} ($TESTS_PASSED/$TESTS_RUN)"
    exit 0
  fi
  echo -e "  ${RED}FAILED${NC} ($TESTS_FAILED of $TESTS_RUN)"
  exit 1
}

for tool in python3 jq; do
  if ! command -v "$tool" >/dev/null 2>&1; then
    echo "SKIP: $tool not available — the segment and install.sh's merge both need it"
    exit 0
  fi
done

# ─── Sandbox ──────────────────────────────────────────────────────────

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REAL_HOME="$HOME"
SANDBOX="$(mktemp -d /tmp/clade-eta-test-XXXXXX)"
case "$SANDBOX" in
  /tmp/clade-eta-test-*) : ;;
  *) echo "FATAL: sandbox '$SANDBOX' is not under /tmp — aborting before any write"; exit 1 ;;
esac
export HOME="$SANDBOX/home"
mkdir -p "$HOME"
if [[ "$HOME" == "$REAL_HOME" ]]; then
  echo "FATAL: fake HOME equals real HOME — aborting"; exit 1
fi
# A profile's CLAUDE_CONFIG_DIR would send the model and its refit to the real
# config dir; the clock and fit-delay hooks are set per case below.
unset CLAUDE_CONFIG_DIR CLADE_TASK_ETA_NOW CLADE_TASK_ETA_FIT_DELAY

cleanup() {
  # a refit this suite started must not outlive it (each holds the sandbox path in its argv)
  pkill -f "$SANDBOX/home/.claude/scripts/task-eta.py" 2>/dev/null
  rm -rf "$SANDBOX"
}
trap cleanup EXIT

if [[ -n "${SE_SRC:-}" ]]; then
  SRC="$SE_SRC"
else
  SRC="$SANDBOX/repo"
  mkdir -p "$SRC"
  tar -C "$REPO_ROOT" --exclude='.git' --exclude='orchestrator/.venv' --exclude='node_modules' \
    --exclude='__pycache__' -cf - . | tar -xf - -C "$SRC"
fi
INSTALL_SH="${SE_INSTALL:-$SRC/install.sh}"

# Hermetic Claude Code, as in tests/test-install.sh: install.sh §8d may run `claude --version`.
NO_CLAUDE_BIN="$SANDBOX/no-claude-bin"
mkdir -p "$NO_CLAUDE_BIN"
printf '#!/usr/bin/env bash\nexit 127\n' > "$NO_CLAUDE_BIN/claude"
chmod +x "$NO_CLAUDE_BIN/claude"
export PATH="$NO_CLAUDE_BIN:$PATH"
touch "$HOME/.bashrc"

CLAUDE_DIR="$HOME/.claude"
SETTINGS="$CLAUDE_DIR/settings.json"
ETA="$CLAUDE_DIR/scripts/task-eta.py"
MODEL="$CLAUDE_DIR/task-eta-model.json"
LOCK="$CLAUDE_DIR/task-eta-model.lock"
FITLOG="$CLAUDE_DIR/task-eta-fit.log"

run_install() {  # run_install LOG — exits non-zero into the log, never the terminal
  bash "$INSTALL_SH" </dev/null >"$1" 2>&1
}

refresh() { jq -c '.statusLine.refreshInterval' "$SETTINGS" 2>/dev/null; }

# ─── Suite 1: install.sh and statusLine.refreshInterval ──────────────

section "install.sh: statusLine.refreshInterval"

if run_install "$SANDBOX/install-1.log"; then
  pass "fresh install exits 0"
else
  fail "fresh install exits 0" "see $SANDBOX/install-1.log"
fi
if [[ "$(refresh)" == "10" ]] \
   && [[ "$(jq -r '.statusLine.command' "$SETTINGS")" == "bash ~/.claude/statusline-command.sh" ]]; then
  pass "a fresh install sets refreshInterval 10 beside the command"
else
  fail "a fresh install sets refreshInterval 10 beside the command" "statusLine=$(jq -c .statusLine "$SETTINGS")"
fi
[[ -f "$ETA" ]] && pass "task-eta.py is installed to ~/.claude/scripts" \
  || fail "task-eta.py is installed to ~/.claude/scripts"

jq '.statusLine.refreshInterval = 3 | .model = "sentinel-keep"' "$SETTINGS" > "$SETTINGS.new" && mv "$SETTINGS.new" "$SETTINGS"
run_install "$SANDBOX/install-2.log" || fail "reinstall exits 0" "see $SANDBOX/install-2.log"
if [[ "$(refresh)" == "3" && "$(jq -r .model "$SETTINGS")" == "sentinel-keep" ]]; then
  pass "a reinstall keeps the refreshInterval the user set"
else
  fail "a reinstall keeps the refreshInterval the user set" "refreshInterval=$(refresh)"
fi

jq 'del(.statusLine.refreshInterval)' "$SETTINGS" > "$SETTINGS.new" && mv "$SETTINGS.new" "$SETTINGS"
run_install "$SANDBOX/install-3.log" || fail "reinstall exits 0" "see $SANDBOX/install-3.log"
if [[ "$(refresh)" == "10" ]]; then
  pass "a reinstall adds refreshInterval 10 where it is absent"
else
  fail "a reinstall adds refreshInterval 10 where it is absent" "refreshInterval=$(refresh)"
fi

[[ -n "${SE_TASK_ETA:-}" ]] && cp "$SE_TASK_ETA" "$ETA"
SL="${SE_STATUSLINE:-$CLAUDE_DIR/statusline-command.sh}"

# ─── Synthetic transcripts ───────────────────────────────────────────
# The self-test's own builders, from the repository copy: a seeded history for
# the fit, and one transcript per case. T0 is their fixed instant.

FIX="$SANDBOX/fixtures"
WORK="$SANDBOX/work"
mkdir -p "$FIX" "$WORK"
if ! eval "$(python3 - "$SRC/configs/scripts/task-eta.py" "$CLAUDE_DIR/projects" "$FIX" <<'PY'
import importlib.util, os, random, sys
spec = importlib.util.spec_from_file_location('te', sys.argv[1])
te = importlib.util.module_from_spec(spec)
spec.loader.exec_module(te)
root, fix = sys.argv[2], sys.argv[3]
te._synthetic_history(root, random.Random(1), 250)
T0, MIN = te._T0, te.MIN
wf = (te._Synth().prompt(T0).tool(T0 + 2000, 'b1', 'Bash', command='make').result(T0 + 3000, 'b1')
      .tool(T0 + 5000, 'w1', 'Workflow', script='s').result(T0 + 6000, 'w1', taskId='t-w1').turn_end(T0 + 9000))
wf.write(os.path.join(fix, 'wf.jsonl'))
bad = te._Synth()
bad.lines = wf.lines[:2] + ['{"type":"user","message":', 'not json at all'] + wf.lines[2:]
bad.write(os.path.join(fix, 'malformed.jsonl'))
wf.prompt(T0 + 10 * MIN).turn_end(T0 + 10.5 * MIN).write(os.path.join(fix, 'wf-later-prompt.jsonl'))
te._Synth().prompt(T0).tool(T0 + 2000, 'b1', 'Bash', command='sleep').write(os.path.join(fix, 'fg.jsonl'))
(te._Synth().prompt(T0).tool(T0 + 5000, 'w1', 'Workflow', script='s').result(T0 + 6000, 'w1', taskId='t-w1')
 .tool(T0 + 60000, 's1', 'TaskStop', task_id='t-w1').result(T0 + 61000, 's1', task_id='t-w1')
 .turn_end(T0 + 62000)).write(os.path.join(fix, 'stopped.jsonl'))
(te._Synth().prompt(T0).tool(T0 + 5000, 'w1', 'Workflow', script='s')
 .result(T0 + 6000, 'w1', error='denied by a PreToolUse hook').turn_end(T0 + 9000)).write(os.path.join(fix, 'refused.jsonl'))
open(os.path.join(fix, 'empty.jsonl'), 'w').close()
s = int(T0 / 1000)
print('T2=%d T20=%d T30=%d T300=%d' % (s + 120, s + 1200, s + 1800, s + 18000))
PY
)"; then
  echo "FATAL: could not build the synthetic transcripts"; exit 1
fi

# plain RAW — ANSI colours stripped, runs of spaces squeezed, trailing space dropped (the
# usage segment adds its leading space even when it prints nothing)
plain() { printf '%s' "$1" | sed $'s/\033\\[[0-9;]*m//g' | tr -s ' ' | sed 's/ *$//'; }

# sl NOW TRANSCRIPT — run the status line; sets OUT (plain), RAW, RC, ERR
sl() {
  local payload
  payload=$(jq -cn --arg cwd "$WORK" --arg t "$2" '{cwd: $cwd, transcript_path: $t}')
  RAW=$(printf '%s' "$payload" | CLADE_TASK_ETA_NOW="$1" bash "$SL" 2>"$SANDBOX/sl.err")
  RC=$?
  ERR=$(cat "$SANDBOX/sl.err")
  OUT=$(plain "$RAW")
}

wait_for_model() {  # up to ~30 s for a refit to write the model and release its lock
  local i=0
  while [[ $i -lt 300 ]]; do
    [[ -f "$MODEL" && ! -e "$LOCK" ]] && return 0
    sleep 0.1; i=$((i + 1))
  done
  return 1
}

refits_running() { pgrep -f "$ETA --fit" 2>/dev/null | wc -l | tr -d ' '; }

# ─── Suite 2: the first call has no model ────────────────────────────

section "No model yet: elapsed only, and one detached refit"

rm -f "$MODEL" "$LOCK" "$FITLOG"
sl "$T20" "$FIX/wf.jsonl"
if [[ $RC -eq 0 && "$OUT" == "work 20m workflow" ]]; then
  pass "elapsed only while the model is missing: '$OUT'"
else
  fail "elapsed only while the model is missing" "rc=$RC out='$OUT' err='$ERR'"
fi
if wait_for_model && grep -q "fit ok" "$FITLOG" 2>/dev/null; then
  pass "that call started a refit, which wrote the model and released its lock"
else
  fail "that call started a refit, which wrote the model and released its lock" \
    "model=$([[ -f $MODEL ]] && echo yes || echo no) lock=$([[ -e $LOCK ]] && echo held || echo free) log=$(cat "$FITLOG" 2>/dev/null)"
fi

# ─── Suite 3: the line, with a model ─────────────────────────────────

section "The segment, with a model fitted from the synthetic history"

sl "$T20" "$FIX/wf.jsonl"
if [[ $RC -eq 0 && "$OUT" == "work 20m workflow" ]]; then
  pass "elapsed and the job it waits on, no band: '$OUT'"
else
  fail "elapsed and the job it waits on, no band" "rc=$RC out='$OUT' err='$ERR'"
fi
if [[ "$RAW" == *$'\033[2m20m workflow'* ]]; then
  pass "the segment is dim"
else
  fail "the segment is dim" "raw=$(printf '%q' "$RAW")"
fi
sl "$T30" "$FIX/wf-later-prompt.jsonl"
if [[ "$OUT" == "work 20m workflow" ]]; then
  pass "a prompt typed while the Workflow runs still shows it: '$OUT'"
else
  fail "a prompt typed while the Workflow runs still shows it" "out='$OUT'"
fi
sl "$T2" "$FIX/stopped.jsonl"
if [[ $RC -eq 0 && "$OUT" == "work" ]]; then   # idle: the segment prints nothing
  pass "a Workflow stopped with TaskStop is no longer shown in flight: '$OUT'"
else
  fail "a Workflow stopped with TaskStop is no longer shown in flight" "rc=$RC out='$OUT' err='$ERR'"
fi
sl "$T20" "$FIX/refused.jsonl"
if [[ $RC -eq 0 && "$OUT" == "work" ]]; then
  pass "a Workflow whose launch was refused is not shown in flight: '$OUT'"
else
  fail "a Workflow whose launch was refused is not shown in flight" "rc=$RC out='$OUT' err='$ERR'"
fi
sl "$T300" "$FIX/fg.jsonl"
if [[ "$OUT" == "work 5.0h" ]]; then
  pass "past 4 h: elapsed only, no estimate: '$OUT'"
else
  fail "past 4 h: elapsed only, no estimate" "out='$OUT'"
fi

# ─── Suite 4: fail soft ──────────────────────────────────────────────

section "Fail soft: the other segments render, exit 0, no traceback"

soft() {  # soft NAME — after sl: rc 0, the dir segment, no traceback, nothing after it
  if [[ $RC -eq 0 && "$OUT" == "work" && "$ERR" != *Traceback* ]]; then
    pass "$1"
  else
    fail "$1" "rc=$RC out='$OUT' err='$ERR'"
  fi
}
sl "$T20" "$FIX/missing.jsonl"; soft "no transcript at that path"
sl "$T20" "$FIX/empty.jsonl"; soft "an empty transcript"
sl "$T20" "$FIX"; soft "a directory for a transcript"
RAW=$(printf 'not json' | bash "$SL" 2>"$SANDBOX/sl.err"); RC=$?; ERR=$(cat "$SANDBOX/sl.err")
OUT=$(plain "$RAW")
if [[ $RC -eq 0 && "$ERR" != *Traceback* && "$OUT" != *task* ]]; then
  pass "stdin that is not JSON"
else
  fail "stdin that is not JSON" "rc=$RC out='$OUT' err='$ERR'"
fi
sl "$T20" "$FIX/malformed.jsonl"
if [[ $RC -eq 0 && "$OUT" == "work 20m workflow" && "$ERR" != *Traceback* ]]; then
  pass "malformed lines are skipped, the rest still read: '$OUT'"
else
  fail "malformed lines are skipped, the rest still read" "rc=$RC out='$OUT' err='$ERR'"
fi
printf '{"version": 1, "grid_s": "corrupt"' > "$MODEL"
sl "$T20" "$FIX/wf.jsonl"
if [[ $RC -eq 0 && "$OUT" == "work 20m workflow" && "$ERR" != *Traceback* ]]; then
  pass "a corrupt model reads as no model: elapsed only"
else
  fail "a corrupt model reads as no model: elapsed only" "rc=$RC out='$OUT' err='$ERR'"
fi
wait_for_model >/dev/null    # that call refits too; let it finish before the lock case
CLAUDE_CONFIG_DIR="$SANDBOX/no-such-config-dir" sl "$T20" "$FIX/wf.jsonl"
if [[ $RC -eq 0 && "$OUT" == "work 20m workflow" && "$ERR" != *Traceback* ]]; then
  pass "a missing config dir (no lock can be made): elapsed only"
else
  fail "a missing config dir (no lock can be made): elapsed only" "rc=$RC out='$OUT' err='$ERR'"
fi

# ─── Suite 5: one refit at a time ────────────────────────────────────

section "The refit lock: five concurrent calls start one refit"

wait_for_model
rm -f "$MODEL" "$FITLOG"
export CLADE_TASK_ETA_FIT_DELAY=3       # the refit holds its lock this long before fitting
for _ in 1 2 3 4 5; do
  sl "$T20" "$FIX/wf.jsonl" &
done
wait
n_running=$(refits_running)
wait_for_model
i=0; while [[ $i -lt 50 && "$(refits_running)" != "0" ]]; do sleep 0.1; i=$((i + 1)); done
unset CLADE_TASK_ETA_FIT_DELAY
n_fits=$(grep -c "fit ok" "$FITLOG" 2>/dev/null)
if [[ "$n_running" == "1" && "$n_fits" == "1" ]]; then
  pass "one refit ran, not five (running while held: $n_running, fits logged: $n_fits)"
else
  fail "one refit ran, not five" "running while held: $n_running, fits logged: ${n_fits:-0}"
fi

# ─── Suite 6: slt eta, no python3, escapes ───────────────────────────

section "slt eta off|on, no python3, a backslash in the segment"

bash "$CLAUDE_DIR/scripts/statusline-toggle.sh" eta off >/dev/null
sl "$T20" "$FIX/wf.jsonl"
if [[ "$OUT" == "work" ]]; then pass "slt eta off drops the segment"
else fail "slt eta off drops the segment" "out='$OUT'"; fi
bash "$CLAUDE_DIR/scripts/statusline-toggle.sh" eta on >/dev/null
sl "$T20" "$FIX/wf.jsonl"
if [[ "$OUT" == "work 20m workflow" ]]; then pass "slt eta on brings it back"
else fail "slt eta on brings it back" "out='$OUT'"; fi

NOPY="$SANDBOX/no-python-bin"
mkdir -p "$NOPY"
for tool in bash cat jq git basename sed; do
  p=$(command -v "$tool") && ln -s "$p" "$NOPY/$tool"
done
payload=$(jq -cn --arg cwd "$WORK" --arg t "$FIX/wf.jsonl" '{cwd: $cwd, transcript_path: $t}')
RAW=$(printf '%s' "$payload" | PATH="$NOPY" CLADE_TASK_ETA_NOW="$T20" "$NOPY/bash" "$SL" 2>"$SANDBOX/sl.err"); RC=$?
OUT=$(plain "$RAW")
if [[ $RC -eq 0 && "$OUT" == "work" ]]; then pass "no python3: no segment, the rest renders"
else fail "no python3: no segment, the rest renders" "rc=$RC out='$OUT' err=$(cat "$SANDBOX/sl.err")"; fi

cp "$ETA" "$SANDBOX/task-eta.real"
printf '#!/usr/bin/env python3\nprint(r"a\\nb\\033[31m")\n' > "$ETA"
sl "$T20" "$FIX/wf.jsonl"
cp "$SANDBOX/task-eta.real" "$ETA"
if [[ "$RAW" != *$'\n'* && "$OUT" == "work anb033[31m" ]]; then
  pass "a backslash in the segment is dropped, not read as an escape"
else
  fail "a backslash in the segment is dropped, not read as an escape" "raw=$(printf '%q' "$RAW")"
fi

# ─── Suite 6b: fit to the pane ───────────────────────────────────────
# A long repository name, a long branch, usage data and a drop-in, at the pane
# widths seen on the author's tmux (2026-11-20). Claude Code indents the line two
# columns and keeps two free, so the line must fit COLUMNS - 4. Widths are counted
# in characters, which needs a UTF-8 locale ("…" is one column, three bytes); without one the composer overcounts and drops a piece early, so the
# exact strings are checked only where a UTF-8 locale exists.

section "COLUMNS: the line fits the pane, the task time last to go"

UTF8=""
for l in C.UTF-8 C.utf8 en_US.UTF-8 en_US.utf8; do
  if locale -a 2>/dev/null | grep -qx "$l"; then UTF8=$l; break; fi
done
printf 'number\n' > "$CLAUDE_DIR/.statusline-mode"
LONG="$SANDBOX/faceswap-platform-100"
mkdir -p "$LONG" "$CLAUDE_DIR/statusline-extra.d"
git -C "$LONG" init -q && git -C "$LONG" symbolic-ref HEAD refs/heads/feat/statusline-compact
printf '#!/bin/sh\nprintf "amsg ✓104"\n' > "$CLAUDE_DIR/statusline-extra.d/10-test.sh"
chmod +x "$CLAUDE_DIR/statusline-extra.d/10-test.sh"

slw() {  # slw COLUMNS — the long repository, five days of usage data, the drop-in
  local payload reset=$(( $(date +%s) + 5 * 86400 ))
  payload=$(jq -cn --arg cwd "$LONG" --arg t "$FIX/wf.jsonl" --argjson r "$reset" \
    '{cwd: $cwd, transcript_path: $t, rate_limits: {seven_day: {used_percentage: 80, resets_at: $r}}}')
  RAW=$(printf '%s' "$payload" | LC_ALL="${UTF8:-C}" COLUMNS="$1" CLADE_TASK_ETA_NOW="$T20" \
    bash "$SL" 2>"$SANDBOX/sl.err")
  OUT=$(plain "$RAW")
}
nchars() { python3 -c 'import sys; print(len(sys.argv[1]))' "$1"; }

for w in 227 94 80 70 46 35 29 24; do
  slw "$w"
  n=$(nchars "$OUT")
  if [[ "$n" -le $((w - 4)) && "$OUT" == *" 20m"* && "$OUT" != *"git:("* ]]; then
    pass "COLUMNS=$w: $n columns, the task time kept: '$OUT'"
  else
    fail "COLUMNS=$w: fits in $((w - 4)) with the task time" "$n columns: '$OUT'"
  fi
done

if [[ -n "$UTF8" ]]; then
  while IFS='|' read -r w want; do
    slw "$w"
    if [[ "$OUT" == "$want" ]]; then pass "COLUMNS=$w gives '$want'"
    else fail "COLUMNS=$w gives '$want'" "got '$OUT'"; fi
  done <<'CASES'
94|faceswap-platform-100 feat/statusline-compact 20m workflow +53% (5d) amsg ✓104
80|faceswap-platform-100 feat/statusline-compact 20m workflow +53% (5d)
70|faceswap-platform-100 feat/statusline-compact 20m workflow +53%
46|faceswap-plat… feat/status… 20m +53%
29|faceswap-plat… 20m +53%
24|faceswap-plat… 20m
CASES
else
  echo "  (no UTF-8 locale: exact strings skipped, the fit checks above still ran)"
fi

payload=$(jq -cn --arg cwd "$LONG" --arg t "$FIX/wf.jsonl" '{cwd: $cwd, transcript_path: $t}')
RAW=$(printf '%s' "$payload" | env -u COLUMNS CLADE_TASK_ETA_NOW="$T20" bash "$SL" 2>/dev/null)
OUT=$(plain "$RAW")
if [[ "$OUT" == "faceswap-platform-100 feat/statusline-compact 20m workflow"*"amsg ✓104" ]]; then
  pass "no COLUMNS: everything prints, as before: '$OUT'"
else
  fail "no COLUMNS: everything prints" "out='$OUT'"
fi
rm -f "$CLAUDE_DIR/statusline-extra.d/10-test.sh"

# ─── Suite 7: every guard is observed ────────────────────────────────

if [[ -z "$SE_MUTANT" ]]; then
section "Guard mutations: removing any guard turns this suite red"

MUT_DIR="$SANDBOX/mutants"
mkdir -p "$MUT_DIR"
NMUT=0
MUT_NAMES=(); MUT_EXPECT=(); MUT_ENV=()
mutation() {  # mutation green|red NAME FILE ANCHOR REPLACEMENT
  local file="$3" out var
  case "$file" in
    install.sh)               out="$SRC/install-m$NMUT.sh"; var=SE_INSTALL ;;
    statusline-command.sh)    out="$MUT_DIR/statusline-m$NMUT.sh"; var=SE_STATUSLINE ;;
    task-eta.py)              out="$MUT_DIR/task-eta-m$NMUT.py"; var=SE_TASK_ETA ;;
  esac
  local src="$SRC/install.sh"
  [[ "$file" == "install.sh" ]] || src="$SRC/configs/scripts/$file"
  if ! python3 - "$src" "$out" "$4" "$5" <<'PY'
import sys
src = open(sys.argv[1], encoding="utf-8").read()
if src.count(sys.argv[3]) != 1:
    sys.exit(3)
open(sys.argv[2], "w", encoding="utf-8").write(src.replace(sys.argv[3], sys.argv[4]))
PY
  then
    fail "mutation '$2': its anchor no longer matches $file exactly once"
    return 0
  fi
  MUT_NAMES[NMUT]="$2"; MUT_EXPECT[NMUT]="$1"; MUT_ENV[NMUT]="$var=$out"
  NMUT=$((NMUT + 1))
}

mutation green "no-op control (a comment reworded)" statusline-command.sh \
  '# Inline, not a drop-in: drop-in segments get no stdin' '# Inline, not a drop-in: a drop-in segment gets no stdin'
mutation red "the segment reaches the output" statusline-command.sh \
  '[ -n "$eta" ] && output+=" \033[2m${eta}\033[0m"' ':'
mutation red "the line is fitted to COLUMNS" statusline-command.sh \
  '*) budget=$((COLUMNS - 4)) ;;' '*) ;;'
mutation red "the fit keeps the task time: its forms are read" statusline-command.sh \
  '      eta_short)  eta=$eta_short ;;' '      eta_short)  eta="" ;;'
mutation red "the width counts the drop-in segments" statusline-command.sh \
  '  for p in "$dir" "$branch" "$eta" "$usage_plain" "$extra_plain"; do' \
  '  for p in "$dir" "$branch" "$eta" "$usage_plain"; do'
mutation red "slt eta off is honoured" statusline-command.sh \
  'if [ "$(cat "$HOME/.claude/.statusline-eta" 2>/dev/null)" != "off" ] \' 'if true \'
mutation red "a backslash is dropped before printf %b" statusline-command.sh \
  '  _eta=${_eta//\\/}' '  :'
mutation red "install: a refreshInterval the user set wins" install.sh \
  '((.statusLine | objects | .refreshInterval) // $slr)' '$slr'
mutation red "install: the merge path adds refreshInterval" install.sh \
  '       | .statusLine = '"'"'"$SL_WITH_REFRESH"'"'"'' '       | .statusLine = $sl'
mutation red "install: a fresh install adds refreshInterval" install.sh \
  "'.hooks = \$hooks | .statusLine = '\"\$SL_WITH_REFRESH\"'" "'.hooks = \$hooks | .statusLine = \$sl"
mutation red "task-eta: a missing model starts a refit" task-eta.py \
  '                _SPAWN(cfg, token)' '                pass'
mutation red "task-eta: O_EXCL keeps a second refit out" task-eta.py \
  'os.O_CREAT | os.O_EXCL | os.O_WRONLY' 'os.O_CREAT | os.O_WRONLY'
mutation red "task-eta: a TaskStop ends the job it names" task-eta.py \
  "                self._stop(inp.get('task_id') or inp.get('shell_id'), ts)" '                pass'
mutation red "task-eta: a refused launch never ran" task-eta.py \
  "                self._unlaunch(b.get('tool_use_id'))" '                pass'
mutation red "task-eta: a lock error leaves elapsed time" task-eta.py \
  '        except OSError:                  # a missing or read-only config dir' \
  '        except FileExistsError:          # a missing or read-only config dir'

# Bounded parallelism; bash 3.2 has no `wait -n`, so wait oldest-first.
SE_JOBS=$(getconf _NPROCESSORS_ONLN 2>/dev/null || echo 2)
[[ "$SE_JOBS" =~ ^[0-9]+$ && "$SE_JOBS" -ge 1 ]] || SE_JOBS=2
[[ "$SE_JOBS" -gt 8 ]] && SE_JOBS=8
SELF="$REPO_ROOT/tests/test-statusline-eta.sh"
MUT_PIDS=(); MUT_RCS=()
next=0; i=0
while [[ "$i" -lt "$NMUT" ]]; do
  if [[ $((i - next)) -ge "$SE_JOBS" ]]; then
    wait "${MUT_PIDS[$next]}"; MUT_RCS[next]=$?
    next=$((next + 1))
  fi
  env SE_MUTANT=1 SE_SRC="$SRC" "${MUT_ENV[$i]}" bash "$SELF" > "$MUT_DIR/m$i.log" 2>&1 &
  MUT_PIDS[i]=$!
  i=$((i + 1))
done
while [[ "$next" -lt "$NMUT" ]]; do
  wait "${MUT_PIDS[$next]}"; MUT_RCS[next]=$?
  next=$((next + 1))
done

i=0
while [[ "$i" -lt "$NMUT" ]]; do
  rc="${MUT_RCS[$i]}"
  first=$(grep -m1 '✗' "$MUT_DIR/m$i.log" 2>/dev/null | sed 's/\x1b\[[0-9;]*m//g; s/^ *✗ *//')
  if [[ "${MUT_EXPECT[$i]}" == "green" ]]; then
    if [[ "$rc" -eq 0 ]]; then pass "control: ${MUT_NAMES[$i]} leaves the suite green"
    else fail "control: ${MUT_NAMES[$i]} leaves the suite green" "rc=$rc, first failure: $first"; fi
  elif [[ "$rc" -ne 0 ]]; then
    pass "without ${MUT_NAMES[$i]}: red — ${first:-rc=$rc}"
  else
    fail "without ${MUT_NAMES[$i]}: the suite stayed GREEN" "this guard is claimed and not checked"
  fi
  i=$((i + 1))
done
fi

summary
