#!/usr/bin/env bash
# test-kimi-hooks.sh — Kimi 2.6.0 hook protocol, install.sh §11c and uninstall.sh §9c.
# Every runtime case executes the exact command read from the installed
# config.toml. HOME, KIMI_CODE_HOME, project, runtime and sync state are
# temporary. No Kimi process, network, credential, or real user file is used.
#
# KIMI_SRC_ROOT may point at a git-show/archive copy of the old tree for the
# required RED control (KIMI_UNINSTALL_SH selects its uninstall.sh alone). KIMI_ADAPTER_OVERRIDE replaces only the installed
# adapter after installation for guard-ablation controls.

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
HISTORY="$RUN_HOME/.claude/corrections/history.jsonl"
FAKE_BIN="$TMP_ROOT/no-network-bin"
SYNC_MARKER="$TMP_ROOT/sync-marker"
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

section "install the runtime fixture"
if install_home "$RUN_HOME" "$TMP_ROOT/runtime-install.log"; then
  pass "install.sh succeeds against the temporary HOME"
else
  fail "install.sh succeeds against the temporary HOME" "see $TMP_ROOT/runtime-install.log"
  printf '\n%d passed, %d failed, %d total\n' "$TESTS_PASSED" "$TESTS_FAILED" "$TESTS_RUN"
  exit 1
fi
if [[ -n "${KIMI_ADAPTER_OVERRIDE:-}" ]]; then
  cp "$KIMI_ADAPTER_OVERRIDE" "$RUN_HOME/.kimi-code/hooks/decision-to-kimi.sh"
  chmod +x "$RUN_HOME/.kimi-code/hooks/decision-to-kimi.sh"
fi

section "print-mode subagent timeout installation"
TIMEOUT_HOME="$TMP_ROOT/subagent-timeout-home"
TIMEOUT_CONFIG="$TIMEOUT_HOME/.kimi-code/config.toml"
TIMEOUT_BASE="$TMP_ROOT/subagent-timeout-base.toml"
TIMEOUT_EXPECTED="$TMP_ROOT/subagent-timeout-expected.toml"
TIMEOUT_SKIP='subagent settings left unchanged'
mkdir -p "$TIMEOUT_HOME/.kimi-code"
python3 - "$RUN_HOME/.kimi-code/config.toml" "$TIMEOUT_CONFIG" "$RUN_HOME" "$TIMEOUT_HOME" <<'PY'
from pathlib import Path
import sys

source, target, source_home, target_home = sys.argv[1:]
text = Path(source).read_text(encoding="utf-8").replace(source_home, target_home)
lines = []
in_subagent = False
for line in text.splitlines(keepends=True):
    if line.strip() == "[subagent]":
        in_subagent = True
        continue
    if in_subagent and line.lstrip().startswith("["):
        in_subagent = False
    if not in_subagent:
        lines.append(line)
for index, line in enumerate(lines):
    if line.lstrip().startswith("["):
        lines.insert(index, 'fixture_root = "unchanged"\n')
        break
else:
    lines.append('fixture_root = "unchanged"\n')
text = "".join(lines) + '\n[fixture_table]\nvalue = "unchanged"\n'
Path(target).write_text(text, encoding="utf-8")
PY
cp "$TIMEOUT_CONFIG" "$TIMEOUT_BASE"

reset_timeout_config() {
  cp "$TIMEOUT_BASE" "$TIMEOUT_CONFIG"
}
timeout_root_form() {
  python3 - "$TIMEOUT_CONFIG" "$1" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
for index, line in enumerate(lines):
    if line.lstrip().startswith("["):
        lines.insert(index, sys.argv[2] + "\n")
        break
else:
    lines.append(sys.argv[2] + "\n")
path.write_text("".join(lines), encoding="utf-8")
PY
}
TIMEOUT_BIN="$TMP_ROOT/timeout-no-python-bin"
mkdir -p "$TIMEOUT_BIN"
for cmd in python python3; do
  printf '#!/usr/bin/env bash\nexit 1\n' > "$TIMEOUT_BIN/$cmd"
  chmod +x "$TIMEOUT_BIN/$cmd"
done
install_timeout_home() {
  HOME="$TIMEOUT_HOME" KIMI_CODE_HOME="$TIMEOUT_HOME/.kimi-code" \
    PATH="$TIMEOUT_BIN:$PATH" bash "$INSTALL_SH" </dev/null > "$1" 2>&1
}
assert_timeout_toml() {
  if ! python3 -c 'import tomllib' >/dev/null 2>&1; then
    printf '  - %s (tomllib unavailable; not run)\n' "$3"
    return
  fi
  local errors
  errors=$(python3 - "$1" "$2" 2>&1 <<'PY'
from pathlib import Path
import sys
import tomllib

try:
    before = tomllib.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    after = tomllib.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
except Exception as exc:
    print(f"TOML parse failed: {exc}")
    raise SystemExit(0)

errors = []
extra_roots = set(after) - set(before) - {"subagent"}
missing_roots = set(before) - set(after)
if extra_roots:
    errors.append(f"unexpected root additions: {sorted(extra_roots)}")
if missing_roots:
    errors.append(f"root keys or tables removed: {sorted(missing_roots)}")
for key in set(before) & set(after) - {"subagent"}:
    if before[key] != after[key]:
        errors.append(f"root key or table changed: {key}")
subagent = after.get("subagent")
if not isinstance(subagent, dict) or subagent.get("timeout_ms") != 7200000:
    errors.append("subagent.timeout_ms != 7200000")
elif "subagent" in before:
    old_subagent = before["subagent"]
    extra = set(subagent) - set(old_subagent) - {"timeout_ms"}
    missing = set(old_subagent) - set(subagent)
    if extra:
        errors.append(f"unexpected subagent keys: {sorted(extra)}")
    if missing:
        errors.append(f"subagent keys removed: {sorted(missing)}")
    for key in set(old_subagent) & set(subagent):
        if old_subagent[key] != subagent[key]:
            errors.append(f"subagent key changed: {key}")
if errors:
    print("; ".join(errors))
PY
)
  assert_eq "$TIMEOUT_RC|$errors" "0|" "$3"
}
assert_timeout_skip() {
  cmp -s "$1" "$TIMEOUT_CONFIG"
  TIMEOUT_CMP=$?
  assert_eq "$TIMEOUT_RC|$TIMEOUT_CMP|$(grep -cF "$TIMEOUT_SKIP" "$2")" \
    "0|0|1" "$3"
}

reset_timeout_config
cp "$TIMEOUT_BASE" "$TIMEOUT_EXPECTED"
printf '\n[subagent]\ntimeout_ms = 7200000\n' >> "$TIMEOUT_EXPECTED"
install_timeout_home "$TMP_ROOT/timeout-absent-1.log"
TIMEOUT_RC=$?
cmp -s "$TIMEOUT_EXPECTED" "$TIMEOUT_CONFIG"
TIMEOUT_CMP=$?
assert_eq "$TIMEOUT_RC|$TIMEOUT_CMP" "0|0" \
  "absent subagent table is appended with the 7200000 ms default"
assert_timeout_toml "$TIMEOUT_BASE" "$TIMEOUT_CONFIG" \
  "absent table: TOML parses and every original root key and table is unchanged"
cp "$TIMEOUT_CONFIG" "$TIMEOUT_EXPECTED"
install_timeout_home "$TMP_ROOT/timeout-absent-2.log"
TIMEOUT_RC=$?
cmp -s "$TIMEOUT_EXPECTED" "$TIMEOUT_CONFIG"
TIMEOUT_CMP=$?
assert_eq "$TIMEOUT_RC|$TIMEOUT_CMP|$(grep -cF "$TIMEOUT_SKIP" "$TMP_ROOT/timeout-absent-2.log")" \
  "0|0|1" "second install is byte-identical and prints one preservation line"

reset_timeout_config
printf '\n[subagent] # existing table\nanswer = 42\n' >> "$TIMEOUT_CONFIG"
cp "$TIMEOUT_CONFIG" "$TMP_ROOT/timeout-table-before.toml"
cp "$TIMEOUT_CONFIG" "$TIMEOUT_EXPECTED"
python3 - "$TIMEOUT_EXPECTED" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
text = path.read_text(encoding="utf-8")
old = "[subagent] # existing table\n"
assert text.count(old) == 1
path.write_text(text.replace(old, old + "timeout_ms = 7200000\n"), encoding="utf-8")
PY
install_timeout_home "$TMP_ROOT/timeout-table.log"
TIMEOUT_RC=$?
cmp -s "$TIMEOUT_EXPECTED" "$TIMEOUT_CONFIG"
TIMEOUT_CMP=$?
assert_eq "$TIMEOUT_RC|$TIMEOUT_CMP" "0|0" \
  "existing table gains timeout_ms directly under its header only"
assert_timeout_toml "$TMP_ROOT/timeout-table-before.toml" "$TIMEOUT_CONFIG" \
  "existing table: its other keys and every original TOML value survive"

reset_timeout_config
printf '\n[subagent]\ntimeout_ms = 17\nanswer = 42\n' >> "$TIMEOUT_CONFIG"
cp "$TIMEOUT_CONFIG" "$TIMEOUT_EXPECTED"
install_timeout_home "$TMP_ROOT/timeout-user-table.log"
TIMEOUT_RC=$?
cmp -s "$TIMEOUT_EXPECTED" "$TIMEOUT_CONFIG"
TIMEOUT_CMP=$?
assert_eq "$TIMEOUT_RC|$TIMEOUT_CMP|$(grep -cF "$TIMEOUT_SKIP" "$TMP_ROOT/timeout-user-table.log")" \
  "0|0|1" "user table timeout is byte-identical with one preservation line"

reset_timeout_config
timeout_root_form 'subagent.timeout_ms = 23'
cp "$TIMEOUT_CONFIG" "$TIMEOUT_EXPECTED"
install_timeout_home "$TMP_ROOT/timeout-dotted.log"
TIMEOUT_RC=$?
cmp -s "$TIMEOUT_EXPECTED" "$TIMEOUT_CONFIG"
TIMEOUT_CMP=$?
assert_eq "$TIMEOUT_RC|$TIMEOUT_CMP|$(grep -cF "$TIMEOUT_SKIP" "$TMP_ROOT/timeout-dotted.log")" \
  "0|0|1" "dotted root timeout is byte-identical with one preservation line"

reset_timeout_config
timeout_root_form 'subagent = { timeout_ms = 29, answer = 42 }'
cp "$TIMEOUT_CONFIG" "$TIMEOUT_EXPECTED"
install_timeout_home "$TMP_ROOT/timeout-inline.log"
TIMEOUT_RC=$?
cmp -s "$TIMEOUT_EXPECTED" "$TIMEOUT_CONFIG"
TIMEOUT_CMP=$?
assert_eq "$TIMEOUT_RC|$TIMEOUT_CMP|$(grep -cF "$TIMEOUT_SKIP" "$TMP_ROOT/timeout-inline.log")" \
  "0|0|1" "inline subagent table is byte-identical with one preservation line"

reset_timeout_config
cat >> "$TIMEOUT_CONFIG" <<'EOF'
timeout_ms = 17
subagent.timeout_ms = 23

[unrelated_inline]
subagent = { timeout_ms = 29 }
EOF
cp "$TIMEOUT_CONFIG" "$TMP_ROOT/timeout-unrelated-before.toml"
cp "$TIMEOUT_CONFIG" "$TIMEOUT_EXPECTED"
printf '\n[subagent]\ntimeout_ms = 7200000\n' >> "$TIMEOUT_EXPECTED"
install_timeout_home "$TMP_ROOT/timeout-unrelated.log"
TIMEOUT_RC=$?
cmp -s "$TIMEOUT_EXPECTED" "$TIMEOUT_CONFIG"
TIMEOUT_CMP=$?
assert_eq "$TIMEOUT_RC|$TIMEOUT_CMP" "0|0" \
  "unrelated-table timeout forms do not suppress the root subagent default"
assert_timeout_toml "$TMP_ROOT/timeout-unrelated-before.toml" "$TIMEOUT_CONFIG" \
  "unrelated-table forms: appended TOML parses and all original values survive"

reset_timeout_config
python3 - "$TIMEOUT_CONFIG" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
data = path.read_bytes()
assert data.endswith(b"\n")
path.write_bytes(data[:-1])
PY
cp "$TIMEOUT_CONFIG" "$TMP_ROOT/timeout-no-newline-before.toml"
cp "$TIMEOUT_CONFIG" "$TIMEOUT_EXPECTED"
printf '\n\n[subagent]\ntimeout_ms = 7200000\n' >> "$TIMEOUT_EXPECTED"
install_timeout_home "$TMP_ROOT/timeout-no-newline.log"
TIMEOUT_RC=$?
cmp -s "$TIMEOUT_EXPECTED" "$TIMEOUT_CONFIG"
TIMEOUT_CMP=$?
assert_eq "$TIMEOUT_RC|$TIMEOUT_CMP" "0|0" \
  "missing trailing newline is terminated before the appended table"
assert_timeout_toml "$TMP_ROOT/timeout-no-newline-before.toml" "$TIMEOUT_CONFIG" \
  "missing trailing newline: TOML parses and original values survive"

section "TOML-safe subagent timeout forms"
reset_timeout_config
timeout_root_form 'subagent.max_concurrency = 3'
cp "$TIMEOUT_CONFIG" "$TIMEOUT_EXPECTED"
install_timeout_home "$TMP_ROOT/timeout-root-dotted-other.log"
TIMEOUT_RC=$?
assert_timeout_skip "$TIMEOUT_EXPECTED" "$TMP_ROOT/timeout-root-dotted-other.log" \
  "root dotted subagent key without timeout is byte-identical with one skip line"

reset_timeout_config
timeout_root_form '"subagent" . max_concurrency = 3'
cp "$TIMEOUT_CONFIG" "$TIMEOUT_EXPECTED"
install_timeout_home "$TMP_ROOT/timeout-root-dotted-double.log"
TIMEOUT_RC=$?
assert_timeout_skip "$TIMEOUT_EXPECTED" "$TMP_ROOT/timeout-root-dotted-double.log" \
  "double-quoted root dotted subagent key is byte-identical with one skip line"

reset_timeout_config
timeout_root_form "'subagent' . timeout_ms = 5"
cp "$TIMEOUT_CONFIG" "$TIMEOUT_EXPECTED"
install_timeout_home "$TMP_ROOT/timeout-root-dotted-single.log"
TIMEOUT_RC=$?
assert_timeout_skip "$TIMEOUT_EXPECTED" "$TMP_ROOT/timeout-root-dotted-single.log" \
  "single-quoted root dotted timeout with dot whitespace is byte-identical"

for form in '"subagent" = { foo = 1 }' "'subagent' = { foo = 1 }"; do
  reset_timeout_config
  timeout_root_form "$form"
  cp "$TIMEOUT_CONFIG" "$TIMEOUT_EXPECTED"
  install_timeout_home "$TMP_ROOT/timeout-quoted-inline-${form:0:1}.log"
  TIMEOUT_RC=$?
  assert_timeout_skip "$TIMEOUT_EXPECTED" "$TMP_ROOT/timeout-quoted-inline-${form:0:1}.log" \
    "quoted inline subagent form ${form:0:1} is byte-identical with one skip line"
done

reset_timeout_config
printf '\n["subagent"]\nfoo = 1\n' >> "$TIMEOUT_CONFIG"
cp "$TIMEOUT_CONFIG" "$TMP_ROOT/timeout-quoted-table-double-before.toml"
install_home "$TIMEOUT_HOME" "$TMP_ROOT/timeout-quoted-table-double.log"
TIMEOUT_RC=$?
assert_timeout_toml "$TMP_ROOT/timeout-quoted-table-double-before.toml" "$TIMEOUT_CONFIG" \
  "double-quoted subagent table gains a valid default through the tomllib guard"

reset_timeout_config
printf "\n['subagent']\nfoo = 1\n" >> "$TIMEOUT_CONFIG"
cp "$TIMEOUT_CONFIG" "$TMP_ROOT/timeout-quoted-table-single-before.toml"
install_timeout_home "$TMP_ROOT/timeout-quoted-table-single.log"
TIMEOUT_RC=$?
assert_timeout_toml "$TMP_ROOT/timeout-quoted-table-single-before.toml" "$TIMEOUT_CONFIG" \
  "single-quoted subagent table gains a valid default without Python"

reset_timeout_config
printf '\n[ "subagent" ]\nfoo = 1\n' >> "$TIMEOUT_CONFIG"
cp "$TIMEOUT_CONFIG" "$TMP_ROOT/timeout-quoted-table-spaced-before.toml"
install_timeout_home "$TMP_ROOT/timeout-quoted-table-spaced.log"
TIMEOUT_RC=$?
assert_timeout_toml "$TMP_ROOT/timeout-quoted-table-spaced-before.toml" "$TIMEOUT_CONFIG" \
  "whitespace inside quoted subagent table brackets is recognised"

reset_timeout_config
printf '\n[subagent]\n"timeout_ms" = 5\n' >> "$TIMEOUT_CONFIG"
cp "$TIMEOUT_CONFIG" "$TIMEOUT_EXPECTED"
install_timeout_home "$TMP_ROOT/timeout-quoted-key-double.log"
TIMEOUT_RC=$?
assert_timeout_skip "$TIMEOUT_EXPECTED" "$TMP_ROOT/timeout-quoted-key-double.log" \
  "double-quoted timeout_ms user value is byte-identical with one skip line"

reset_timeout_config
printf "\n[subagent]\n'timeout_ms' = 5\n" >> "$TIMEOUT_CONFIG"
cp "$TIMEOUT_CONFIG" "$TIMEOUT_EXPECTED"
install_timeout_home "$TMP_ROOT/timeout-quoted-key-single.log"
TIMEOUT_RC=$?
assert_timeout_skip "$TIMEOUT_EXPECTED" "$TMP_ROOT/timeout-quoted-key-single.log" \
  "single-quoted timeout_ms user value is byte-identical with one skip line"

reset_timeout_config
cat >> "$TIMEOUT_CONFIG" <<'EOF'
x = """
\"""
[subagent]
"""
EOF
cp "$TIMEOUT_CONFIG" "$TMP_ROOT/timeout-multiline-basic-before.toml"
install_timeout_home "$TMP_ROOT/timeout-multiline-basic.log"
TIMEOUT_RC=$?
assert_timeout_toml "$TMP_ROOT/timeout-multiline-basic-before.toml" "$TIMEOUT_CONFIG" \
  "multi-line basic strings, including escaped triple quotes, are not edited"

reset_timeout_config
cat >> "$TIMEOUT_CONFIG" <<'EOF'
x = '''
[subagent]
'''
EOF
cp "$TIMEOUT_CONFIG" "$TMP_ROOT/timeout-multiline-literal-before.toml"
install_timeout_home "$TMP_ROOT/timeout-multiline-literal.log"
TIMEOUT_RC=$?
assert_timeout_toml "$TMP_ROOT/timeout-multiline-literal-before.toml" "$TIMEOUT_CONFIG" \
  "multi-line literal string headers are ignored and the default is appended"

for kind in basic literal; do
  reset_timeout_config
  if [[ "$kind" == basic ]]; then
    printf 'x = """\n[subagent]\n' >> "$TIMEOUT_CONFIG"
  else
    printf "x = '''\n[subagent]\n" >> "$TIMEOUT_CONFIG"
  fi
  cp "$TIMEOUT_CONFIG" "$TIMEOUT_EXPECTED"
  install_timeout_home "$TMP_ROOT/timeout-unclosed-$kind.log"
  TIMEOUT_RC=$?
  assert_timeout_skip "$TIMEOUT_EXPECTED" "$TMP_ROOT/timeout-unclosed-$kind.log" \
    "unclosed $kind multi-line string is byte-identical with one skip line"
done

# A multi-line array's element lines can start with `[`; none of them is a
# table header, so the scanner tracks bracket depth outside strings.
reset_timeout_config
timeout_root_form 'matrix = [
  ["a"],
]
subagent.max_concurrency = 3'
cp "$TIMEOUT_CONFIG" "$TIMEOUT_EXPECTED"
install_timeout_home "$TMP_ROOT/timeout-array-then-dotted.log"
TIMEOUT_RC=$?
assert_timeout_skip "$TIMEOUT_EXPECTED" "$TMP_ROOT/timeout-array-then-dotted.log" \
  "root dotted subagent key after a multi-line array is still seen and skipped"

reset_timeout_config
timeout_root_form 'matrix = [
  ["subagent"]
]'
cp "$TIMEOUT_CONFIG" "$TMP_ROOT/timeout-array-element-before.toml"
install_timeout_home "$TMP_ROOT/timeout-array-element.log"
TIMEOUT_RC=$?
assert_timeout_toml "$TMP_ROOT/timeout-array-element-before.toml" "$TIMEOUT_CONFIG" \
  "an array element spelled like [\"subagent\"] is not a table header"

reset_timeout_config
printf '\nmatrix = [\n  1,\n' >> "$TIMEOUT_CONFIG"
cp "$TIMEOUT_CONFIG" "$TIMEOUT_EXPECTED"
install_timeout_home "$TMP_ROOT/timeout-unclosed-array.log"
TIMEOUT_RC=$?
assert_timeout_skip "$TIMEOUT_EXPECTED" "$TMP_ROOT/timeout-unclosed-array.log" \
  "unclosed array is byte-identical with one skip line"

reset_timeout_config
cat >> "$TIMEOUT_CONFIG" <<'EOF'
x = 1 # """
[ "subagent" ]
foo = 1
EOF
cp "$TIMEOUT_CONFIG" "$TMP_ROOT/timeout-comment-delimiter-before.toml"
install_timeout_home "$TMP_ROOT/timeout-comment-delimiter.log"
TIMEOUT_RC=$?
assert_timeout_toml "$TMP_ROOT/timeout-comment-delimiter-before.toml" "$TIMEOUT_CONFIG" \
  "triple quotes in comments do not hide a following quoted table"

reset_timeout_config
printf '\n[[ "subagent" ]]\nfoo = 1\n' >> "$TIMEOUT_CONFIG"
cp "$TIMEOUT_CONFIG" "$TIMEOUT_EXPECTED"
install_timeout_home "$TMP_ROOT/timeout-subagent-array.log"
TIMEOUT_RC=$?
assert_timeout_skip "$TIMEOUT_EXPECTED" "$TMP_ROOT/timeout-subagent-array.log" \
  "subagent array-of-tables is skipped rather than redefined"

reset_timeout_config
printf 'x = """\n""""""\n' >> "$TIMEOUT_CONFIG"
cp "$TIMEOUT_CONFIG" "$TIMEOUT_EXPECTED"
install_timeout_home "$TMP_ROOT/timeout-ambiguous-quotes.log"
TIMEOUT_RC=$?
assert_timeout_skip "$TIMEOUT_EXPECTED" "$TMP_ROOT/timeout-ambiguous-quotes.log" \
  "ambiguous six-quote run is byte-identical with one skip line"

reset_timeout_config
printf 'x = "unterminated\n[subagent]\n"\n' >> "$TIMEOUT_CONFIG"
cp "$TIMEOUT_CONFIG" "$TIMEOUT_EXPECTED"
install_timeout_home "$TMP_ROOT/timeout-unclosed-single.log"
TIMEOUT_RC=$?
assert_timeout_skip "$TIMEOUT_EXPECTED" "$TMP_ROOT/timeout-unclosed-single.log" \
  "unclosed single-line string is byte-identical with one skip line"

if python3 -c 'import tomllib' >/dev/null 2>&1; then
  reset_timeout_config
  printf 'not valid TOML here\n' >> "$TIMEOUT_CONFIG"
  cp "$TIMEOUT_CONFIG" "$TIMEOUT_EXPECTED"
  install_home "$TIMEOUT_HOME" "$TMP_ROOT/timeout-guard-original.log"
  TIMEOUT_RC=$?
  cmp -s "$TIMEOUT_EXPECTED" "$TIMEOUT_CONFIG"
  TIMEOUT_CMP=$?
  assert_eq "$TIMEOUT_RC|$TIMEOUT_CMP|$(grep -cF 'original config.toml does not parse' "$TMP_ROOT/timeout-guard-original.log")" \
    "0|0|1" "tomllib guard preserves an invalid original config"

  for mode in parse root subagent subagent-value timeout-value; do
    case "$mode" in
      parse) expected='candidate config.toml does not parse' ;;
      root) expected='candidate would change root key or table hooks' ;;
      subagent) expected='candidate would add a subagent key other than timeout_ms' ;;
      subagent-value) expected='candidate would change subagent key answer' ;;
      timeout-value) expected='candidate does not set subagent.timeout_ms to 7200000' ;;
    esac
    reset_timeout_config
    if [[ "$mode" == subagent-value ]]; then
      printf '\n[subagent]\nanswer = 42\n' >> "$TIMEOUT_CONFIG"
    fi
    cp "$TIMEOUT_CONFIG" "$TIMEOUT_EXPECTED"
    HOME="$TIMEOUT_HOME" KIMI_CODE_HOME="$TIMEOUT_HOME/.kimi-code" \
      CLADE_TEST_KIMI_SUBAGENT_TIMEOUT_BAD_CANDIDATE="$mode" \
      bash "$INSTALL_SH" </dev/null > "$TMP_ROOT/timeout-guard-$mode.log" 2>&1
    TIMEOUT_RC=$?
    cmp -s "$TIMEOUT_EXPECTED" "$TIMEOUT_CONFIG"
    TIMEOUT_CMP=$?
    assert_eq "$TIMEOUT_RC|$TIMEOUT_CMP|$(grep -cF "$expected" "$TMP_ROOT/timeout-guard-$mode.log")" \
      "0|0|1" "tomllib guard rejects forced $mode candidate corruption"
  done
else
  printf '  - tomllib candidate-guard controls (tomllib unavailable; not run)\n'
fi

git -C "$PROJ" init -q
git -C "$PROJ" config user.email kimi-hooks@example.invalid
git -C "$PROJ" config user.name kimi-hooks
printf '# fixture\n' > "$PROJ/CLAUDE.md"
printf 'one\n' > "$PROJ/src/app.py"
git -C "$PROJ" add -A
git -C "$PROJ" commit -qm 'fixture initial'

hook_command() {
  python3 - "$1/.kimi-code/config.toml" "$2" "$3" <<'PY'
import re, sys
path, event, hook = sys.argv[1:]
blocks, current = [], None
for line in open(path, encoding="utf-8"):
    if line.strip() == "[[hooks]]":
        if current is not None:
            blocks.append(current)
        current = [line]
    elif line.startswith("["):
        if current is not None:
            blocks.append(current)
        current = None
    elif current is not None:
        current.append(line)
if current is not None:
    blocks.append(current)
for block in blocks:
    text = "".join(block)
    def field(name):
        match = re.search(r"(?m)^" + re.escape(name) + r'\s*=\s*"((?:[^"\\]|\\.)*)"\s*$', text)
        return match.group(1) if match else None
    command = field("command") or ""
    if field("event") == event and ("/" + hook) in command:
        print(command)
        break
PY
}

RUN_OUT=""
RUN_RC=0
run_hook() {
  local event="$1" hook="$2" payload="$3" cmd
  cmd=$(hook_command "$RUN_HOME" "$event" "$hook")
  if [[ -z "$cmd" ]]; then
    RUN_OUT="MISSING COMMAND: $event/$hook"
    RUN_RC=97
    return
  fi
  RUN_OUT=$(printf '%s' "$payload" | HOME="$RUN_HOME" KIMI_CODE_HOME="$RUN_HOME/.kimi-code" \
    CLAUDE_PROJECT_DIR="$PROJ" CLADE_RUNTIME_DIR="$RUNTIME" CP_SHADOW_DIR="$SHADOW" \
    SYNC_MARKER="$SYNC_MARKER" PATH="$FAKE_BIN:$PATH" bash -c "$cmd" 2>"$TMP_ROOT/last-stderr")
  RUN_RC=$?
}

# Mirror internal/runHook.ts:resultFromExitCode and structuredOutput.
kimi_verdict() {
  if [[ "$RUN_RC" == 2 ]]; then printf 'BLOCK'; return; fi
  if [[ "$RUN_RC" != 0 ]]; then printf 'ALLOW'; return; fi
  if [[ -z "${RUN_OUT//[[:space:]]/}" ]]; then printf 'ALLOW'; return; fi
  if jq -e '(.hookSpecificOutput.permissionDecision? // "") == "deny"' <<< "$RUN_OUT" >/dev/null 2>&1; then
    printf 'BLOCK'
  elif jq -e '(.message? | type) == "string" or (.hookSpecificOutput.message? | type) == "string"' <<< "$RUN_OUT" >/dev/null 2>&1; then
    printf 'MESSAGE'
  else
    printf 'ALLOW'
  fi
}
assert_verdict() {
  local got
  got=$(kimi_verdict)
  assert_eq "$got" "$2" "$1 (rc=$RUN_RC, verdict=$got)"
}
run_payload() {
  run_hook "$1" "$2" "$3"
  assert_verdict "$4" "$5"
}

prompt_payload() {
  jq -nc --arg sid "$1" --arg prompt "$2" --arg cwd "$PROJ" \
    '{hook_event_name:"UserPromptSubmit",session_id:$sid,cwd:$cwd,
      prompt:[{type:"text",text:"first part"},{type:"image_url",imageUrl:{url:"fixture"}},{type:"text",text:$prompt}]}'
}
tool_payload() {
  jq -nc --arg event "$1" --arg sid "$2" --arg name "$3" --argjson input "$4" --arg cwd "$PROJ" \
    '{hook_event_name:$event,session_id:$sid,cwd:$cwd,tool_name:$name,tool_input:$input,tool_call_id:"call_fixture",tool_output:"fixture output"}'
}

section "PreToolUse guards through the installed commands"
run_payload PreToolUse pre-tool-guardian.sh \
  "$(tool_payload PreToolUse session_guard Bash '{"command":"git push --force origin main"}')" \
  "guardian denies a force push to main" BLOCK
assert_contains "$(jq -r '.hookSpecificOutput.permissionDecisionReason // empty' <<< "$RUN_OUT")" \
  "Force push to main/master blocked" "guardian preserves its own deny reason"
run_payload PreToolUse pre-tool-guardian.sh \
  "$(tool_payload PreToolUse session_guard Bash '{"command":"git status --short"}')" \
  "guardian allows a safe Bash call" ALLOW
run_payload PreToolUse pre-tool-guardian.sh \
  "$(tool_payload PreToolUse session_guard Bash '{"command":"rm -rf $BUILD_DIR/"}')" \
  "guardian rewrite becomes a deny, never an original-command allow" BLOCK
assert_contains "$(jq -r '.hookSpecificOutput.permissionDecisionReason // empty' <<< "$RUN_OUT")" \
  'BUILD_DIR:?' "rewrite denial names the safer command"
run_payload PreToolUse linter-config-guard.sh \
  "$(tool_payload PreToolUse session_lint Edit '{"path":"/tmp/.ruff.toml","old_string":"a","new_string":"b"}')" \
  "linter guard sees Kimi's Edit path and denies" BLOCK
assert_contains "$(jq -r '.hookSpecificOutput.permissionDecisionReason // empty' <<< "$RUN_OUT")" \
  "/tmp/.ruff.toml" "linter denial names the protected path"
run_payload PreToolUse linter-config-guard.sh \
  "$(tool_payload PreToolUse session_lint Write '{"path":"/tmp/app.py","content":"print(1)\n"}')" \
  "linter guard allows an ordinary Write" ALLOW

section "UserPromptSubmit prompt arrays, context and attribution"
SECRET='sk-'"test-1234567890abcdefghij"  # split so the staged-diff secret scan does not see a literal key
run_payload UserPromptSubmit secret-scanner.sh \
  "$(prompt_payload session_secret "credential is $SECRET")" \
  "secret scanner reads prompt parts and emits a Kimi message" MESSAGE
assert_contains "$(jq -r '.message // empty' <<< "$RUN_OUT")" \
  "Handle it as data" "secret note is the wrapped hook's own handling guidance"
run_payload UserPromptSubmit secret-scanner.sh \
  "$(prompt_payload session_secret "ordinary request with no credential")" \
  "secret scanner stays silent on a safe prompt" ALLOW

SID='session_c49ae4fd-1b85-4f0f-aaaa-bbbbbbbbbbbb'
run_payload UserPromptSubmit correction-detector.sh \
  "$(prompt_payload "$SID" "No, that is wrong. Use the safer approach instead.")" \
  "correction detector reads prompt parts and emits a Kimi message" MESSAGE
assert_contains "$(jq -r '.message // empty' <<< "$RUN_OUT")" \
  "possible correction" "correction context reaches Kimi's message field"
LAST=$(tail -n 1 "$HISTORY" 2>/dev/null)
assert_eq "$(jq -r '.session_id // empty' <<< "$LAST")" "$SID" \
  "correction history keeps Kimi's session_ id intact"
assert_eq "$(jq -r 'has("transcript_path") and (.transcript_path == null)' <<< "$LAST")" "true" \
  "missing Kimi transcript_path persists as null"
BEFORE=$(wc -l < "$HISTORY" | tr -d ' ')
run_payload UserPromptSubmit correction-detector.sh \
  "$(prompt_payload "$SID" "Please refactor the parser and add coverage.")" \
  "correction detector stays silent on a non-correction" ALLOW
assert_eq "$(wc -l < "$HISTORY" | tr -d ' ')" "$BEFORE" \
  "safe prompt writes no correction record"

section "data-only correction loop and cleanup"
run_payload PostToolUse edit-shadow-detector.sh \
  "$(tool_payload PostToolUse "$SID" Edit "{\"path\":\"$PROJ/src/app.py\",\"old_string\":\"one\",\"new_string\":\"two\"}")" \
  "edit shadow records through Kimi's path argument without output" ALLOW
SHADOW_FILE="$SHADOW/session-$SID.jsonl"
assert_file "$SHADOW_FILE" "edit shadow uses the intact Kimi session id"
assert_contains "$(cat "$SHADOW_FILE" 2>/dev/null)" "$PROJ/src/app.py" "edit shadow records the written file"
run_payload PostToolUse revert-detector.sh \
  "$(tool_payload PostToolUse "$SID" Bash '{"command":"git checkout -- src/app.py"}')" \
  "PostToolUse revert detector stays data-only" ALLOW
LAST=$(tail -n 1 "$HISTORY" 2>/dev/null)
assert_eq "$(jq -r '.type // empty' <<< "$LAST")" "implicit-revert" "revert is recorded after the Bash call"
assert_eq "$(jq -r '.session_id // empty' <<< "$LAST")" "$SID" "revert history keeps the session_ id"
assert_eq "$(jq -r '.transcript_path == null' <<< "$LAST")" "true" "revert transcript_path is null, not a crash"
assert_contains "$(jq -c '.reverted_files' <<< "$LAST")" "src/app.py" "revert pairs the file recorded by the shadow"
BEFORE=$(wc -l < "$HISTORY" | tr -d ' ')
run_payload PostToolUse revert-detector.sh \
  "$(tool_payload PostToolUse "$SID" Bash '{"command":"git status --short"}')" \
  "an ordinary Bash result writes no revert record" ALLOW
assert_eq "$(wc -l < "$HISTORY" | tr -d ' ')" "$BEFORE" "safe Bash leaves history unchanged"
run_payload SessionEnd session-end-cleanup.sh \
  "$(tool_payload SessionEnd "$SID" Bash '{"command":""}')" \
  "SessionEnd cleanup has no protocol output" ALLOW
assert_no_file "$SHADOW_FILE" "SessionEnd removes only the ending session's shadow"

section "session baseline and one-continuation Stop guard"
STOP_SID='session_stop_guard_01'
run_payload SessionStart session-baseline.sh \
  "$(tool_payload SessionStart "$STOP_SID" Bash '{"command":""}')" \
  "SessionStart baseline needs no model channel" ALLOW
BASELINE="$PROJ/.claude/sessions/$STOP_SID.baseline"
assert_file "$BASELINE" "SessionStart writes the stop-check baseline"
printf 'dirty\n' > "$PROJ/src/new-file.txt"
run_payload Stop stop-check.sh \
  "$(jq -nc --arg sid "$STOP_SID" --arg cwd "$PROJ" '{hook_event_name:"Stop",session_id:$sid,cwd:$cwd,stop_hook_active:false}')" \
  "stop-check exit-2 becomes a Kimi block" BLOCK
assert_contains "$(jq -r '.hookSpecificOutput.permissionDecisionReason // empty' <<< "$RUN_OUT")" \
  "uncommitted change" "Stop block carries the hook's stderr reason"
CLEAN_SID='session_stop_clean_01'
run_payload SessionStart session-baseline.sh \
  "$(tool_payload SessionStart "$CLEAN_SID" Bash '{"command":""}')" \
  "a second baseline runs for the clean-stop fixture" ALLOW
run_payload Stop stop-check.sh \
  "$(jq -nc --arg sid "$CLEAN_SID" --arg cwd "$PROJ" '{hook_event_name:"Stop",session_id:$sid,cwd:$cwd,stop_hook_active:false}')" \
  "stop-check allows a session with no new dirt" ALLOW

section "SessionStart context is delivered once on the first prompt"
CONTEXT_SID='session_context_once_01'
PAYLOAD=$(prompt_payload "$CONTEXT_SID" "Please continue the current task")
run_payload UserPromptSubmit session-context.sh "$PAYLOAD" \
  "session context reaches the first Kimi prompt" MESSAGE
assert_contains "$(jq -r '.message // empty' <<< "$RUN_OUT")" "Recent commits:" \
  "first-prompt message contains the wrapped SessionStart context"
SENTINEL="$RUNTIME/kimi-session-context/$CONTEXT_SID.session-context.sh.once"
assert_file "$SENTINEL" "once-per-session sentinel lives under the private runtime dir"
run_payload UserPromptSubmit session-context.sh "$PAYLOAD" \
  "the same session gets no duplicate context" ALLOW
run_payload UserPromptSubmit session-context.sh \
  "$(prompt_payload session_context_once_02 "Please continue")" \
  "a different Kimi session gets its own context" MESSAGE

section "SessionEnd releases only the ending session's first-prompt sentinel"
ONCE_DIR="$RUNTIME/kimi-session-context"
OTHER_SENTINEL="$ONCE_DIR/session_context_once_02.session-context.sh.once"
PREFIX_SENTINEL="$ONCE_DIR/${CONTEXT_SID}x.session-context.sh.once"
mkdir -p "$PREFIX_SENTINEL"
assert_file "$OTHER_SENTINEL" "a parallel session holds its own sentinel"
# Each id below must release nothing: a dotted id the shadow sanitizer would
# fold onto session_context_once_02, a traversal that resolves to its sentinel,
# and two ids that begin with a valid id and only fail the regex at its $
# anchor, one running into the other session's sentinel name and one passing
# through the first session's sentinel and back out with "..". Both sentinels
# are put back after each id, so a release is reported by the id that caused
# it and does not cascade into the cases after it.
for HOSTILE in 'session.context_once_02' '../kimi-session-context/session_context_once_02' \
  'session_context_once_02.session-context' \
  "$CONTEXT_SID.session-context.sh.once/../session_context_once_02"; do
  run_payload SessionEnd session-end-cleanup.sh \
    "$(tool_payload SessionEnd "$HOSTILE" Bash '{"command":""}')" \
    "SessionEnd for id '$HOSTILE' has no protocol output" ALLOW
  assert_file "$OTHER_SENTINEL" "id '$HOSTILE' cannot release another session's sentinel"
  assert_file "$SENTINEL" "id '$HOSTILE' leaves the first session's sentinel"
  mkdir -p "$OTHER_SENTINEL" "$SENTINEL"
done
# Names the ending id's glob does match, but that are not an empty sentinel
# directory: a regular file, a directory with contents, and a symlink to an
# empty directory. The hook's rmdir must leave all three, and must not follow
# the link to the directory behind it.
PLANTED_FILE="$ONCE_DIR/${CONTEXT_SID}.planted.once"
PLANTED_FULL="$ONCE_DIR/${CONTEXT_SID}.full.once"
PLANTED_LINK="$ONCE_DIR/${CONTEXT_SID}.link.once"
LINK_TARGET="$TMP_ROOT/once-link-target"
mkdir -p "$PLANTED_FULL" "$LINK_TARGET"
: > "$PLANTED_FILE"
: > "$PLANTED_FULL/keep"
ln -s "$LINK_TARGET" "$PLANTED_LINK"
run_payload SessionEnd session-end-cleanup.sh \
  "$(tool_payload SessionEnd "$CONTEXT_SID" Bash '{"command":""}')" \
  "SessionEnd with a sentinel to release has no protocol output" ALLOW
assert_no_file "$SENTINEL" "SessionEnd releases the ending session's sentinel"
assert_file "$OTHER_SENTINEL" "a parallel session's sentinel survives that SessionEnd"
assert_file "$PREFIX_SENTINEL" "an id that only extends the ending id keeps its sentinel"
if [[ -f "$PLANTED_FILE" && ! -L "$PLANTED_FILE" ]]; then
  pass "a regular file under the ending id's sentinel name survives"
else
  fail "a regular file under the ending id's sentinel name survives" "missing $PLANTED_FILE"
fi
assert_file "$PLANTED_FULL/keep" "a sentinel-named directory with contents keeps them"
if [[ -L "$PLANTED_LINK" && -d "$LINK_TARGET" ]]; then
  pass "a sentinel-named symlink is neither removed nor followed"
else
  fail "a sentinel-named symlink is neither removed nor followed" "link or its target is gone"
fi
rm -rf "$PLANTED_FILE" "$PLANTED_FULL" "$PLANTED_LINK" "$LINK_TARGET"
run_payload UserPromptSubmit session-context.sh "$PAYLOAD" \
  "a resumed session (same id after SessionEnd) gets the context once more" MESSAGE
assert_file "$SENTINEL" "the resumed session claims a fresh sentinel"
ln -s "$RUNTIME" "$TMP_ROOT/runtime-link"
RUN_OUT=$(tool_payload SessionEnd session_context_once_02 Bash '{"command":""}' | \
  HOME="$RUN_HOME" CLADE_RUNTIME_DIR="$TMP_ROOT/runtime-link" CP_SHADOW_DIR="$SHADOW" \
  bash -c "$(hook_command "$RUN_HOME" SessionEnd session-end-cleanup.sh)")
RUN_RC=$?
assert_eq "$RUN_RC|$RUN_OUT" "0|" "a symlinked runtime root fails open with no output"
assert_file "$OTHER_SENTINEL" "a symlinked runtime root is never followed to a sentinel"
RUN_OUT=$(tool_payload SessionEnd session_context_once_02 Bash '{"command":""}' | \
  HOME="$RUN_HOME" CLADE_RUNTIME_DIR="$RUNTIME" CP_SHADOW_DIR="$TMP_ROOT/no-shadow-dir" \
  bash -c "$(hook_command "$RUN_HOME" SessionEnd session-end-cleanup.sh)")
RUN_RC=$?
assert_eq "$RUN_RC|$RUN_OUT" "0|" "SessionEnd with no shadow dir exits 0 silently"
assert_no_file "$OTHER_SENTINEL" "the sentinel is released even when the session left no shadow dir"
rmdir "$PREFIX_SENTINEL" 2>/dev/null

section "memory sync on both PostToolUse matchers"
: > "$RUN_HOME/.claude/.sync-config"
cat > "$RUN_HOME/.claude/scripts/sync-push.sh" <<'EOF'
#!/usr/bin/env bash
printf 'push\n' >> "$SYNC_MARKER"
EOF
chmod +x "$RUN_HOME/.claude/scripts/sync-push.sh"
run_payload PostToolUse memory-sync.sh \
  "$(tool_payload PostToolUse session_memory Edit "{\"path\":\"$RUN_HOME/.claude/hooks/learned.md\",\"old_string\":\"a\",\"new_string\":\"b\"}")" \
  "memory-sync Edit is fire-and-forget with no stdout" ALLOW
for _ in $(seq 1 50); do [[ -f "$SYNC_MARKER" ]] && break; sleep 0.1; done
assert_eq "$(grep -c '^push$' "$SYNC_MARKER" 2>/dev/null || true)" "1" \
  "Kimi Edit path triggers the real memory-sync entry point"
run_payload PostToolUse memory-sync.sh \
  "$(tool_payload PostToolUse session_memory Bash '{"command":"touch ~/.claude/hooks/another.md"}')" \
  "memory-sync Bash is also fire-and-forget" ALLOW
for _ in $(seq 1 50); do [[ "$(grep -c '^push$' "$SYNC_MARKER" 2>/dev/null || true)" == 2 ]] && break; sleep 0.1; done
assert_eq "$(grep -c '^push$' "$SYNC_MARKER" 2>/dev/null || true)" "2" \
  "the distinct Bash wiring invokes the same command again"
run_payload PostToolUse memory-sync.sh \
  "$(tool_payload PostToolUse session_memory Edit "{\"path\":\"$PROJ/src/app.py\",\"old_string\":\"one\",\"new_string\":\"two\"}")" \
  "an unsynced path is a safe no-op" ALLOW
assert_eq "$(grep -c '^push$' "$SYNC_MARKER" 2>/dev/null || true)" "2" \
  "unsynced Edit does not invoke sync-push"

section "remaining adapter protocol forms and fail-open"
ADAPTER="$RUN_HOME/.kimi-code/hooks/decision-to-kimi.sh"
LEGACY="$TMP_ROOT/legacy-block.sh"
cat > "$LEGACY" <<'EOF'
#!/usr/bin/env bash
cat >/dev/null
printf '%s' '{"decision":"block","reason":"legacy block reason"}'
EOF
chmod +x "$LEGACY"
RUN_OUT=$(prompt_payload session_legacy "block this" | HOME="$RUN_HOME" "$ADAPTER" "$LEGACY")
RUN_RC=$?
assert_verdict "legacy decision:block becomes a Kimi block" BLOCK
assert_contains "$(jq -r '.hookSpecificOutput.permissionDecisionReason // empty' <<< "$RUN_OUT")" \
  "legacy block reason" "legacy block reason survives"
LEGACY_REWRITE="$TMP_ROOT/legacy-rewrite.sh"
cat > "$LEGACY_REWRITE" <<'EOF'
#!/usr/bin/env bash
cat >/dev/null
printf '%s' '{"decision":"allow","updatedInput":{"command":"echo safer"}}'
EOF
chmod +x "$LEGACY_REWRITE"
RUN_OUT=$(prompt_payload session_legacy_rewrite "rewrite this" | HOME="$RUN_HOME" "$ADAPTER" "$LEGACY_REWRITE")
RUN_RC=$?
assert_verdict "legacy top-level updatedInput becomes a deny" BLOCK
assert_contains "$(jq -r '.hookSpecificOutput.permissionDecisionReason // empty' <<< "$RUN_OUT")" \
  "echo safer" "legacy rewrite denial names the safer command"
NONCOMMAND_REWRITE="$TMP_ROOT/noncommand-rewrite.sh"
cat > "$NONCOMMAND_REWRITE" <<'EOF'
#!/usr/bin/env bash
cat >/dev/null
printf '%s' '{"hookSpecificOutput":{"updatedInput":{"file_path":"/tmp/safer.txt"}}}'
EOF
chmod +x "$NONCOMMAND_REWRITE"
RUN_OUT=$(prompt_payload session_noncommand_rewrite "rewrite this" | HOME="$RUN_HOME" "$ADAPTER" "$NONCOMMAND_REWRITE")
RUN_RC=$?
assert_verdict "a non-command updatedInput is still refused, never dropped" BLOCK
assert_contains "$(jq -r '.hookSpecificOutput.permissionDecisionReason // empty' <<< "$RUN_OUT")" \
  "/tmp/safer.txt" "non-command rewrite denial describes the requested input"
EMPTY_BLOCK="$TMP_ROOT/empty-block.sh"
printf '#!/usr/bin/env bash\ncat >/dev/null\nexit 2\n' > "$EMPTY_BLOCK"
chmod +x "$EMPTY_BLOCK"
RUN_OUT=$(prompt_payload session_empty_block "stop" | HOME="$RUN_HOME" "$ADAPTER" "$EMPTY_BLOCK" 2>/dev/null)
RUN_RC=$?
assert_verdict "exit 2 with no stderr still blocks" BLOCK
assert_contains "$(jq -r '.hookSpecificOutput.permissionDecisionReason // empty' <<< "$RUN_OUT")" \
  "Blocked by UserPromptSubmit hook" "an empty block reason gets Kimi's default reason"
EMPTY_JSON="$TMP_ROOT/empty-json-block.sh"
printf '#!/usr/bin/env bash\ncat >/dev/null\nprintf "%%s" '\''{"decision":"block"}'\''\n' > "$EMPTY_JSON"
chmod +x "$EMPTY_JSON"
RUN_OUT=$(prompt_payload session_empty_json "stop" | HOME="$RUN_HOME" "$ADAPTER" "$EMPTY_JSON")
RUN_RC=$?
assert_contains "$(jq -r '.hookSpecificOutput.permissionDecisionReason // empty' <<< "$RUN_OUT")" \
  "Blocked by UserPromptSubmit hook" "an empty JSON block reason also gets the default"
MALFORMED="$TMP_ROOT/malformed-input.sh"
cat > "$MALFORMED" <<'EOF'
#!/usr/bin/env bash
input=$(cat)
if [[ "$input" == '{broken' ]]; then
  printf '%s' '{"decision":"block","reason":"raw input preserved"}'
else
  printf '%s' '{"decision":"block","reason":"raw input lost"}'
fi
EOF
chmod +x "$MALFORMED"
RUN_OUT=$(printf '{broken' | HOME="$RUN_HOME" "$ADAPTER" "$MALFORMED")
RUN_RC=$?
assert_contains "$(jq -r '.hookSpecificOutput.permissionDecisionReason // empty' <<< "$RUN_OUT")" \
  "raw input preserved" "malformed JSON reaches the wrapped hook unchanged under fail-open"
printf 'not a directory\n' > "$TMP_ROOT/runtime-blocker"
RUN_OUT=$(prompt_payload session_runtime_failure "continue" | HOME="$RUN_HOME" CLAUDE_PROJECT_DIR="$PROJ" \
  CLADE_RUNTIME_DIR="$TMP_ROOT/runtime-blocker" "$ADAPTER" --once-per-session \
  "$RUN_HOME/.claude/hooks/session-context.sh")
RUN_RC=$?
assert_eq "$RUN_RC|$RUN_OUT" "0|" "unavailable private runtime state fails open without context"
PLAIN="$TMP_ROOT/plain-context.sh"
cat > "$PLAIN" <<'EOF'
#!/usr/bin/env bash
cat >/dev/null
printf 'plain prompt context'
EOF
chmod +x "$PLAIN"
RUN_OUT=$(prompt_payload session_plain "continue" | HOME="$RUN_HOME" "$ADAPTER" "$PLAIN")
RUN_RC=$?
assert_eq "$RUN_OUT" "plain prompt context" "plain stdout uses Kimi's prompt-context channel unchanged"
RUN_OUT=$(printf '{}' | "$ADAPTER" "$TMP_ROOT/does-not-exist" 2>/dev/null)
RUN_RC=$?
assert_eq "$RUN_RC|$RUN_OUT" "0|" "missing wrapped hook fails open"
NONZERO="$TMP_ROOT/nonzero-hook.sh"
cat > "$NONZERO" <<'EOF'
#!/usr/bin/env bash
cat >/dev/null
printf 'partial output that must not be injected'
exit 1
EOF
chmod +x "$NONZERO"
RUN_OUT=$(prompt_payload session_nonzero "continue" | HOME="$RUN_HOME" "$ADAPTER" "$NONZERO" 2>/dev/null)
RUN_RC=$?
assert_eq "$RUN_RC|$RUN_OUT" "0|" "a non-zero, non-block wrapped exit fails open without partial context"
WRONG_EVENT="$RUNTIME/kimi-session-context/session_wrong_event.session-context.sh.once"
RUN_OUT=$(tool_payload SessionStart session_wrong_event Bash '{"command":""}' | \
  HOME="$RUN_HOME" CLAUDE_PROJECT_DIR="$PROJ" CLADE_RUNTIME_DIR="$RUNTIME" \
  "$ADAPTER" --once-per-session "$RUN_HOME/.claude/hooks/session-context.sh")
RUN_RC=$?
assert_eq "$RUN_RC|$RUN_OUT" "0|" "once-only context does not run on SessionStart itself"
assert_no_file "$WRONG_EVENT" "wrong-event invocation writes no once sentinel"
BAD_ID='bad.id'
BAD_SENTINEL="$RUNTIME/kimi-session-context/$BAD_ID.session-context.sh.once"
RUN_OUT=$(prompt_payload "$BAD_ID" "continue" | HOME="$RUN_HOME" CLAUDE_PROJECT_DIR="$PROJ" \
  CLADE_RUNTIME_DIR="$RUNTIME" "$ADAPTER" --once-per-session "$RUN_HOME/.claude/hooks/session-context.sh")
RUN_RC=$?
assert_eq "$RUN_RC|$RUN_OUT" "0|" "a non-Kimi-shaped session id cannot arm first-prompt context"
assert_no_file "$BAD_SENTINEL" "invalid session id writes no sentinel"
NORMALISE="$TMP_ROOT/normalise-check.sh"
cat > "$NORMALISE" <<'EOF'
#!/usr/bin/env bash
input=$(cat)
jq -nr --argjson input "$input" '
  if ($input.hook_event_name == "UserPromptSubmit"
      and ($input.prompt | type) == "string"
      and ($input | has("transcript_path"))
      and $input.transcript_path == null)
  then "normalised" else "not normalised" end'
EOF
chmod +x "$NORMALISE"
RUN_OUT=$(prompt_payload session_normalise "one two" | HOME="$RUN_HOME" "$ADAPTER" "$NORMALISE")
RUN_RC=$?
assert_eq "$RUN_OUT" "normalised" "event name, prompt string and null transcript reach the wrapped hook"
EVENT_DEFAULT="$TMP_ROOT/event-default-check.sh"
cat > "$EVENT_DEFAULT" <<'EOF'
#!/usr/bin/env bash
input=$(cat)
jq -nr --argjson input "$input" '
  {hookSpecificOutput:{permissionDecision:"deny",permissionDecisionReason:(
    if ($input | has("hook_event_name")) then "event key present" else "event key missing" end)}}'
EOF
chmod +x "$EVENT_DEFAULT"
RUN_OUT=$(jq -nc '{session_id:"session_event_default",prompt:[{type:"text",text:"continue"}]}' | \
  HOME="$RUN_HOME" "$ADAPTER" "$EVENT_DEFAULT")
RUN_RC=$?
assert_contains "$(jq -r '.hookSpecificOutput.permissionDecisionReason // empty' <<< "$RUN_OUT")" \
  "event key present" "adapter supplies hook_event_name even for a hand-piped payload"

section "installer migration, idempotency and user entries"
check_config() {
  python3 - "$1" "$2" "$3" <<'PY'
import re, sys
home, expected_total, user_mode = sys.argv[1], int(sys.argv[2]), sys.argv[3]
path = home + "/.kimi-code/config.toml"
text = open(path, encoding="utf-8").read()
raw = re.split(r"(?m)^\[\[hooks\]\]\s*$", text)[1:]
entries = []
for chunk in raw:
    chunk = re.split(r"(?m)^\[(?!\[hooks\]\])", chunk, maxsplit=1)[0]
    def field(name):
        m = re.search(r"(?m)^" + name + r"\s*=\s*(.+?)\s*$", chunk)
        return m.group(1).strip() if m else None
    entries.append({k: field(k) for k in ("event", "matcher", "command", "timeout")})
specs = [
    ("PreToolUse", "Bash", "pre-tool-guardian.sh", "5", ""),
    ("PreToolUse", "Edit|Write", "linter-config-guard.sh", "5", ""),
    ("UserPromptSubmit", "", "secret-scanner.sh", "5", ""),
    ("UserPromptSubmit", "", "correction-detector.sh", "5", ""),
    ("PostToolUse", "Edit|Write", "edit-shadow-detector.sh", "5", ""),
    ("PostToolUse", "Bash", "revert-detector.sh", "5", ""),
    ("SessionStart", "startup|clear", "session-baseline.sh", "5", ""),
    ("SessionEnd", "", "session-end-cleanup.sh", "5", ""),
    ("UserPromptSubmit", "", "session-context.sh", "10", "--once-per-session "),
    ("Stop", "", "stop-check.sh", "10", ""),
    ("PostToolUse", "Edit|Write", "memory-sync.sh", "10", ""),
    ("PostToolUse", "Bash", "memory-sync.sh", "10", ""),
]
errors = []
if len(entries) != expected_total:
    errors.append(f"entry count {len(entries)} != {expected_total}")
for event, matcher, hook, timeout, mode in specs:
    command = f'"{home}/.kimi-code/hooks/decision-to-kimi.sh {mode}{home}/.claude/hooks/{hook}"'
    matches = [e for e in entries if e == {"event": f'"{event}"', "matcher": f'"{matcher}"', "command": command, "timeout": timeout}]
    if len(matches) != 1:
        errors.append(f"{event}/{matcher}/{hook}: exact entry count {len(matches)}")
if user_mode == "user":
    user = '"custom-user-hook"'
    if sum(e["command"] == user for e in entries) != 1:
        errors.append("user-written entry missing or duplicated")
if errors:
    print("; ".join(errors))
    sys.exit(1)
PY
}

OLD_HOME="$TMP_ROOT/old-guardian-home"
mkdir -p "$OLD_HOME/.kimi-code"
cat > "$OLD_HOME/.kimi-code/config.toml" <<EOF
default_model = "kimi-code/k3"

[[hooks]]
event = "PreToolUse"
matcher = "Bash"
command = "$OLD_HOME/.kimi-code/hooks/decision-to-kimi.sh $OLD_HOME/.claude/hooks/pre-tool-guardian.sh"
timeout = 5
EOF
install_home "$OLD_HOME" "$TMP_ROOT/old-install-1.log"
OLD_RC=$?
assert_eq "$OLD_RC" "0" "legacy-only guardian home installs successfully"
OLD_CHECK=$(check_config "$OLD_HOME" 12 legacy 2>&1)
assert_eq "$OLD_CHECK" "" "legacy guardian migrates to exactly the 12-entry portable set"
install_home "$OLD_HOME" "$TMP_ROOT/old-install-2.log"
SECOND_CHECK=$(check_config "$OLD_HOME" 12 legacy 2>&1)
assert_eq "$SECOND_CHECK" "" "second install adds no duplicate entries"

USER_HOME="$TMP_ROOT/user-hook-home"
mkdir -p "$USER_HOME/.kimi-code"
cat > "$USER_HOME/.kimi-code/config.toml" <<'EOF'
default_model = "kimi-code/k3"

[[hooks]]
event = "SessionStart"
matcher = "custom-user-matcher"
command = "custom-user-hook"
timeout = 17
EOF
USER_BLOCK=$(sed -n '/^\[\[hooks\]\]$/,$p' "$USER_HOME/.kimi-code/config.toml")
install_home "$USER_HOME" "$TMP_ROOT/user-install-1.log"
USER_CHECK=$(check_config "$USER_HOME" 13 user 2>&1)
assert_eq "$USER_CHECK" "" "user-written hook survives beside the portable set"
install_home "$USER_HOME" "$TMP_ROOT/user-install-2.log"
USER_CHECK=$(check_config "$USER_HOME" 13 user 2>&1)
assert_eq "$USER_CHECK" "" "reinstall preserves the user entry exactly once"
assert_eq "$(sed -n '/^\[\[hooks\]\]$/,$p' "$USER_HOME/.kimi-code/config.toml" | head -5)" "$USER_BLOCK" \
  "the user-written TOML block is byte-for-byte untouched"

EMPTY_HOME="$TMP_ROOT/no-config-home"
mkdir -p "$EMPTY_HOME/.kimi-code"
install_home "$EMPTY_HOME" "$TMP_ROOT/no-config-install.log"
assert_no_file "$EMPTY_HOME/.kimi-code/config.toml" "installer never fabricates Kimi config.toml"

section "uninstall.sh takes out Clade's Kimi entries and nothing else"
NO_PY_BIN="$TMP_ROOT/no-python-bin"
mkdir -p "$NO_PY_BIN"
for cmd in python python3; do
  printf '#!/usr/bin/env bash\nexit 1\n' > "$NO_PY_BIN/$cmd"
  chmod +x "$NO_PY_BIN/$cmd"
done
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
  local script="$1" probe="$2" d rc errors="" config
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
    multiline|unparseable)
      if [[ "$probe" == multiline ]]; then
        # A user string that LOOKS like a Clade table: the line-based edit
        # would cut it, so only the parse check can see the damage.
        printf '\n[notes]\ntext = """\n[[hooks]]\ncommand = "%s/.kimi-code/hooks/decision-to-kimi.sh fake"\n"""\n' "$d" >> "$config"
      else
        printf '\n[broken\n' >> "$config"
      fi
      cp "$config" "$d/before"
      uninstall_home "$d" "$d/log" "$script"
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
    *) errors="unknown uninstall probe" ;;
  esac
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
UN_PROBES="roundtrip no-python symlink untouched multiline unparseable readonly-dir"
if [[ "$(id -u)" == 0 ]]; then
  # root writes into a mode-555 directory, so the probe cannot fail there.
  UN_PROBES="${UN_PROBES% readonly-dir}"
  printf '  SKIPPED (running as root): uninstall probe readonly-dir and its mutation\n'
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
