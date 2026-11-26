#!/usr/bin/env bash
# ci-local-runner.sh — runner labels, tag-only tiers and the files every step
# gets: the cases of tests/test-ci-local.sh that pin configs/scripts/
# ci_local_runner.py and its call sites in ci-local.py.
#
# Sourced by that suite, never run on its own: it uses the suite's helpers
# (pass, fail, assert_*, section), its $RUNNER and $SANDBOX, check_json from
# tests/lib/ci-local-flaky.sh, and — for ci_local_runner_mutations, called from
# the suite's mutation table — its `mutation` function. Split out because
# test-ci-local.sh sits at the edge of the 1500-line cap.
#
# Each case is a shape a real repository hit on 2026-11-21, when scamai moved
# its CI to owned hardware:
#   - `runs-on: [self-hosted, macOS, macserver-public]` named no platform to a
#     case-sensitive match, so a witty macOS job's steps ran on a Linux host.
#     Labels compare case-insensitively now, OS and architecture labels alike,
#     in a flow list, a block list, a group/labels mapping, comments ignored;
#   - `on: push: tags: ["v*"]` ran on every branch head, where its tag check
#     failed by construction. A workflow only a tag push starts is a reasoned
#     tag tier now, run on a head that carries a tag, with --all, or by --job;
#   - `echo dir >> "$GITHUB_PATH"` failed: no step had $GITHUB_ENV,
#     $GITHUB_PATH, $GITHUB_OUTPUT, $GITHUB_STEP_SUMMARY, $RUNNER_TEMP or
#     $GITHUB_WORKSPACE, and inside a hosted job a step wrote into the OUTER
#     job's files. Each job now gets its own, and $GITHUB_ENV and $GITHUB_PATH
#     writes reach the later steps of that job only.
# And one from 2026-11-17: validate-plugin.yml's `npm install -g` wrote into
# the host's own global npm prefix, so two gates on one host raced there
# (npm ENOTEMPTY) and a local gate replaced the developer's installed CLI.
# Each job now gets an npm global prefix of its own; two concurrent runs
# install a local package into theirs while a throwaway "host" prefix, set the
# ways a developer's machine sets one, must come out byte-for-byte unchanged.
# A step that uses nvm is the exception, found in review on 2026-11-25: nvm
# refuses NPM_CONFIG_PREFIX and the step exited 11, green on main. It now runs
# with no prefix and its output says so; a stub nvm.sh plays nvm's part. A
# second review found the step whose text does not show nvm (a script it runs
# loads it, an eval): without -e it passed on the wrong node. nvm's refusal in
# its output now makes it run again without the prefix.
# Every step that runs records what it saw, so the assertions read what
# happened, not what was printed about it.

# ─── Fixtures ────────────────────────────────────────────────────────
# The suite runs on Linux (its other cases expect "needs Darwin"); the
# architecture is whichever this host has.
RL_HERE_ARCH=$(python3 -c "
import platform; m = platform.machine().lower()
print('X64' if m in ('x86_64', 'amd64') else 'ARM64' if m in ('aarch64', 'arm64') else 'ARM')")
if [[ "$RL_HERE_ARCH" == X64 ]]; then RL_OTHER_ARCH=ARM64; else RL_OTHER_ARCH=X64; fi

LABELS="$SANDBOX/labels"; mkdir -p "$LABELS/.github/workflows"
cat > "$LABELS/.github/workflows/labels.yml" <<YAML
name: Labels
on: [push, pull_request]
jobs:
  self_mac:
    name: Self-hosted Mac
    runs-on: [self-hosted, macOS, macserver-public]
    steps:
      - name: Mac only
        run: touch .self-mac-ran
  self_linux:
    name: Self-hosted Linux
    runs-on: [self-hosted, LINUX, castor]
    steps:
      - name: Linux
        run: touch .self-linux-ran
  other_arch:
    name: Other Arch
    runs-on: [self-hosted, Linux, $RL_OTHER_ARCH]
    steps:
      - name: Another architecture
        run: touch .other-arch-ran
  same_arch:
    name: Same Arch
    runs-on: [self-hosted, linux, $(tr '[:upper:]' '[:lower:]' <<< "$RL_HERE_ARCH")]
    steps:
      - name: This architecture
        run: touch .same-arch-ran
  block_list:
    name: Block List
    runs-on:
      - self-hosted
      - MacOS
    steps:
      - name: A list below the key
        run: touch .block-list-ran
  group_labels:
    name: Group Labels
    runs-on:  # the group's runners carry these labels
      group: macserver-private
      labels:
        - self-hosted
        - macOS
    steps:
      - name: A mapping below the key
        run: touch .group-labels-ran
  flow_group:
    name: Flow Group
    runs-on: {group: windows-box, labels: [self-hosted, Windows]}
    steps:
      - name: A flow mapping
        run: touch .flow-group-ran
  commented:
    name: Commented
    runs-on: self-hosted  # was macos-latest
    steps:
      - name: The comment is not a label
        run: touch .commented-ran
  hosted_upper:
    name: Hosted Upper
    runs-on: MACOS-15
    steps:
      - name: Upper-case image
        run: touch .hosted-upper-ran
YAML

FILES="$SANDBOX/files"; mkdir -p "$FILES/.github/workflows"
cat > "$FILES/.github/workflows/files.yml" <<'YAML'
name: Files
on: [push, pull_request]
jobs:
  writer:
    name: Runner Files
    runs-on: ubuntu-latest
    env:
      CI_LOCAL_T_JOBVAL: job
    steps:
      - name: Write the command files
        id: write
        run: |
          r() { if eval "$2"; then echo "$1 ok"; else echo "$1 BAD"; fi >> .files-results; }
          r temp-empty 'test -d "$RUNNER_TEMP" && test -z "$(ls -A "$RUNNER_TEMP")"'
          r temp-outside 'case "$RUNNER_TEMP" in "$PWD"/*) false ;; *) true ;; esac'
          r workspace 'test "$GITHUB_WORKSPACE" = "$PWD"'
          mkdir -p "$RUNNER_TEMP/bin"
          printf '#!/bin/sh\necho tool-on-path\n' > "$RUNNER_TEMP/bin/ci-local-t-tool"
          chmod +x "$RUNNER_TEMP/bin/ci-local-t-tool"
          echo "$RUNNER_TEMP/bin" >> "$GITHUB_PATH"
          echo "CI_LOCAL_T_FILE=from-file" >> "$GITHUB_ENV"
          echo "CI_LOCAL_T_JOBVAL=from-file" >> "$GITHUB_ENV"
          echo "CI_LOCAL_T_OWN=from-file" >> "$GITHUB_ENV"
          { echo "CI_LOCAL_T_MULTI<<CI_LOCAL_EOF"; echo "line one"; echo "line two"; echo CI_LOCAL_EOF; } >> "$GITHUB_ENV"
          echo "answer=42" >> "$GITHUB_OUTPUT"
          echo "### summary" >> "$GITHUB_STEP_SUMMARY"
          echo "saved=1" >> "$GITHUB_STATE"
          r writer-unset 'test -z "${CI_LOCAL_T_FILE+set}"'
      - name: Read them
        env:
          CI_LOCAL_T_OWN: step
        run: |
          r() { if eval "$2"; then echo "$1 ok"; else echo "$1 BAD"; fi >> .files-results; }
          r env 'test "$CI_LOCAL_T_FILE" = from-file'
          r env-over-job 'test "$CI_LOCAL_T_JOBVAL" = from-file'
          r own-over-env 'test "$CI_LOCAL_T_OWN" = step'
          r heredoc 'test "$CI_LOCAL_T_MULTI" = "$(printf "line one\nline two")"'
          r path 'test "$(ci-local-t-tool)" = tool-on-path'
      - name: Reads an output
        if: steps.write.outputs.answer == '42'
        run: touch .output-read-ran
  next:
    name: Next Job
    runs-on: ubuntu-latest
    steps:
      - name: Sees none of it
        run: |
          r() { if eval "$2"; then echo "$1 ok"; else echo "$1 BAD"; fi >> .files-results; }
          r job-env 'test -z "${CI_LOCAL_T_FILE+set}"'
          r job-path '! command -v ci-local-t-tool >/dev/null'
          r job-temp 'test -d "$RUNNER_TEMP" && test -z "$(ls -A "$RUNNER_TEMP")"'
  bad_env:
    name: Bad Env File
    runs-on: ubuntu-latest
    steps:
      - name: Writes a line the runner rejects
        run: echo "NO_EQUALS_SIGN" >> "$GITHUB_ENV"
      - name: Never reached
        run: touch .after-bad-env-ran
  open_heredoc:
    name: Open Heredoc
    runs-on: ubuntu-latest
    steps:
      - name: Never closes its heredoc
        run: printf 'CI_LOCAL_T_X<<END\nvalue\n' >> "$GITHUB_ENV"
YAML

# npm's global prefix. The caller's is a throwaway "host" prefix, set every
# way a developer's machine sets one: ~/.npmrc, NPM_CONFIG_PREFIX and a
# lower-case npm_config_prefix (npm reads both spellings, and the last in the
# environment wins). It is on PATH and holds a decoy of each bin a step
# installs, so a step that runs the host's copy says so.
NPMG="$SANDBOX/npm-global"; mkdir -p "$NPMG/bin" "$NPMG/lib/node_modules" "$SANDBOX/npm-home"
for b in ci-local-t-npmbin ci-local-t-hello; do
  printf '#!/bin/sh\necho host-global\n' > "$NPMG/bin/$b"; chmod +x "$NPMG/bin/$b"
done
printf 'prefix=%s\n' "$NPMG" > "$SANDBOX/npm-home/.npmrc"
NPM_TMP="$SANDBOX/npm-tmp"; mkdir -p "$NPM_TMP"
npm_caller() {
  env HOME="$SANDBOX/npm-home" NPM_CONFIG_PREFIX="$NPMG" npm_config_prefix="$NPMG" \
    CI_LOCAL_T_NPMG="$NPMG" PATH="$NPMG/bin:$PATH" TMPDIR="$NPM_TMP" "$@"
}
NPMW="$SANDBOX/npm-env"; mkdir -p "$NPMW/.github/workflows"
cat > "$NPMW/.github/workflows/npm.yml" <<'YAML'
name: Npm
on: [push, pull_request]
jobs:
  first:
    name: Npm Prefix
    runs-on: ubuntu-latest
    steps:
      - name: Installs into its own prefix
        run: |
          r() { if eval "$2"; then echo "$1 ok"; else echo "$1 BAD"; fi >> .npm-results; }
          echo "$NPM_CONFIG_PREFIX" > .npm-prefix-first
          r one-spelling 'test "$(env | grep -ci "^npm_config_prefix=")" = 1'
          r not-callers 'test "$NPM_CONFIG_PREFIX" != "$CI_LOCAL_T_NPMG"'
          r empty 'test -d "$NPM_CONFIG_PREFIX" && test -z "$(ls -A "$NPM_CONFIG_PREFIX")"'
          r outside 'case "$NPM_CONFIG_PREFIX" in "$PWD"/*) false ;; *) true ;; esac'
          r root-on-path 'case ":$PATH:" in *":$NPM_CONFIG_PREFIX:"*) true ;; *) false ;; esac'
          test -n "$NPM_CONFIG_PREFIX" || exit 1     # never write /bin
          mkdir -p "$NPM_CONFIG_PREFIX/bin"
          printf '#!/bin/sh\necho job-prefix\n' > "$NPM_CONFIG_PREFIX/bin/ci-local-t-npmbin"
          chmod +x "$NPM_CONFIG_PREFIX/bin/ci-local-t-npmbin"
          r bin-first 'test "$(ci-local-t-npmbin)" = job-prefix'
      - name: Runs what the step before installed
        run: |
          r() { if eval "$2"; then echo "$1 ok"; else echo "$1 BAD"; fi >> .npm-results; }
          r same-prefix 'test "$NPM_CONFIG_PREFIX" = "$(cat .npm-prefix-first)"'
          r installed-earlier 'test "$(ci-local-t-npmbin)" = job-prefix'
      # The spelling npm documents. Before the $GITHUB_ENV write below, which
      # would rightly hand this step an upper-case one as well.
      - name: Names a lower-case prefix of its own
        env:
          npm_config_prefix: npm-own-lower
        run: |
          r() { if eval "$2"; then echo "$1 ok"; else echo "$1 BAD"; fi >> .npm-results; }
          r lower-one-spelling 'test "$(env | grep -ci "^npm_config_prefix=")" = 1 && test "$(env | grep -c "^npm_config_prefix=")" = 1'
          r lower-wins 'test "$npm_config_prefix" = npm-own-lower'
      - name: Names a prefix of its own
        env:
          NPM_CONFIG_PREFIX: npm-own-prefix
        run: |
          r() { if eval "$2"; then echo "$1 ok"; else echo "$1 BAD"; fi >> .npm-results; }
          r workflow-wins 'test "$NPM_CONFIG_PREFIX" = npm-own-prefix'
          echo "NPM_CONFIG_PREFIX=npm-env-file-prefix" >> "$GITHUB_ENV"
      - name: Reads the prefix GITHUB_ENV names
        run: |
          r() { if eval "$2"; then echo "$1 ok"; else echo "$1 BAD"; fi >> .npm-results; }
          r env-file-wins 'test "$NPM_CONFIG_PREFIX" = npm-env-file-prefix'
  second:
    name: Npm Next Job
    runs-on: ubuntu-latest
    steps:
      - name: Starts from an empty prefix
        run: |
          r() { if eval "$2"; then echo "$1 ok"; else echo "$1 BAD"; fi >> .npm-results; }
          r next-job-own 'test "$NPM_CONFIG_PREFIX" != "$(cat .npm-prefix-first)"'
          r next-job-empty 'test -d "$NPM_CONFIG_PREFIX" && test -z "$(ls -A "$NPM_CONFIG_PREFIX")"'
          r host-bins-kept 'test "$(ci-local-t-npmbin)" = host-global'
  expr:
    name: Npm Expression Prefix
    runs-on: ubuntu-latest
    env:
      NPM_CONFIG_PREFIX: ${{ runner.temp }}/npm
    steps:
      - name: Its prefix only the hosted run can set
        run: |
          r() { if eval "$2"; then echo "$1 ok"; else echo "$1 BAD"; fi >> .npm-results; }
          r expr-own 'test -n "$NPM_CONFIG_PREFIX" && test "$NPM_CONFIG_PREFIX" != "$CI_LOCAL_T_NPMG"'
          r expr-one-spelling 'test "$(env | grep -ci "^npm_config_prefix=")" = 1'
YAML
# The real thing: `npm install -g` of a local package (a tarball, no network),
# then its bin, in two checkouts gated at once, as two worktrees were.
NPM_PKG="$SANDBOX/npm-pkg/package"; mkdir -p "$NPM_PKG"
printf '{"name": "ci-local-t-pkg", "version": "1.0.0", "bin": {"ci-local-t-hello": "hello.js"}}\n' \
  > "$NPM_PKG/package.json"
printf '#!/usr/bin/env node\nconsole.log("hello-from-ci-local-t-pkg");\n' > "$NPM_PKG/hello.js"
chmod +x "$NPM_PKG/hello.js"
for c in a b; do
  mkdir -p "$SANDBOX/npm-$c/.github/workflows"
  tar -czf "$SANDBOX/npm-$c/ci-local-t-pkg.tgz" -C "$SANDBOX/npm-pkg" package
  cat > "$SANDBOX/npm-$c/.github/workflows/npm.yml" <<'YAML'
name: Npm Install
on: [push, pull_request]
jobs:
  install:
    name: Npm Install
    runs-on: ubuntu-latest
    steps:
      - name: Install a CLI globally
        run: npm install -g --offline --no-audit --no-fund ./ci-local-t-pkg.tgz
      - name: Run it
        run: |
          ci-local-t-hello > .npm-hello
          npm prefix -g > .npm-global-prefix
          command -v ci-local-t-hello > .npm-hello-path
YAML
done
# Every entry under a directory with its mtime and size, the directory's own
# mtime last: what "unchanged" means for the host prefix.
npm_manifest() {
  python3 - "$1" <<'PY'
import os, sys
root = sys.argv[1]
paths = sorted(os.path.join(d, n) for d, dirs, files in os.walk(root) for n in dirs + files)
for p in paths + [root]:
    st = os.lstat(p)
    print(os.path.relpath(p, root), st.st_mtime_ns, st.st_size)
PY
}

# nvm refuses NPM_CONFIG_PREFIX. A stand-in for nvm.sh, so no real nvm is
# needed: what nvm_die_on_prefix does (nvm 0.40.1, ~/.nvm/nvm.sh). Any
# spelling of npm_config_prefix, compared upper-cased, set outside $NVM_DIR
# makes `nvm use` print nvm's refusal, deactivate nvm's node (here
# CI_LOCAL_T_NODE, which a successful `nvm use` sets to "stub") and return
# 11; sourcing it with a default alias runs `nvm use default`, which fails
# the step under bash -e. "Nvm By Name" and "Nvm Positions" load it through a
# variable, so only their `nvm` commands say nvm; "Nvm Mentions Only" says nvm
# every way that is not using it, and must keep the job's prefix. "Nvm
# Indirect" loads it where the text does not show it: in scripts, one with no
# -e (the review's shape, green on the wrong node), and in an eval. That
# script writes $GITHUB_ENV and $GITHUB_PATH entries named for the node it
# ran on, and a later step records which reached it: only the run again's.
NVMW="$SANDBOX/npm-nvm"; mkdir -p "$NVMW/.github/workflows" "$NVMW/nvm-stub/alias" "$NVMW/nvm-bare" "$NVMW/tools"
touch "$NVMW/nvm-stub/alias/default"
cat > "$NVMW/nvm-stub/nvm.sh" <<'SH'
nvm() {
  _n=$(awk 'BEGIN { for (k in ENVIRON) if (toupper(k) == "NPM_CONFIG_PREFIX") { print k; exit } }')
  if [ -n "$_n" ]; then
    eval "_v=\${$_n}"
    case "$_v" in
      "" | "$NVM_DIR"/*) ;;
      *) unset CI_LOCAL_T_NODE
         echo "nvm is not compatible with the \"$_n\" environment variable: currently set to \"$_v\"" >&2
         echo "Run \`unset $_n\` to unset it." >&2
         return 11 ;;
    esac
  fi
  CI_LOCAL_T_NODE=stub
  echo "Now using node (stub)"
}
if [ -f "$NVM_DIR/alias/default" ]; then nvm use default --silent > /dev/null; fi
SH
cat > "$NVMW/tools/use-node.sh" <<'SH'
#!/usr/bin/env bash
# A project script that loads nvm, with no -e.
export NVM_DIR="$PWD/nvm-stub"
. "$NVM_DIR/nvm.sh"
nvm use 22 >/dev/null
echo "script node=${CI_LOCAL_T_NODE:-host}"
# What it leaves for the job's later steps names the node it ran on.
echo "NODE_SEEN_${CI_LOCAL_T_NODE:-host}=1" >> "$GITHUB_ENV"
echo "$PWD/seen-${CI_LOCAL_T_NODE:-host}" >> "$GITHUB_PATH"
SH
cat > "$NVMW/tools/use-node-e.sh" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
export NVM_DIR="$PWD/nvm-stub"
. "$NVM_DIR/nvm.sh"
echo "script-e node=${CI_LOCAL_T_NODE:-host}"
SH
chmod +x "$NVMW/tools/use-node.sh" "$NVMW/tools/use-node-e.sh"
cat > "$NVMW/.github/workflows/nvm.yml" <<'YAML'
name: Nvm
on: [push, pull_request]
jobs:
  sources:
    name: Nvm Sources
    runs-on: ubuntu-latest
    steps:
      - name: Sources nvm.sh and nothing else
        run: |
          r() { if eval "$2"; then echo "$1 ok"; else echo "$1 BAD"; fi >> .nvm-results; }
          export NVM_DIR="$PWD/nvm-stub"
          . "$NVM_DIR/nvm.sh"
          r sourced-ran 'true'
          r sourced-no-prefix 'test "$(env | grep -ci "^npm_config_prefix=")" = 0'
          r sourced-bins-on-path 'case ":$PATH:" in *"/npm-prefix/bin:"*) true ;; *) false ;; esac'
  by_name:
    name: Nvm By Name
    runs-on: ubuntu-latest
    steps:
      - name: Loads nvm under another name and runs it
        run: |
          r() { if eval "$2"; then echo "$1 ok"; else echo "$1 BAD"; fi >> .nvm-results; }
          export NVM_DIR="$PWD/nvm-bare"
          . "$CI_LOCAL_T_NVM_LOAD"
          nvm use 22
          r by-name-ran 'true'
  mentions:
    name: Nvm Mentions Only
    runs-on: ubuntu-latest
    steps:
      - name: Mentions nvm without using it
        run: |
          r() { if eval "$2"; then echo "$1 ok"; else echo "$1 BAD"; fi >> .nvm-results; }
          # nvm use 22 is not needed here, and nor is nvm.sh
          nvm_unused="$HOME/.nvm/versions NVM_DIR=${NVM_DIR-} nvm-free"
          r mentions-own 'test -n "$NPM_CONFIG_PREFIX" && test "$NPM_CONFIG_PREFIX" != "$CI_LOCAL_T_NPMG"'
      # Where a command starts, followed by each character that ends no word
      # but is not the nvm command either.
      - name: Assigns a variable named nvm
        run: |
          r() { if eval "$2"; then echo "$1 ok"; else echo "$1 BAD"; fi >> .nvm-results; }
          nvm=unused
          r mentions-assign 'test -n "$NPM_CONFIG_PREFIX" && test "$NPM_CONFIG_PREFIX" != "$CI_LOCAL_T_NPMG"'
      - name: Names a command nvm-free
        run: |
          r() { if eval "$2"; then echo "$1 ok"; else echo "$1 BAD"; fi >> .nvm-results; }
          true || nvm-free
          r mentions-dash 'test -n "$NPM_CONFIG_PREFIX" && test "$NPM_CONFIG_PREFIX" != "$CI_LOCAL_T_NPMG"'
      - name: Names a script under nvm/
        run: |
          r() { if eval "$2"; then echo "$1 ok"; else echo "$1 BAD"; fi >> .nvm-results; }
          true || nvm/not-run.sh
          r mentions-slash 'test -n "$NPM_CONFIG_PREFIX" && test "$NPM_CONFIG_PREFIX" != "$CI_LOCAL_T_NPMG"'
      - name: Names a script under nvm.d/
        run: |
          r() { if eval "$2"; then echo "$1 ok"; else echo "$1 BAD"; fi >> .nvm-results; }
          true || nvm.d/not-run
          r mentions-dot 'test -n "$NPM_CONFIG_PREFIX" && test "$NPM_CONFIG_PREFIX" != "$CI_LOCAL_T_NPMG"'
  fails:
    name: Nvm Fails
    runs-on: ubuntu-latest
    steps:
      - name: Uses nvm, then fails
        run: |
          export NVM_DIR="$PWD/nvm-stub"
          . "$NVM_DIR/nvm.sh"
          echo "nvm step output"
          exit 3
  indirect:
    name: Nvm Indirect
    runs-on: ubuntu-latest
    steps:
      - name: Runs a script that loads nvm, with no -e
        run: ./tools/use-node.sh | tee -a .nvm-indirect
      - name: Runs a script that loads nvm, with -e
        run: ./tools/use-node-e.sh >> .nvm-indirect
      - name: Evals its nvm command
        run: |
          export NVM_DIR="$PWD/nvm-bare"
          . "$CI_LOCAL_T_NVM_LOAD"
          eval "nvm use 22" > /dev/null
          echo "eval node=${CI_LOCAL_T_NODE:-host}" >> .nvm-indirect
      - name: Reads what the script with no -e left for it
        run: |
          p=""; for n in host stub; do case ":$PATH:" in *":$PWD/seen-$n:"*) p="$p $n" ;; esac; done
          echo "env host=${NODE_SEEN_host:-unset} stub=${NODE_SEEN_stub:-unset}, path:${p:- none}" > .nvm-indirect-left
  own:
    name: Nvm Own Prefix
    runs-on: ubuntu-latest
    steps:
      - name: Exports a prefix of its own, then loads nvm
        run: NPM_CONFIG_PREFIX="$PWD/own-prefix" ./tools/use-node-e.sh
  slow:
    name: Nvm Slow
    runs-on: ubuntu-latest
    steps:
      - name: Sources nvm.sh, then hangs
        run: |
          export NVM_DIR="$PWD/nvm-stub"
          . "$NVM_DIR/nvm.sh"
          exec sleep 30
  slow_refused:
    name: Nvm Slow Refused
    runs-on: ubuntu-latest
    steps:
      - name: Evals its nvm command, then hangs
        run: |
          export NVM_DIR="$PWD/nvm-bare"
          . "$CI_LOCAL_T_NVM_LOAD"
          eval "nvm use 22" || true
          exec sleep 30
YAML
# Each place a command starts that the step text match names, one step each,
# with nothing else in the step that could match.
NVM_POS_NAMES=()
{
  printf '  positions:\n    name: Nvm Positions\n    runs-on: ubuntu-latest\n    steps:\n'
  while IFS='~' read -r label cmd; do
    NVM_POS_NAMES+=("Runs nvm $label")
    printf '      - name: Runs nvm %s\n        run: |\n          export NVM_DIR="$PWD/nvm-bare"\n          . "$CI_LOCAL_T_NVM_LOAD"\n          %s\n          true\n' "$label" "$cmd"
  done <<'POS'
after a semicolon~true; nvm use 22
after and-and~true && nvm use 22
after or-or~false || nvm use 22
in a command substitution~v=$(nvm current)
in backticks~v=`nvm current`
in a brace group~{ nvm use 22; }
after a bang~! nvm use 22
after then~if true; then nvm use 22; fi
after do~for v in 22; do nvm use "$v"; done
after else~if false; then :; else nvm use 22; fi
after elif~if false; then :; elif nvm use 22; then :; fi
after if~if nvm use 22; then :; fi
after while~while nvm use 22; do break; done
after until~until nvm use 22 || :; do :; done
after time~time nvm use 22
after command~true || command nvm use 22
POS
} >> "$NVMW/.github/workflows/nvm.yml"
# A caller with no PATH at all (`env -u PATH`, as from cron or `env -i`).
NOPATH="$SANDBOX/npm-nopath"; mkdir -p "$NOPATH/.github/workflows"
cat > "$NOPATH/.github/workflows/p.yml" <<'YAML'
name: No Path
on: [push, pull_request]
jobs:
  p:
    name: No Path
    runs-on: ubuntu-latest
    steps:
      - name: Records its PATH
        run: printf '%s\n' "${PATH-UNSET}" > .path-seen
YAML

# A git checkout: whether HEAD carries a tag decides the tag tier.
TAGS="$SANDBOX/tags"; mkdir -p "$TAGS/.github/workflows"
cat > "$TAGS/.github/workflows/release.yml" <<'YAML'
name: Release
on:
  push:
    tags: ["v*"]
  workflow_dispatch:
jobs:
  release:
    name: Tag Release
    runs-on: ubuntu-latest
    steps:
      - name: Only on a tag
        run: touch .tag-release-ran
YAML
cat > "$TAGS/.github/workflows/block.yml" <<'YAML'
name: Block Tags
on:
  push:
    tags:
      - "v*"   # a release
  schedule:
    - cron: "0 3 * * 1"
jobs:
  block:
    name: Block Tag Tier
    runs-on: ubuntu-latest
    steps:
      - name: Block style
        run: touch .block-tag-ran
YAML
cat > "$TAGS/.github/workflows/flow.yml" <<'YAML'
name: Flow Tags
on: {push: {tags-ignore: [nightly*]}, release: {types: [published]}}
jobs:
  flow:
    name: Flow Tag Tier
    runs-on: ubuntu-latest
    steps:
      - name: Flow style, tags-ignore
        run: touch .flow-tag-ran
YAML
cat > "$TAGS/.github/workflows/branches.yml" <<'YAML'
name: Branches
on:
  push:
    branches: [main]
    tags: ["v*"]
jobs:
  branches:
    name: Branches And Tags
    runs-on: ubuntu-latest
    steps:
      - name: A branch push starts it
        run: touch .branches-ran
YAML
cat > "$TAGS/.github/workflows/pr.yml" <<'YAML'
name: PR
on: {push: {tags: [v*]}, pull_request: {}}
jobs:
  pr:
    name: Tags And PRs
    runs-on: ubuntu-latest
    steps:
      - name: A pull request starts it
        run: touch .tags-pr-ran
YAML
cat > "$TAGS/.github/workflows/called.yml" <<'YAML'
name: Called
on:
  push:
    tags: ["v*"]
  workflow_call:
jobs:
  called:
    name: Tags And Call
    runs-on: ubuntu-latest
    steps:
      - name: A caller on any push may start it
        run: touch .tags-call-ran
YAML
printf '.*-ran\n' > "$TAGS/.gitignore"
git -C "$TAGS" init -q && git -C "$TAGS" add -A \
  && git -C "$TAGS" -c user.name=t -c user.email=t@example.invalid -c commit.gpgsign=false commit -q -m base

# ─── Runner labels ───────────────────────────────────────────────────
section "runner labels match case-insensitively: a self-hosted macOS job is a platform skip"
OUT="$(python3 "$RUNNER" --repo "$LABELS" --list 2>&1)"
lafter() { grep -A1 -F -- "] $1 " <<< "$OUT"; }
assert_contains "$(lafter 'Self-hosted Mac')" "needs Darwin; this machine is Linux" \
  "[self-hosted, macOS, macserver-public] needs Darwin, as the label macOS says"
assert_contains "$(lafter 'Block List')" "needs Darwin" "a block list below runs-on: is read (- MacOS)"
assert_contains "$(lafter 'Group Labels')" "needs Darwin" "a group mapping's labels: list is read, its group is not a label"
assert_contains "$(lafter 'Flow Group')" "needs Windows" "a flow mapping {group, labels: [...]} is read"
assert_contains "$(lafter 'Hosted Upper')" "needs Darwin" "an upper-case hosted image (MACOS-15) is macOS"
assert_contains "$(lafter 'Other Arch')" "needs $RL_OTHER_ARCH; this machine is $RL_HERE_ARCH" \
  "an architecture label for another CPU is a platform skip"
for j in 'Self-hosted Linux' 'Same Arch' 'Commented'; do
  assert_contains "$(lafter "$j")" "[run ] $j" "$j runs here"
done
assert_lacks "$OUT" "UNPROVEN" "a platform skip is reasoned, never an unproven lane"
rm -f "$LABELS"/.*-ran
OUT="$(python3 "$RUNNER" --repo "$LABELS" 2>&1)"; RC=$?
assert_eq "$RC" "0" "the label fixture passes"
assert_contains "$OUT" "ci-local: 3/3 job(s) passed" "exactly the three jobs for this platform ran, and the verdict is green"
for m in self-mac block-list group-labels flow-group hosted-upper other-arch; do
  if [[ -e "$LABELS/.$m-ran" ]]; then fail "the .$m-ran job did not execute on the wrong platform" "it ran"
  else pass "the .$m-ran job did not execute on the wrong platform"; fi
done
# Round 1 ran `--job "Release-script tests"`: a named job is still planned in full.
OUT="$(python3 "$RUNNER" --repo "$LABELS" --job "Self-hosted Mac" 2>&1)"
assert_contains "$OUT" "skipped Self-hosted Mac: needs Darwin" "--job on a self-hosted macOS job skips it on Linux"
if [[ -e "$LABELS/.self-mac-ran" ]]; then fail "--job did not run the macOS job's steps here" "it ran"
else pass "--job did not run the macOS job's steps here"; fi

# ─── The files every step gets ───────────────────────────────────────
section "each job gets RUNNER_TEMP, GITHUB_WORKSPACE and the command files a runner gives"
files_reset() { rm -f "$FILES"/.files-results "$FILES"/.*-ran; }
result() { grep -E "^$1 (ok|BAD)$" "$FILES/.files-results" 2>/dev/null | tr '\n' ' ' | sed 's/ $//'; }
files_reset
# The outer job's files, as a hosted job running this suite has them: a step
# must write to its own, never to these. A private TMPDIR, so the check that
# the per-job directories are gone afterwards sees no one else's run.
: > "$SANDBOX/outer-env"; : > "$SANDBOX/outer-path"; : > "$SANDBOX/outer-output"; : > "$SANDBOX/outer-state"
RL_TMP="$SANDBOX/files-tmp"; mkdir -p "$RL_TMP"
OUT="$(GITHUB_ENV="$SANDBOX/outer-env" GITHUB_PATH="$SANDBOX/outer-path" GITHUB_OUTPUT="$SANDBOX/outer-output" \
  GITHUB_STATE="$SANDBOX/outer-state" RUNNER_TEMP="$SANDBOX" TMPDIR="$RL_TMP" \
  python3 "$RUNNER" --repo "$FILES" --job "Runner Files" --job "Next Job" 2>&1)"; RC=$?
assert_eq "$RC" "0" "a job that writes \$GITHUB_PATH, \$GITHUB_ENV and \$GITHUB_OUTPUT passes"
assert_lacks "$OUT" "FLAKY" "on its first attempt"
for k in temp-empty temp-outside workspace writer-unset; do
  assert_eq "$(result "$k")" "$k ok" "writer: $k"
done
assert_eq "$(result env)" "env ok" "a \$GITHUB_ENV value reaches the next step"
assert_eq "$(result env-over-job)" "env-over-job ok" "\$GITHUB_ENV outranks the job's env:, as on the runner"
assert_eq "$(result own-over-env)" "own-over-env ok" "the step's own env: outranks \$GITHUB_ENV"
assert_eq "$(result heredoc)" "heredoc ok" "a NAME<<DELIMITER value keeps its lines"
assert_eq "$(result path)" "path ok" "a \$GITHUB_PATH entry is on the next step's PATH"
for k in job-env job-path job-temp; do
  assert_eq "$(result "$k")" "$k ok" "the next job sees none of it: $k"
done
for f in outer-env outer-path outer-output outer-state; do
  if [[ -s "$SANDBOX/$f" ]]; then fail "a step did not write the outer job's $f" "$(head -3 "$SANDBOX/$f")"
  else pass "a step did not write the outer job's $f"; fi
done
assert_contains "$OUT" "unproven Runner Files › Reads an output" \
  "steps.<id>.outputs is still unproven: the output is written, never read"
if [[ -e "$FILES/.output-read-ran" ]]; then fail "the output-reading step did not run" "it ran"
else pass "the output-reading step did not run"; fi
RL_LEFT="$(cd "$RL_TMP" && ls -d ci-local-job-* 2>/dev/null)"
assert_eq "$RL_LEFT" "" "the per-job directories are removed after the run"

section "a \$GITHUB_ENV the runner cannot read fails the step that wrote it"
files_reset
OUT="$(python3 "$RUNNER" --repo "$FILES" --job "Bad Env File" 2>&1)"; RC=$?
assert_eq "$RC" "1" "a line with neither = nor << fails the run"
assert_contains "$OUT" "FAILED  Bad Env File" "the job is named"
assert_contains "$OUT" "\$GITHUB_ENV: invalid format 'NO_EQUALS_SIGN'" "the failure says why, in the runner's terms"
if [[ -e "$FILES/.after-bad-env-ran" ]]; then fail "the job stops at that step" "the next step ran"
else pass "the job stops at that step"; fi
CHECK=$(check_json "$(python3 "$RUNNER" --repo "$FILES" --job "Open Heredoc" --json 2>/dev/null)" '
f = (d.get("failed") or [{}])[0]
if d.get("verdict") != "fail" or "matching delimiter not found" not in f.get("reason", ""):
    problems.append("verdict=%r failed=%r" % (d.get("verdict"), d.get("failed")))
if f.get("first_exit") is not None:
    problems.append("rerun: first_exit=%r" % f.get("first_exit"))
')
assert_eq "$CHECK" "ok" "JSON: a heredoc with no closing delimiter fails, with the reason, and is not rerun"

# ─── npm's global prefix ─────────────────────────────────────────────
section "each job gets an npm global prefix of its own, never the host's"
npm_result() { grep -E "^$1 (ok|BAD)$" "$NPMW/.npm-results" 2>/dev/null | tr '\n' ' ' | sed 's/ $//'; }
rm -f "$NPMW"/.npm-*
OUT="$(npm_caller python3 "$RUNNER" --repo "$NPMW" 2>&1)"; RC=$?
assert_eq "$RC" "0" "a job that installs into its npm prefix passes"
assert_lacks "$OUT" "FLAKY" "on its first attempt"
assert_contains "$OUT" "unproven Npm Expression Prefix › Its prefix only the hosted run can set" \
  "the step whose prefix is a \${{ }} still reads unproven"
for k in one-spelling not-callers empty outside root-on-path bin-first; do
  assert_eq "$(npm_result "$k")" "$k ok" "npm prefix: $k"
done
assert_eq "$(npm_result same-prefix)" "same-prefix ok" "the prefix is the job's: the next step has the same one"
assert_eq "$(npm_result installed-earlier)" "installed-earlier ok" "what a step installs, a later step runs"
for k in lower-one-spelling lower-wins; do
  assert_eq "$(npm_result "$k")" "$k ok" "a step's own lower-case npm_config_prefix wins, the only spelling: $k"
done
assert_eq "$(npm_result workflow-wins)" "workflow-wins ok" "a step's own NPM_CONFIG_PREFIX still wins, as on a runner"
assert_eq "$(npm_result env-file-wins)" "env-file-wins ok" "so does one a step wrote to \$GITHUB_ENV"
for k in expr-own expr-one-spelling; do
  assert_eq "$(npm_result "$k")" "$k ok" "a \${{ }} prefix, unset here, falls back to the job's, not the host's: $k"
done
for k in next-job-own next-job-empty host-bins-kept; do
  assert_eq "$(npm_result "$k")" "$k ok" "the next job starts from an empty prefix: $k"
done
NPM_FIRST="$(cat "$NPMW/.npm-prefix-first" 2>/dev/null)"
if [[ -n "$NPM_FIRST" && ! -e "$NPM_FIRST" ]]; then pass "the job's npm prefix is removed after the run"
else fail "the job's npm prefix is removed after the run" "'$NPM_FIRST' is still there"; fi

NP_DEF="$(python3 -c 'import os; print(os.defpath)')"
rm -f "$NOPATH/.path-seen"
OUT="$(env -u PATH "$(command -v python3)" "$RUNNER" --repo "$NOPATH" 2>&1)"; RC=$?
NP_SEEN="$(cat "$NOPATH/.path-seen" 2>/dev/null)"
# Exactly <prefix>/bin, <prefix>, then exec's default: no empty entry.
NP_RE="^(/[^:]+)/npm-prefix/bin:(/[^:]+)/npm-prefix:${NP_DEF}\$"
if [[ "$RC" == 0 && "$NP_SEEN" =~ $NP_RE && "${BASH_REMATCH[1]}" == "${BASH_REMATCH[2]}" ]]; then
  pass "a caller with no PATH: the step finds bash, its PATH is the prefix's bins, then os.defpath"
else fail "a caller with no PATH: the step finds bash, its PATH is the prefix's bins, then os.defpath" \
  "rc=$RC PATH '$NP_SEEN': $(echo "$OUT" | tail -2 | tr '\n' ' ')"; fi

section "a step that uses nvm runs without the prefix nvm refuses, and its output says so"
nvm_result() { grep -E "^$1 (ok|BAD)$" "$NVMW/.nvm-results" 2>/dev/null | tr '\n' ' ' | sed 's/ $//'; }
NVM_WHY="runs without the job's npm prefix: it uses nvm, which refuses NPM_CONFIG_PREFIX, so its global installs go wherever nvm puts them, on this host"
NVM_REFUSED="ran again without the job's npm prefix: nvm refused NPM_CONFIG_PREFIX in its output (exit {}), so its global installs go wherever nvm puts them, on this host"
nvm_caller() { CI_LOCAL_T_NVM_LOAD="$NVMW/nvm-stub/nvm.sh" npm_caller "$@"; }
rm -f "$NVMW"/.nvm-*
OUT="$(nvm_caller python3 "$RUNNER" --repo "$NVMW" \
  --job "Nvm Sources" --job "Nvm By Name" --job "Nvm Mentions Only" --job "Nvm Positions" 2>&1)"; RC=$?
assert_eq "$RC" "0" "steps that use nvm pass: no prefix is left for nvm to refuse, the caller's included"
assert_lacks "$OUT" "FLAKY" "on their first attempt"
assert_eq "$(nvm_result sourced-ran)" "sourced-ran ok" "a step that sources nvm.sh gets past it (with the prefix nvm would exit 11)"
assert_eq "$(nvm_result sourced-no-prefix)" "sourced-no-prefix ok" \
  "it sees no npm_config_prefix in any spelling, the caller's included"
assert_eq "$(nvm_result sourced-bins-on-path)" "sourced-bins-on-path ok" "the job's prefix bins are still on its PATH"
assert_eq "$(nvm_result by-name-ran)" "by-name-ran ok" "a step that runs nvm by name, no nvm.sh in its text, gets past nvm use"
assert_eq "$(nvm_result mentions-own)" "mentions-own ok" \
  "a step that only mentions nvm (a comment, ~/.nvm, NVM_DIR, a variable nvm_x) keeps the job's prefix"
for s in "Sources nvm.sh and nothing else" "Loads nvm under another name and runs it"; do
  assert_eq "$(grep -cxF "    ci-local: step \"$s\" $NVM_WHY" <<< "$OUT")" "1" "one line in the run's output names the step: $s"
done
assert_lacks "$OUT" "step \"Mentions nvm without using it\" runs without" "the step that only mentions nvm gets no such line"
for k in mentions-assign mentions-dash mentions-slash mentions-dot; do
  assert_eq "$(nvm_result "$k")" "$k ok" "nvm where a command starts, then one of = - / . is not nvm: the step keeps the prefix ($k)"
done
# Every place a command starts is found from the text: the note comes before
# the step, which runs once and never again after nvm's refusal.
for s in "${NVM_POS_NAMES[@]}"; do
  assert_eq "$(grep -cxF "    ci-local: step \"$s\" $NVM_WHY" <<< "$OUT")" "1" "found from its text: $s"
done
assert_eq "$(grep -c "^    ci-local: step .* runs without the job's npm prefix" <<< "$OUT")" "$((2 + ${#NVM_POS_NAMES[@]}))" \
  "no other step of those jobs gets a note"
assert_lacks "$OUT" "nvm refused the job's npm prefix" "none of them ran a second time"
# The shape a review found (2026-11-25): no prefix in the caller's environment,
# green on main, exit 11 once every step was handed the job's.
env -u NPM_CONFIG_PREFIX -u npm_config_prefix python3 "$RUNNER" --repo "$NVMW" --job "Nvm Sources" \
  > /dev/null 2>&1; RC=$?
assert_eq "$RC" "0" "with no prefix in the caller's environment either, a step that sources nvm.sh passes"
# The first attempt's tail (--no-rerun), then the rerun's: each is a step's output.
for mode in --no-rerun rerun; do
  if [[ "$mode" == --no-rerun ]]; then
    OUT="$(npm_caller python3 "$RUNNER" --repo "$NVMW" --job "Nvm Fails" --json --no-rerun 2>/dev/null)"
  else OUT="$(npm_caller python3 "$RUNNER" --repo "$NVMW" --job "Nvm Fails" --json 2>/dev/null)"; fi
  CHECK=$(CL_NVM_WANT="ci-local: step \"Uses nvm, then fails\" $NVM_WHY" check_json "$OUT" '
import os
fs = d.get("failed") or [{}]
tail = fs[0].get("output_tail", "").splitlines()
if fs[0].get("exit_code") != 3 or tail[:1] != [os.environ["CL_NVM_WANT"]] or "nvm step output" not in tail:
    problems.append("failed=%r" % fs)
')
  assert_eq "$CHECK" "ok" "JSON ($mode): a failed nvm step's output tail opens with that line, then its own output"
done
# nvm loaded where the text does not show it (the review's shapes, 2026-11-25):
# with no -e the step passed on another node, with -e or eval it exited 11.
rm -f "$NVMW/.nvm-indirect" "$NVMW/.nvm-indirect-left"
OUT="$(nvm_caller python3 "$RUNNER" --repo "$NVMW" --job "Nvm Indirect" 2>&1)"; RC=$?
assert_eq "$RC" "0" "steps that load nvm out of sight pass: nvm's refusal of the job's prefix ran each again without it"
assert_lacks "$OUT" "FLAKY" "running again after nvm's refusal is not a flake rerun"
assert_eq "$(tr '\n' ' ' < "$NVMW/.nvm-indirect" 2>/dev/null)" \
  "script node=host script node=stub script-e node=stub eval node=stub " \
  "each ends on nvm's node, run once more; the one with no -e had passed on another"
assert_eq "$(cat "$NVMW/.nvm-indirect-left" 2>/dev/null)" "env host=unset stub=1, path: stub" \
  "the discarded attempt's \$GITHUB_ENV and \$GITHUB_PATH writes are dropped: a later step sees only the run again's"
for x in "Runs a script that loads nvm, with no -e~0" "Runs a script that loads nvm, with -e~11" \
         "Evals its nvm command~11"; do
  s="${x%~*}"; n="${x##*~}"
  assert_eq "$(grep -cF "· $s … nvm refused the job's npm prefix (exit $n), running it again without it … ok (" <<< "$OUT")" \
    "1" "its line in the run's output says so: $s"
done
# --no-rerun leaves this alone: the first attempt ran in an environment the
# step cannot use, which is not a failure to report.
OUT="$(nvm_caller python3 "$RUNNER" --repo "$NVMW" --job "Nvm Sources" --job "Nvm Indirect" \
  --job "Nvm Fails" --json --no-rerun 2>/dev/null)"
CHECK=$(CL_WHY="$NVM_WHY" CL_REF="$NVM_REFUSED" check_json "$OUT" '
import os
why, ref = os.environ["CL_WHY"], os.environ["CL_REF"]
want = sorted([("Nvm Sources", "Sources nvm.sh and nothing else", why),
               ("Nvm Indirect", "Runs a script that loads nvm, with no -e", ref.format(0)),
               ("Nvm Indirect", "Runs a script that loads nvm, with -e", ref.format(11)),
               ("Nvm Indirect", "Evals its nvm command", ref.format(11)),
               ("Nvm Fails", "Uses nvm, then fails", why)])
got = sorted((e.get("job"), e.get("step"), e.get("why")) for e in d.get("no_npm_prefix") or [{}])
if got != want or "Nvm Indirect" not in d.get("passed", []):
    problems.append("no_npm_prefix=%r passed=%r" % (d.get("no_npm_prefix"), d.get("passed")))
')
assert_eq "$CHECK" "ok" "JSON: no_npm_prefix names each step without the prefix and why, passed or failed, under --no-rerun too"
OUT="$(nvm_caller python3 "$RUNNER" --repo "$NVMW" --job "Nvm Own Prefix" --json --no-rerun 2>/dev/null)"
CHECK=$(check_json "$OUT" '
fs = d.get("failed") or [{}]
tail = fs[0].get("output_tail", "")
if (fs[0].get("exit_code") != 11 or "/own-prefix\"" not in tail or "ci-local: step" in tail
        or d.get("no_npm_prefix") != []):
    problems.append("failed=%r no_npm_prefix=%r" % (fs, d.get("no_npm_prefix")))
')
assert_eq "$CHECK" "ok" "a prefix the step's own script exports is nvm's to refuse, as on a runner: exit 11, not run again"
OUT="$(nvm_caller python3 "$RUNNER" --repo "$NVMW" --job "Nvm Slow" --job "Nvm Slow Refused" \
  --json --timeout 2 2>/dev/null)"
CHECK=$(CL_WHY="$NVM_WHY" check_json "$OUT" '
import os
got = [(e.get("job"), e.get("why")) for e in d.get("no_npm_prefix") or []]
if ("Nvm Slow", os.environ["CL_WHY"]) not in got:
    problems.append("no_npm_prefix=%r" % d.get("no_npm_prefix"))
')
assert_eq "$CHECK" "ok" "JSON: a step that uses nvm and times out is in no_npm_prefix too"
CHECK=$(check_json "$OUT" '
slow = {f.get("job"): f for f in d.get("failed", [])}.get("Nvm Slow Refused", {})
if ("exceeded the 2s step timeout" not in slow.get("reason", "")
        or "nvm is not compatible" not in slow.get("output_tail", "")
        or any(e.get("job") == "Nvm Slow Refused" for e in d.get("no_npm_prefix") or [])):
    problems.append("failed=%r no_npm_prefix=%r" % (slow, d.get("no_npm_prefix")))
')
assert_eq "$CHECK" "ok" "nvm's refusal in a step that then timed out does not run it again"

section "two gates at once, each running npm install -g: both pass, the host prefix is untouched"
if command -v npm >/dev/null 2>&1; then
  NPM_BEFORE="$(npm_manifest "$NPMG")"
  rm -f "$SANDBOX"/npm-[ab]/.npm-*
  npm_caller python3 "$RUNNER" --repo "$SANDBOX/npm-a" --json > "$SANDBOX/npm-a.json" 2>/dev/null &
  NPM_PID_A=$!
  npm_caller python3 "$RUNNER" --repo "$SANDBOX/npm-b" --json > "$SANDBOX/npm-b.json" 2>/dev/null &
  NPM_PID_B=$!
  wait "$NPM_PID_A"; NPM_RC_A=$?
  wait "$NPM_PID_B"; NPM_RC_B=$?
  assert_eq "$NPM_RC_A $NPM_RC_B" "0 0" "both concurrent runs exit 0"
  for c in a b; do
    CHECK=$(check_json "$(cat "$SANDBOX/npm-$c.json")" '
if d.get("verdict") != "pass" or d.get("passed") != ["Npm Install"]:
    problems.append("verdict=%r passed=%r failed=%r flaky=%r" % (d.get("verdict"), d.get("passed"),
                    [f.get("output_tail", "")[-300:] for f in d.get("failed", [])], d.get("flaky")))
')
    assert_eq "$CHECK" "ok" "gate $c: verdict pass on the first attempt, not flaky"
    assert_eq "$(cat "$SANDBOX/npm-$c/.npm-hello" 2>/dev/null)" "hello-from-ci-local-t-pkg" \
      "gate $c: the installed bin runs, not the host's decoy"
    NPM_P="$(cat "$SANDBOX/npm-$c/.npm-global-prefix" 2>/dev/null)"
    assert_eq "$(cat "$SANDBOX/npm-$c/.npm-hello-path" 2>/dev/null)" "$NPM_P/bin/ci-local-t-hello" \
      "gate $c: the bin resolves from the prefix npm installed it into"
    if [[ -n "$NPM_P" && "$NPM_P" != "$NPMG" && ! -e "$NPM_P" ]]; then
      pass "gate $c: that prefix was its own, and is removed after the run"
    else fail "gate $c: that prefix was its own, and is removed after the run" "prefix '$NPM_P'"; fi
  done
  if [[ "$(cat "$SANDBOX/npm-a/.npm-global-prefix" 2>/dev/null)" != "$(cat "$SANDBOX/npm-b/.npm-global-prefix" 2>/dev/null)" ]]; then
    pass "the two gates installed into different prefixes"
  else fail "the two gates installed into different prefixes" "both used one"; fi
  NPM_AFTER="$(npm_manifest "$NPMG")"
  if [[ "$NPM_AFTER" == "$NPM_BEFORE" ]]; then
    pass "the host's global prefix is unchanged: every entry, mtime and size"
  else fail "the host's global prefix is unchanged: every entry, mtime and size" \
    "$(diff <(echo "$NPM_BEFORE") <(echo "$NPM_AFTER") | head -6 | tr '\n' ' ')"; fi
else
  echo -e "  ${YELLOW}-${NC} not run: npm is not on PATH, so no real npm install -g was gated (the env cases above still ran)"
fi

# ─── Tag-only tiers ──────────────────────────────────────────────────
section "a workflow only a tag push starts is a tag tier: skipped on a head with no tag"
tags_reset() { rm -f "$TAGS"/.*-ran; }
tag_ran() { [[ -e "$TAGS/.$1-ran" ]]; }
OUT="$(python3 "$RUNNER" --repo "$TAGS" --list 2>&1)"
tafter() { grep -A1 -F -- "] $1 " <<< "$OUT"; }
assert_contains "$(tafter 'Tag Release')" 'tag-only tier — push fires on tags: ["v*"] alone' \
  "push: tags: [v*] plus workflow_dispatch is a tag tier, and says its filter"
assert_contains "$(tafter 'Block Tag Tier')" "tag-only tier" "block style, a commented tag list, beside a schedule"
assert_contains "$(tafter 'Flow Tag Tier')" "tag-only tier — push fires on tags-ignore" \
  "flow style; tags-ignore alone also starts it only for tags; beside release"
for j in 'Branches And Tags' 'Tags And PRs' 'Tags And Call'; do
  assert_contains "$(tafter "$j")" "[run ] $j" "$j still runs: a branch push, a PR or a caller starts it"
done
assert_lacks "$OUT" "UNPROVEN" "a tag tier is reasoned, never an unproven lane"
tags_reset
CHECK=$(check_json "$(python3 "$RUNNER" --repo "$TAGS" --json 2>/dev/null)" '
if d.get("verdict") != "pass":
    problems.append("verdict=%r" % d.get("verdict"))
skipped = {s["job"]: s["unproven"] for s in d.get("skipped", [])}
if skipped != {"Tag Release": False, "Block Tag Tier": False, "Flow Tag Tier": False}:
    problems.append("skipped=%r" % skipped)
if sorted(d.get("passed", [])) != ["Branches And Tags", "Tags And Call", "Tags And PRs"]:
    problems.append("passed=%r" % d.get("passed"))
')
assert_eq "$CHECK" "ok" "JSON: verdict pass, the three tag tiers skipped and not unproven"
for m in tag-release block-tag flow-tag; do
  if tag_ran "$m"; then fail "the .$m-ran tag tier did not execute on a branch head" "it ran"
  else pass "the .$m-ran tag tier did not execute on a branch head"; fi
done
for m in branches tags-pr tags-call; do
  if tag_ran "$m"; then pass "the .$m-ran workflow executed"
  else fail "the .$m-ran workflow executed" "the marker is missing"; fi
done

section "a tag tier runs on a tagged head, with --all, or when named"
tags_reset
OUT="$(python3 "$RUNNER" --repo "$TAGS" --all 2>&1)"
assert_contains "$OUT" "--all also runs these normally-skipped jobs:" "--all announces what it adds"
assert_contains "$OUT" "· Tag Release" "and names the tag tier among them"
if tag_ran tag-release; then pass "--all runs the tag tier"; else fail "--all runs the tag tier" "it did not run"; fi
tags_reset
python3 "$RUNNER" --repo "$TAGS" --job "Flow Tag Tier" >/dev/null 2>&1
if tag_ran flow-tag; then pass "--job runs a named tag-tier job"; else fail "--job runs a named tag-tier job" "it did not run"; fi
tags_reset
git -C "$TAGS" tag v1.0.0
OUT="$(python3 "$RUNNER" --repo "$TAGS" 2>&1)"
assert_lacks "$OUT" "tag-only tier" "on a head that carries a tag, nothing is skipped as a tag tier"
if tag_ran tag-release && tag_ran block-tag; then pass "a tagged head runs the tag tiers, as its tag push would"
else fail "a tagged head runs the tag tiers, as its tag push would" "a marker is missing"; fi
OUT="$(python3 "$RUNNER" --repo "$TAGS" --all --job "Tag Release" 2>&1)"
assert_lacks "$OUT" "· Tag Release" "--all on a tagged head does not announce the tag tier: it would run anyway"
git -C "$TAGS" tag -d v1.0.0 >/dev/null

# ─── Mutations ───────────────────────────────────────────────────────
# Called from the suite's mutation table, where `mutation` is defined. Each
# anchor matches ci-local.py or ci_local_runner.py exactly once.
ci_local_runner_mutations() {
  # Runner labels.
  mutation red "the platform check at its call site in skip_reason" \
    'need = runner.platform_need(job.runs_on, local_platform(), platform.machine())' 'need = None'
  mutation red "labels compared case-insensitively" \
    'labels = [lb.lower() for lb in runs_on_labels(runs_on)]' 'labels = runs_on_labels(runs_on)'
  mutation red "an architecture label naming a platform" \
    'if arches and here not in arches:' 'if False:'
  mutation red "a bare runs-on: collecting the labels below it" \
    'job_block = key if key in ("env", "defaults", "runs-on") and bare else ""' \
    'job_block = key if key in ("env", "defaults") and bare else ""'
  mutation red "a flow mapping's labels: being the labels" \
    'labels += [lb for k, v in flow_items(line) if k == "labels" for lb in flow_names(v)]' \
    'labels += flow_names(line)'
  mutation red "a comment after runs-on: not being a label" \
    'line = _uncomment(raw).strip()' 'line = raw.strip()'
  # The files every step gets.
  mutation red "the runner files reaching a step (call site)" \
    'rc, elapsed, out, timed_out = runner.attempt(step.run, cwd, {**env, **files.begin_step()},' \
    'rc, elapsed, out, timed_out = runner.attempt(step.run, cwd, env,'
  mutation red "a \$GITHUB_ENV write reaching later steps" \
    'env.update(files.env)' 'env.update({})'
  mutation red "\$GITHUB_ENV outranking workflow and job env" \
    '            if key in step.inherited and key in files.env:
                continue
' ''
  mutation red "the step's own env outranking \$GITHUB_ENV" \
    'if key in step.inherited and key in files.env:' 'if key in files.env:'
  mutation red "a \$GITHUB_PATH entry reaching later steps" \
    'env["PATH"] = os.pathsep.join(files.path + [env.get("PATH", "")])' \
    'env["PATH"] = env.get("PATH", "")'
  mutation red "a heredoc value in \$GITHUB_ENV" 'elif here > 0:' 'elif False:'
  mutation red "an unreadable \$GITHUB_ENV failing its step" \
    '        if bad_files:
            rc, tail = 1,' '        if False:
            rc, tail = 1,'
  mutation red "runner files kept per job" \
    'files = runner.JobFiles(repo)' 'files = getattr(run_job, "files", None) or runner.JobFiles(repo)
    run_job.files = files' \
    '    files.close()
' ''
  mutation red "GITHUB_WORKSPACE given to a step" \
    '"GITHUB_WORKSPACE": str(self.workspace)}' '}'
  mutation red "a step's own \$GITHUB_STATE, not the outer job's" \
    '"GITHUB_STEP_SUMMARY": "step_summary", "GITHUB_STATE": "save_state"}' \
    '"GITHUB_STEP_SUMMARY": "step_summary"}'
  # npm's global prefix.
  mutation red "the job's npm prefix at its call site in run_job" \
    '        why = runner.isolate_npm_global(env, files.npm_prefix, [
            *files.env, *(k for k, v in step.env.items() if not _EXPR.search(v))], step.run)
' '        why = ""
'
  mutation red "the caller's other spellings of npm_config_prefix being dropped" \
    '    for key in [k for k in env if k.lower() == "npm_config_prefix" and k not in named]:
        del env[key]
' ''
  mutation red "NPM_CONFIG_PREFIX naming the job's prefix" \
    'env["NPM_CONFIG_PREFIX"] = str(prefix)' 'pass'
  mutation red "the prefix's bin directory first on PATH" \
    '[str(prefix / "bin"), str(prefix), env.get' '[str(prefix), env.get'
  mutation red "the prefix itself on PATH (where Windows npm puts bins)" \
    '[str(prefix / "bin"), str(prefix), env.get' '[str(prefix / "bin"), env.get'
  # The anchor carries `for k in workflow_keys if`: the same comparison is on
  # the deletion loop too.
  mutation red "a workflow's prefix counted in any spelling (npm_config_prefix too)" \
    'for k in workflow_keys if k.lower() == "npm_config_prefix"}' \
    'for k in workflow_keys if k == "NPM_CONFIG_PREFIX"}'
  mutation red "a step's own NPM_CONFIG_PREFIX winning" \
    '*files.env, *(k for k, v in step.env.items() if not _EXPR.search(v))], step.run)' \
    '*files.env], step.run)'
  mutation red "a \$GITHUB_ENV NPM_CONFIG_PREFIX winning" \
    '*files.env, *(k for k, v in step.env.items() if not _EXPR.search(v))], step.run)' \
    '*(k for k, v in step.env.items() if not _EXPR.search(v))], step.run)'
  mutation red "a \${{ }} NPM_CONFIG_PREFIX not counting as the workflow's" \
    'step.env.items() if not _EXPR.search(v))]' 'step.env.items())]'
  mutation red "the job's npm prefix existing, empty" \
    'self.npm_prefix.mkdir()' 'pass'
  mutation red "an npm prefix per job, removed with it" \
    'self.npm_prefix = root / "npm-prefix"
        self.npm_prefix.mkdir()' \
    'self.npm_prefix = Path(os.environ["XDG_CACHE_HOME"]) / "ci-local-t-npm-shared"
        self.npm_prefix.mkdir(parents=True, exist_ok=True)'
  mutation red "a caller with no PATH getting os.defpath after the prefix" \
    'env.get("PATH") or os.defpath' 'env.get("PATH", "")'
  # nvm steps.
  mutation red "the step's text reaching the nvm check at its call site" \
    '*files.env, *(k for k, v in step.env.items() if not _EXPR.search(v))], step.run)' \
    '*files.env, *(k for k, v in step.env.items() if not _EXPR.search(v))], "")'
  mutation red "nvm.sh in a step's text counting as nvm" 'r"nvm\.sh|(?:^|' 'r"(?:^|'
  mutation red "nvm run by name counting as nvm" \
    'r"nvm\.sh|(?:^|[;&|(`{!]|\b(?:then|do|else|elif|if|while|until|time|command)\s)\s*nvm(?![\w./=-])",' \
    'r"nvm\.sh",'
  mutation red "comments dropped before the nvm match" \
    '_NVM_USE.search(_SH_COMMENT.sub(r"\1", script))' '_NVM_USE.search(script)'
  mutation red "a word's end after nvm (a variable named nvm_x is not nvm)" \
    '\s*nvm(?![\w./=-])' '\s*nvm'
  # Each character after it that is not the nvm command (review, 2026-11-25:
  # `(?!\w)` alone stayed green).
  mutation red "= after nvm ending no command" 'nvm(?![\w./=-])' 'nvm(?![\w./-])'
  mutation red "- after nvm ending no command" 'nvm(?![\w./=-])' 'nvm(?![\w./=])'
  mutation red "/ after nvm ending no command" 'nvm(?![\w./=-])' 'nvm(?![\w.=-])'
  mutation red ". after nvm ending no command" 'nvm(?![\w./=-])' 'nvm(?![\w/=-])'
  # Each place a command starts, then all of them at once (the same review).
  mutation red "nvm after ; counting as nvm" '[;&|(`{!]' '[&|(`{!]'
  mutation red "nvm after & counting as nvm" '[;&|(`{!]' '[;|(`{!]'
  mutation red "nvm after | counting as nvm" '[;&|(`{!]' '[;&(`{!]'
  mutation red "nvm after ( counting as nvm" '[;&|(`{!]' '[;&|`{!]'
  mutation red "nvm after a backtick counting as nvm" '[;&|(`{!]' '[;&|({!]'
  mutation red "nvm after { counting as nvm" '[;&|(`{!]' '[;&|(`!]'
  mutation red "nvm after ! counting as nvm" '[;&|(`{!]' '[;&|(`{]'
  mutation red "nvm after any of ; & | ( \` { ! counting as nvm" '(?:^|[;&|(`{!]|' '(?:^|'
  mutation red "nvm after then counting as nvm" '(?:then|do|' '(?:do|'
  mutation red "nvm after do counting as nvm" 'then|do|else' 'then|else'
  mutation red "nvm after else counting as nvm" 'do|else|elif' 'do|elif'
  mutation red "nvm after elif counting as nvm" 'else|elif|if' 'else|if'
  mutation red "nvm after if counting as nvm" 'elif|if|while' 'elif|while'
  mutation red "nvm after while counting as nvm" 'if|while|until' 'if|until'
  mutation red "nvm after until counting as nvm" 'while|until|time' 'while|time'
  mutation red "nvm after time counting as nvm" 'until|time|command)' 'until|command)'
  mutation red "nvm after command counting as nvm" 'time|command)' 'time)'
  mutation red "nvm after any keyword counting as nvm" \
    '|\b(?:then|do|else|elif|if|while|until|time|command)\s)' ')'
  mutation red "the nvm note in the run's output" '        if why and echo:' '        if False:'
  mutation red "the nvm note opening the first attempt's output tail" \
    '        tail = runner.step_tail(note, out, tail_lines)
        first_exit' '        tail = runner.step_tail("", out, tail_lines)
        first_exit'
  mutation red "the nvm note opening the rerun's output tail" \
    '            tail = runner.step_tail(note, out, tail_lines)
' '            tail = runner.step_tail("", out, tail_lines)
'
  # nvm loaded where the step's text does not show it.
  mutation red "a step nvm refused the job's prefix running again (call site)" \
    'if not timed_out and runner.nvm_refused(out, files.npm_prefix):' 'if False:'
  mutation red "the run again on fresh runner files, the discarded attempt's writes dropped" \
    'rc, redo, out, timed_out = runner.attempt(step.run, cwd, {**env, **files.begin_step()},' \
    'rc, redo, out, timed_out = runner.attempt(step.run, cwd, {**env, **files._current, "RUNNER_TEMP": str(files.temp), "GITHUB_WORKSPACE": str(files.workspace)},'
  mutation red "the job's prefix leaving the step before it runs again" \
    '            env.pop("NPM_CONFIG_PREFIX", None)
' ''
  mutation red "why a step ran again, for its note and the JSON" \
    '            why = runner.NVM_REFUSED.format(rc)
' ''
  mutation red "the run again named on the step's line" \
    '            if echo:
                print(f"nvm refused' '            if False:
                print(f"nvm refused'
  mutation red "only nvm's refusal of the job's own prefix counting" \
    'f'"'"'currently set to "{prefix}"'"'"')' ''"'"'currently set to "'"'"')'
  mutation red "no run again after a timeout" \
    'if not timed_out and runner.nvm_refused(' 'if runner.nvm_refused('
  mutation red "no_npm_prefix naming a step that passed" \
    'first_output_tail=first_tail, npm_note=why)' 'first_output_tail=first_tail)'
  mutation red "no_npm_prefix naming a step that failed" \
    '
                output_tail=tail, first_exit=first_exit, npm_note=why,' '
                output_tail=tail, first_exit=first_exit,'
  mutation red "no_npm_prefix naming a step that timed out" \
    'command=step.run, output_tail=tail, first_exit=first_exit, npm_note=why,' \
    'command=step.run, output_tail=tail, first_exit=first_exit,'
  # Tag-only tiers.
  mutation red "the tag-tier skip at its call site in skip_reason" \
    'if job.tag_tier and not head_tags and not include_conditional:' 'if False:'
  mutation red "a branches: filter keeping a workflow off the tag tier" \
    'or filters.keys() & {"branches", "branches-ignore"}:' ':'
  mutation red "another push/PR trigger keeping a workflow off the tag tier" \
    'if not triggers - {"push"} <= _OFF_PUSH_PR:' 'if False:'
  mutation red "a tag at HEAD running the tag tier" \
    'tags = runner.head_tags(repo)' 'tags: list[str] = []'
  mutation red "--all announcing a tag tier" \
    'if r is None and j.tag_tier and not tags and j not in conditional]' 'if False]'
  mutation red "a block-style push: being read" \
    'kid_pad = min(_indent(k) for k in kids)' 'return {}'
}
