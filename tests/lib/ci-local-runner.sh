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
    'rc, elapsed, tail, timed_out = _attempt(step.run, cwd, {**env, **files.begin_step()},' \
    'rc, elapsed, tail, timed_out = _attempt(step.run, cwd, env,'
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
