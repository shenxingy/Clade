#!/usr/bin/env bash
# test-kimi-uninstall.sh — uninstall.sh §9c takes out the [[hooks]] entries install.sh §11c
# appended to Kimi's config.toml, and nothing else. Split from test-kimi-hooks.sh,
# whose installer cases it shares the header and fixture with.
# Each case installs into a temporary HOME and KIMI_CODE_HOME, then runs the
# real uninstall.sh there. No Kimi process, network, credential, or real user
# file is used.
#
# KIMI_SRC_ROOT may point at a git-show/archive copy of the old tree for the
# required RED control; KIMI_UNINSTALL_SH selects its uninstall.sh alone.

set -uo pipefail

SRC_ROOT="${KIMI_SRC_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
INSTALL_SH="${KIMI_INSTALL_SH:-$SRC_ROOT/install.sh}"
UNINSTALL_SH="${KIMI_UNINSTALL_SH:-$SRC_ROOT/uninstall.sh}"
TMP_ROOT=$(mktemp -d)
trap 'rm -rf "$TMP_ROOT"' EXIT

TESTS_RUN=0
TESTS_PASSED=0
TESTS_FAILED=0
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[0;33m'; NC='\033[0m'
section() { printf "\n${YELLOW}━━━ %s ━━━${NC}\n" "$1"; }
pass() { TESTS_RUN=$((TESTS_RUN + 1)); TESTS_PASSED=$((TESTS_PASSED + 1)); printf "  ${GREEN}✓${NC} %s\n" "$1"; }
fail() {
  TESTS_RUN=$((TESTS_RUN + 1)); TESTS_FAILED=$((TESTS_FAILED + 1))
  printf "  ${RED}✗${NC} %s\n" "$1"
  [[ -z "${2:-}" ]] || printf "    ${RED}→ %s${NC}\n" "$2"
  return 0
}
assert_eq() {
  if [[ "$1" == "$2" ]]; then pass "$3"; else fail "$3" "want='$2' got='$1'"; fi
}
assert_contains() {
  if grep -qF "$2" <<< "$1"; then pass "$3"; else fail "$3" "missing '$2' in: $1"; fi
}
assert_file() {
  if [[ -e "$1" ]]; then pass "$2"; else fail "$2" "missing $1"; fi
}
assert_no_file() {
  if [[ ! -e "$1" ]]; then pass "$2"; else fail "$2" "unexpected $1"; fi
}
assert_probe() {
  local errors rc
  errors=$($1 "$2" "$3" 2>&1)
  rc=$?
  assert_eq "$rc|$errors" "0|" "$4"
}

for required in jq git python3; do
  command -v "$required" >/dev/null 2>&1 || { echo "missing required test tool: $required"; exit 1; }
done

RUN_HOME="$TMP_ROOT/runtime-home"
RUNTIME="$TMP_ROOT/runtime"
SHADOW="$TMP_ROOT/shadows"
PROJ="$TMP_ROOT/project"
FAKE_BIN="$TMP_ROOT/no-network-bin"
mkdir -p "$RUN_HOME/.kimi-code" "$RUNTIME" "$SHADOW" "$PROJ/src" "$FAKE_BIN"
printf 'default_model = "kimi-code/k3"\n' > "$RUN_HOME/.kimi-code/config.toml"
for cmd in gh docker tailscale gcloud; do
  printf '#!/usr/bin/env bash\nexit 0\n' > "$FAKE_BIN/$cmd"
  chmod +x "$FAKE_BIN/$cmd"
done

install_home() {
  local home="$1" log="$2"
  HOME="$home" KIMI_CODE_HOME="$home/.kimi-code" \
    bash "$INSTALL_SH" </dev/null > "$log" 2>&1
}

section "uninstall.sh takes out Clade's Kimi entries and nothing else"
NO_PY_BIN="$TMP_ROOT/no-python-bin"
mkdir -p "$NO_PY_BIN"
for cmd in python python3; do
  printf '#!/usr/bin/env bash\nexit 1\n' > "$NO_PY_BIN/$cmd"
  chmod +x "$NO_PY_BIN/$cmd"
done
# A python3 whose parse check (the one script uninstall.sh feeds on stdin) is
# killed before it prints, as by a signal or the OOM killer; all else is real.
SILENT_PY_BIN="$TMP_ROOT/silent-check-python-bin"
mkdir -p "$SILENT_PY_BIN"
printf '#!/usr/bin/env bash\n[[ "${1:-}" == - ]] && exit 137\nexec %q "$@"\n' "$(command -v python3)" > "$SILENT_PY_BIN/python3"
chmod +x "$SILENT_PY_BIN/python3"
uninstall_home() {  # uninstall_home HOME LOG [UNINSTALL_SH] [PATH_PREFIX]
  local home="$1" log="$2" script="${3:-$UNINSTALL_SH}" path_prefix="${4:-$FAKE_BIN}"
  HOME="$home" KIMI_CODE_HOME="$home/.kimi-code" PATH="$path_prefix:$PATH" PYTHONDONTWRITEBYTECODE=1 \
    bash "$script" </dev/null > "$log" 2>&1
}
# A config.toml in which install.sh's only edit is the appended [[hooks]]
# tables (yolo, extra_skill_dirs and the subagent timeout are already set), so
# install then uninstall must give back these bytes, plus what the user added
# after installing: a comment and an entry directly behind Clade's last one.
UN_T="$TMP_ROOT/uninstall-template"
mkdir -p "$UN_T/.kimi-code"
cat > "$UN_T/.kimi-code/config.toml" <<EOF
# user header comment
default_model = "kimi-code/k3"
default_permission_mode = "yolo"
extra_skill_dirs = ["$UN_T/.kimi-code/clade-skills"]

[[hooks]]
event = "SessionStart"
matcher = "custom-user-matcher"
command = "custom-user-hook"
timeout = 17

[subagent]
timeout_ms = 7200000

# a comment for the provider table
[providers.mine]
api_key = "sk-fixture"
EOF
chmod 640 "$UN_T/.kimi-code/config.toml"
USER_AFTER=$'\n# my own Stop hook\n[[hooks]]\nevent = "Stop"\nmatcher = ""\ncommand = "user-after-install"\ntimeout = 3\n'
{ cat "$UN_T/.kimi-code/config.toml"; printf '%s' "$USER_AFTER"; } > "$TMP_ROOT/un-expected.toml"
install_home "$UN_T" "$TMP_ROOT/un-install.log"
UN_INSTALL_RC=$?
printf '%s' "$USER_AFTER" >> "$UN_T/.kimi-code/config.toml"
mkdir -p "$TMP_ROOT/un-seed"
cp -R "$UN_T/.kimi-code/hooks" "$TMP_ROOT/un-seed/"
cp "$UN_T/.kimi-code/config.toml" "$TMP_ROOT/un-seed/config.toml"

seed_kimi_home() {  # seed_kimi_home DEST — the template's installed state, re-rooted at DEST
  mkdir -p "$1/.kimi-code/hooks"
  cp "$TMP_ROOT/un-seed/hooks/"*.sh "$1/.kimi-code/hooks/"
  python3 - "$TMP_ROOT" "$1" "$UN_T" <<'PY'
import sys
from pathlib import Path
root, dest, old = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
for source, target in ((root / "un-seed" / "config.toml", dest / ".kimi-code" / "config.toml"),
                       (root / "un-expected.toml", dest / "expected.toml")):
    target.write_text(source.read_text(encoding="utf-8").replace(old, str(dest)), encoding="utf-8")
PY
  chmod 640 "$1/.kimi-code/config.toml"
}

kimi_uninstalled() {  # kimi_uninstalled HOME CONFIG — empty when only Clade's entries are gone
  local errors="" mode
  cmp -s "$2" "$1/expected.toml" || errors="config.toml is not the user's bytes: $(diff "$1/expected.toml" "$2" | head -8 | tr '\n' ' ')"
  mode=$(stat -c %a "$2" 2>/dev/null || stat -f %Lp "$2")
  [[ "$mode" == 640 ]] || errors="$errors; config.toml mode is $mode, not 640"
  [[ ! -e "$1/.kimi-code/hooks/decision-to-kimi.sh" ]] || errors="$errors; the adapter was left behind"
  [[ -f "$1/.kimi-code/hooks/statusline.sh" ]] || errors="$errors; statusline.sh, which tui.toml may run, was removed"
  printf '%s' "$errors"
}

# Each probe is also an oracle for the mutation controls below.
probe_kimi_uninstall() {
  local script="$1" probe="$2" d rc errors="" config leftover
  d=$(mktemp -d "$TMP_ROOT/probe-uninstall.XXXXXX") || return 1
  seed_kimi_home "$d"
  config="$d/.kimi-code/config.toml"
  case "$probe" in
    roundtrip|no-python)
      if [[ "$probe" == roundtrip ]]; then
        uninstall_home "$d" "$d/log" "$script"
      else
        uninstall_home "$d" "$d/log" "$script" "$NO_PY_BIN"
      fi
      rc=$?
      errors=$(kimi_uninstalled "$d" "$config")
      ;;
    clade-only)
      # The common config: no [[hooks]] of the user's, so after the uninstall
      # none is left at all, and the parse check must expect no hooks key.
      python3 - "$USER_AFTER" "$config" "$d/expected.toml" <<'PY' || errors="the user [[hooks]] entries could not be dropped from the fixture"
import sys
from pathlib import Path
user_tables = (
    '[[hooks]]\nevent = "SessionStart"\nmatcher = "custom-user-matcher"\ncommand = "custom-user-hook"\ntimeout = 17\n\n',
    sys.argv[1],
)
for name in sys.argv[2:]:
    path = Path(name)
    text = path.read_text(encoding="utf-8")
    for table in user_tables:
        assert text.count(table) == 1, (name, table)
        text = text.replace(table, "")
    path.write_text(text, encoding="utf-8")
PY
      ! grep -qE 'custom-user-hook|user-after-install' "$config" || errors="$errors; the fixture still holds a user [[hooks]] entry"
      uninstall_home "$d" "$d/log" "$script"
      rc=$?
      errors="$errors$(kimi_uninstalled "$d" "$config")"
      ;;
    symlink)
      mkdir -p "$d/actual"
      mv "$config" "$d/actual/config.toml"
      ln -s "$d/actual/config.toml" "$config"
      uninstall_home "$d" "$d/log" "$script"
      rc=$?
      errors=$(kimi_uninstalled "$d" "$d/actual/config.toml")
      [[ -L "$config" ]] || errors="$errors; the config.toml link was replaced by a file"
      ;;
    untouched)
      cp "$d/expected.toml" "$config"
      cp "$config" "$d/before"
      uninstall_home "$d" "$d/log" "$script"
      rc=$?
      cmp -s "$config" "$d/before" || errors="a config.toml holding nothing of Clade's was rewritten"
      ;;
    multiline|unparseable|silent-check)
      if [[ "$probe" != unparseable ]]; then
        # A user string that LOOKS like a Clade table: the line-based edit
        # would cut it, so only the parse check can see the damage.
        printf '\n[notes]\ntext = """\n[[hooks]]\ncommand = "%s/.kimi-code/hooks/decision-to-kimi.sh fake"\n"""\n' "$d" >> "$config"
      else
        printf '\n[broken\n' >> "$config"
      fi
      cp "$config" "$d/before"
      if [[ "$probe" == silent-check ]]; then
        uninstall_home "$d" "$d/log" "$script" "$SILENT_PY_BIN:$FAKE_BIN"
      else
        uninstall_home "$d" "$d/log" "$script"
      fi
      rc=$?
      cmp -s "$config" "$d/before" || errors="a config.toml the uninstaller could not verify was changed"
      [[ -f "$d/.kimi-code/hooks/decision-to-kimi.sh" ]] || errors="$errors; the adapter was deleted while config.toml still runs it"
      grep -qF 'WARNING: Kimi hooks unchanged' "$d/log" || errors="$errors; no warning line"
      ;;
    readonly-dir)
      # No temporary file can be made beside config.toml: the uninstall must
      # say so and carry on to its end, not stop half-way under `set -e`.
      chmod 555 "$d/.kimi-code"
      cp "$config" "$d/before"
      uninstall_home "$d" "$d/log" "$script"
      rc=$?
      chmod 755 "$d/.kimi-code"
      cmp -s "$config" "$d/before" || errors="config.toml changed although no candidate could be written"
      grep -qF 'WARNING: Kimi hooks unchanged (cannot create a temporary file' "$d/log" || errors="$errors; no warning line"
      grep -qF 'Uninstall complete.' "$d/log" || errors="$errors; uninstall stopped before its end"
      ;;
    readonly-file)
      # The edited copy cannot be written back: the uninstall must say so,
      # keep the adapter config.toml still runs and carry on to its end.
      chmod 400 "$config"
      cp "$config" "$d/before"
      uninstall_home "$d" "$d/log" "$script"
      rc=$?
      chmod 640 "$config"
      cmp -s "$config" "$d/before" || errors="a read-only config.toml changed"
      [[ -f "$d/.kimi-code/hooks/decision-to-kimi.sh" ]] || errors="$errors; the adapter was deleted while config.toml still runs it"
      grep -qF 'WARNING: Kimi hooks unchanged (cannot write' "$d/log" || errors="$errors; no warning line"
      grep -qF 'Uninstall complete.' "$d/log" || errors="$errors; uninstall stopped before its end"
      ;;
    *) errors="unknown uninstall probe" ;;
  esac
  # Every probe: the candidate is a full copy of config.toml, provider keys
  # included, so none may outlive the uninstall.
  for leftover in "$d/.kimi-code/.config.toml."*; do
    [[ -e "$leftover" ]] || continue
    errors="$errors; a temporary copy of config.toml was left in ~/.kimi-code"
    break
  done
  [[ "${rc:-1}" == 0 ]] || errors="uninstall exited ${rc:-?} $errors"
  rm -rf "$d"
  [[ -z "$errors" ]] || { printf '%s\n' "$errors"; return 1; }
  return 0
}

UN_CONFIG="$UN_T/.kimi-code/config.toml"
cp "$UN_T/.kimi-code/hooks/statusline.sh" "$TMP_ROOT/un-statusline.sh"
uninstall_home "$UN_T" "$TMP_ROOT/un-uninstall.log"
UN_RC=$?
assert_eq "$UN_INSTALL_RC|$UN_RC" "0|0" "install.sh then uninstall.sh both succeed against the temporary HOME"
cp "$TMP_ROOT/un-expected.toml" "$UN_T/expected.toml"
assert_eq "$(kimi_uninstalled "$UN_T" "$UN_CONFIG")" "" \
  "after a real install: config.toml is the user's bytes again, mode kept, adapter gone, statusline.sh kept"
assert_contains "$(cat "$TMP_ROOT/un-uninstall.log")" "Kimi hooks: 12 removed from $UN_CONFIG" \
  "uninstall.sh reports the twelve entries it took out"
cp "$UN_CONFIG" "$TMP_ROOT/un-after.toml"
uninstall_home "$UN_T" "$TMP_ROOT/un-uninstall-2.log"
UN_RC=$?
cmp -s "$UN_CONFIG" "$TMP_ROOT/un-after.toml"
assert_eq "$UN_RC|$?" "0|0" "a second uninstall leaves config.toml byte-identical"
UN_PROBES="roundtrip no-python symlink untouched clade-only"
UN_PARSE_CHECKED=""
if python3 -c 'import tomllib' >/dev/null 2>&1; then
  UN_PROBES="$UN_PROBES multiline unparseable silent-check"
  UN_PARSE_CHECKED=1
else
  # Without tomllib the uninstaller has no parse check, so it makes the line
  # edit; these probes, and the mutations they judge, would fail either way.
  printf '  - uninstall probes multiline, unparseable, silent-check and the parse-check mutations (tomllib unavailable; not run)\n'
fi
if [[ "$(id -u)" == 0 ]]; then
  # root writes through mode 555 and 400, so these probes cannot fail there.
  printf '  SKIPPED (running as root): uninstall probes readonly-dir, readonly-file and their mutations\n'
else
  UN_PROBES="$UN_PROBES readonly-dir readonly-file"
fi
for probe in $UN_PROBES; do
  assert_probe probe_kimi_uninstall "$UNINSTALL_SH" "$probe" "uninstall probe: $probe"
done

# Guard ablations: a source tree whose uninstall.sh is a mutant and whose
# configs/ is the real one. Rows are one line each (`read` stops at a newline
# and would leave the probe name empty, which "goes red" without running
# anything), and a mutant must still parse, so red means the guard is missed.
mutate() {
  python3 - "$1" "$2" "$3" "$4" <<'PY'
from pathlib import Path
import sys
source, dest, old, new = sys.argv[1:]
text = Path(source).read_text(encoding="utf-8")
assert text.count(old) == 1, (old, text.count(old))
Path(dest).write_text(text.replace(old, new), encoding="utf-8")
PY
}
uninstall_tree() {  # uninstall_tree DIR UNINSTALL_SH
  mkdir -p "$1"
  cp "$2" "$1/uninstall.sh"
  ln -s "$SRC_ROOT/configs" "$1/configs"
}
uninstall_tree "$TMP_ROOT/un-control" "$UNINSTALL_SH"
assert_probe probe_kimi_uninstall "$TMP_ROOT/un-control/uninstall.sh" roundtrip "no-op uninstall tree control remains green"
UNINSTALL_MUTATIONS=(
  $'blank-line\tif (i > 1 && line[i - 1] == "") drop[i - 1] = 1\tif (0) drop[i - 1] = 1\troundtrip'
  $'trailing-comment\tif (is_content(line[k])) last = k\tlast = k\troundtrip'
  $'command-prefix\tif (index(value, want) == 1) clade = 1\tclade = 1\troundtrip'
  $'parse-check\tif [[ -n "$_kimi_problem" ]]; then\tif false; then\tmultiline'
  $'keep-mode\tcat "$_kimi_candidate" > "$KIMI_CONFIG"\tmv "$_kimi_candidate" "$KIMI_CONFIG"\troundtrip'
  $'keep-link\tcat "$_kimi_candidate" > "$KIMI_CONFIG"\tmv "$_kimi_candidate" "$KIMI_CONFIG"\tsymlink'
  $'adapter-kept\tif [[ -f "$KIMI_CONFIG" ]] && grep -qF \'hooks/decision-to-kimi.sh\' "$KIMI_CONFIG"; then\tif false; then\tunparseable'
  $'temp-guard\tif ! _kimi_candidate=$(mktemp "$KIMI_DIR/.config.toml.XXXXXX" 2>/dev/null); then\t_kimi_candidate=$(mktemp "$KIMI_DIR/.config.toml.XXXXXX"); if false; then\treadonly-dir'
  $'write-guard\tif { cat "$_kimi_candidate" > "$KIMI_CONFIG"; } 2>/dev/null; then\tcat "$_kimi_candidate" > "$KIMI_CONFIG"; if true; then\treadonly-file'
  $'adapter-kept-readonly\tif [[ -f "$KIMI_CONFIG" ]] && grep -qF \'hooks/decision-to-kimi.sh\' "$KIMI_CONFIG"; then\tif false; then\treadonly-file'
  $'temp-cleanup\t[[ -z "$_kimi_candidate" ]] || rm -f "$_kimi_candidate"\t:\troundtrip'
)
# The parse check exists only where tomllib does, and so do these mutations of
# it. clade-only runs everywhere, so its probe alone cannot gate them.
[[ -z "$UN_PARSE_CHECKED" ]] || UNINSTALL_MUTATIONS+=(
  $'no-hooks-left\tdel expected["hooks"]\texpected["hooks"] = kept\tclade-only'
  $'check-verdict\t_kimi_problem="${_kimi_problem:-the parse check exited without a verdict}"\t:\tsilent-check'
)
for mutation in "${UNINSTALL_MUTATIONS[@]}"; do
  IFS=$'\t' read -r name old new probe <<< "$mutation"
  [[ -n "$probe" ]] || { fail "uninstall mutation $name is one well-formed row" "$mutation"; continue; }
  [[ " $UN_PROBES " == *" $probe "* ]] || continue
  tree="$TMP_ROOT/un-mut-$name"
  mkdir -p "$tree"
  if ! mutate "$UNINSTALL_SH" "$tree/uninstall.mutant" "$old" "$new" 2>/dev/null; then
    fail "uninstall mutation $name removes its intended guard" "mutation text not found"
    continue
  fi
  uninstall_tree "$tree" "$tree/uninstall.mutant"
  if ! bash -n "$tree/uninstall.sh" 2>/dev/null; then
    fail "uninstall mutation $name still parses" "a mutant that cannot run goes red for the wrong reason"
    continue
  fi
  if probe_kimi_uninstall "$tree/uninstall.sh" "$probe" >/dev/null 2>&1; then
    fail "uninstall mutation $name goes red" "mutant survived $probe"
  else
    pass "uninstall mutation $name goes red"
  fi
done

printf '\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n'
if [[ "$TESTS_FAILED" == 0 ]]; then
  printf "  ${GREEN}ALL PASSED${NC} (%d/%d)\n" "$TESTS_PASSED" "$TESTS_RUN"
else
  printf "  ${RED}%d FAILED${NC} / %d passed / %d total\n" "$TESTS_FAILED" "$TESTS_PASSED" "$TESTS_RUN"
fi
printf '━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n'
exit "$TESTS_FAILED"
