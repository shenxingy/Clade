#!/usr/bin/env bash
# ci-local-host-mutation.sh — a step written for a throwaway runner is not run
# on a persistent host: the cases of tests/test-ci-local.sh that pin
# ci_local_runner.host_mutation and its call site in ci-local.py's plan_step.
#
# Sourced by that suite, never run on its own: it uses the suite's helpers
# (pass, fail, assert_*, section), its $RUNNER and $SANDBOX, check_json from
# tests/lib/ci-local-flaky.sh, and — for ci_local_host_mutation_mutations,
# called from the suite's mutation table — its `mutation` function.
#
# The incident (2026-11-25): `ci-local.py --json --job test` in a repository
# whose test job opens with a "Free up disk space" step, written for a
# GitHub-hosted VM: `sudo rm -rf /usr/share/dotnet /opt/ghc …` and
# `docker image prune -a -f`. On a host with passwordless sudo the prune
# deleted 316 GB of that host's Docker images.
#
# Every run here puts shims for sudo, docker and apt-get first on PATH. A shim
# records its own invocation and does nothing else, so a mutant whose guard is
# gone records the call instead of touching this machine.

# ─── Fixture ─────────────────────────────────────────────────────────
HM="$SANDBOX/host-mutation"; HM_SHIMS="$SANDBOX/host-mutation-shims"
HM_CALLS="$SANDBOX/host-mutation-calls.log"
mkdir -p "$HM/.github/workflows" "$HM_SHIMS"
for tool in sudo docker apt-get; do
  printf '#!/usr/bin/env bash\nprintf "%%s\\n" "%s $*" >> "%s"\n' "$tool" "$HM_CALLS" > "$HM_SHIMS/$tool"
  chmod +x "$HM_SHIMS/$tool"
done
cat > "$HM/.github/workflows/ci.yml" <<'YAML'
name: CI
on: [push, pull_request]
jobs:
  test:
    name: Test
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Free up disk space
        run: |
          sudo rm -rf /usr/share/dotnet /opt/ghc /usr/local/lib/android
          docker image prune -a -f
          df -h >/dev/null
      - name: Run tests
        run: touch .tests-ran
  gate:
    name: Gate With Prune
    runs-on: ubuntu-latest
    steps:
      - name: Tests that prune first
        run: |
          docker builder prune -af
          touch .gate-ran
      - name: After the unsafe gate
        run: touch .after-ran
YAML

hm_reset() { rm -f "$HM"/.*-ran "$HM_CALLS"; }
hm_ci() { hm_reset; PATH="$HM_SHIMS:$PATH" python3 "$RUNNER" --repo "$HM" "$@" 2>&1; }
hm_ran() { [[ -e "$HM/.$1-ran" ]]; }
hm_calls() { cat "$HM_CALLS" 2>/dev/null; }

section "a step that changes the host is skipped-unsafe, not run"
# The incident's own command line.
OUT="$(hm_ci --json --job test)"
assert_eq "$(hm_calls)" "" "the cleanup step never ran: no sudo, docker or apt-get was invoked"
if hm_ran tests; then pass "the test step after it still ran"
else fail "the test step after it still ran" "no .tests-ran marker"; fi
CHECK=$(check_json "$OUT" '
verdict, lanes, su = d.get("verdict"), d.get("unproven"), d.get("skipped_unsafe") or []
if verdict != "pass": problems.append("verdict %r, want pass: pure cleanup proves nothing less" % verdict)
if lanes: problems.append("unproven %r, want []" % lanes)
if len(su) != 1: problems.append("skipped_unsafe has %d entries, want 1" % len(su))
else:
    s = su[0]
    if s.get("step") != "Free up disk space": problems.append("step %r" % s.get("step"))
    if s.get("unproven") is not False: problems.append("a cleanup step marked unproven")
    r = s.get("reason", "")
    for want in ("skipped-unsafe: host setup or cleanup", "sudo rm -rf /usr/share/dotnet", "docker image prune -a -f", "--allow-host-mutation"):
        if want not in r: problems.append("reason lacks %r: %r" % (want, r))
')
assert_eq "$CHECK" "ok" "JSON: pass, nothing unproven, skipped_unsafe names the cleanup step and why"

OUT="$(hm_ci)"
assert_eq "$(hm_calls)" "" "a full run invokes no sudo, docker or apt-get either"
if hm_ran tests && hm_ran after; then pass "every safe step ran, the one after an unsafe gate included"
else fail "every safe step ran, the one after an unsafe gate included" "a marker is missing"; fi
if hm_ran gate; then fail "the gate step holding docker builder prune did not run" "it ran"
else pass "the gate step holding docker builder prune did not run"; fi
assert_contains "$OUT" "  Test › Free up disk space: skipped-unsafe: host setup or cleanup" \
  "the summary names the cleanup skip"
assert_contains "$OUT" "  unproven Gate With Prune › Tests that prune first: skipped-unsafe: a gate step that changes the host" \
  "a gate step with a host mutation is an unproven lane, with its reason"
assert_contains "$OUT" "ci-local: PARTIAL: 2/2 job(s) passed" "the run reads PARTIAL, not green"
assert_contains "$OUT" "1 lane(s) unproven: Gate With Prune › Tests that prune first" \
  "only the gate is unproven: the cleanup step is not a lane"
OUT="$(hm_ci --json)"
CHECK=$(check_json "$OUT" '
lanes, su = d.get("unproven") or [], d.get("skipped_unsafe") or []
if d.get("verdict") != "partial": problems.append("verdict %r" % d.get("verdict"))
if [(u.get("job"), u.get("step")) for u in lanes] != [("Gate With Prune", "Tests that prune first")]:
    problems.append("unproven %r" % lanes)
elif not lanes[0].get("reason", "").startswith("skipped-unsafe: a gate step"): problems.append("reason %r" % lanes[0].get("reason"))
if [s.get("unproven") for s in su] != [False, True]: problems.append("skipped_unsafe %r" % su)
')
assert_eq "$CHECK" "ok" "JSON: the unsafe gate is in unproven, both skips in skipped_unsafe"

OUT="$(hm_reset; PATH="$HM_SHIMS:$PATH" python3 "$RUNNER" --repo "$HM" --list 2>&1)"
assert_contains "$OUT" "↳ step Free up disk space: skipped-unsafe" "--list names the cleanup skip"
assert_contains "$OUT" "↳ UNPROVEN step Tests that prune first: skipped-unsafe" "--list names the unsafe gate as unproven"

OUT="$(hm_ci --allow-host-mutation --json)"
CALLS="$(hm_calls)"
assert_contains "$CALLS" "sudo rm -rf /usr/share/dotnet /opt/ghc /usr/local/lib/android" \
  "--allow-host-mutation runs the cleanup step (the sudo shim saw it)"
assert_contains "$CALLS" "docker image prune -a -f" "--allow-host-mutation runs the prune (the docker shim saw it)"
if hm_ran gate; then pass "--allow-host-mutation runs the gate step too"
else fail "--allow-host-mutation runs the gate step too" "no .gate-ran marker"; fi
CHECK=$(check_json "$OUT" '
if d.get("verdict") != "pass": problems.append("verdict %r" % d.get("verdict"))
if d.get("skipped_unsafe"): problems.append("skipped_unsafe %r" % d.get("skipped_unsafe"))
')
assert_eq "$CHECK" "ok" "--allow-host-mutation: nothing skipped-unsafe, verdict pass"

section "what counts as changing the host"
# EXPECT is setup (skipped, not a lane), gate (skipped, unproven) or none (run).
HM_TABLE="$SANDBOX/host-mutation-table.txt"
cat > "$HM_TABLE" <<'TABLE'
setup	sudo apt-get update && sudo apt-get install -y ffmpeg
setup	command -v shellcheck >/dev/null || sudo apt-get install -y shellcheck
setup	if [ -d /opt/hostedtoolcache ]; then sudo rm -rf /opt/hostedtoolcache; fi
setup	docker rmi $(docker images -q)
setup	docker images -q | xargs -r docker rmi -f
setup	bash -c 'docker system prune -af'
setup	apt-get autoremove -y
setup	docker volume prune -f
setup	rm -rf ~/.cache/pip
setup	echo `sudo id`
setup	/usr/bin/sudo true
gate	x="$(sudo cat /etc/hostname)"; pytest
gate	FOO=1 sudo -E make install
gate	docker builder prune -af && make test
gate	rm -rf /tmp/build-cache && pytest
gate	cd sub && apt-get purge -y foo && make
none	docker rmi myimg:tag
none	rm -rf build dist "$RUNNER_TEMP/x" "$(pwd)/z" "${GITHUB_WORKSPACE}/w"
none	echo "do not use sudo here"; pytest -q 2>&1 | tee out.log
none	echo "skip it; sudo is for hosted runners" && make test
none	pytest  # hosted only; sudo rm -rf /opt/x
none	docker build -t x . && docker run --rm x pytest
TABLE
CHECK=$(python3 - "$(dirname "$RUNNER")" "$HM_TABLE" <<'PY'
import sys
sys.dont_write_bytecode = True
sys.path.insert(0, sys.argv[1])
import ci_local_runner as r
problems = []
for line in open(sys.argv[2], encoding="utf-8").read().splitlines():
    want, script = line.split("\t", 1)
    h = r.host_mutation(script)
    got = "none" if h is None else "setup" if h.setup_only else "gate"
    if got != want:
        problems.append(f"{script!r}: {got}, want {want}")
print("; ".join(problems) or "ok")
PY
)
assert_eq "$CHECK" "ok" "22 scripts classify as setup, gate or none"

# ─── Mutations ───────────────────────────────────────────────────────
# Called from the suite's mutation table, where `mutation` is defined. Each
# anchor matches ci-local.py or ci_local_runner.py exactly once.
ci_local_host_mutation_mutations() {
  mutation red "the host-mutation check at its call site in plan_step" \
    'mutation = None if _ALLOW_HOST_MUTATION else runner.host_mutation(step.run)' 'mutation = None'
  mutation red "a gate step that changes the host being unproven" \
    'unproven=not mutation.setup_only, unsafe=True)' 'unsafe=True)'
  mutation red "a setup-only step not being a lane" \
    'unproven=not mutation.setup_only, unsafe=True)' 'unproven=True, unsafe=True)'
  mutation red "--allow-host-mutation reaching plan_step" \
    '_ALLOW_HOST_MUTATION = args.allow_host_mutation' '_ALLOW_HOST_MUTATION = False'
  mutation red "skipped_unsafe in the JSON" \
    'for r in ran for s in r.steps if s.unsafe],' 'for r in ran for s in r.steps if False],'
  mutation red "the summary naming a setup skip" \
    'for r in ran for s in r.steps if s.unsafe and not s.unproven):' 'for r in ran for s in r.steps if False):'
  mutation red "--list naming a setup skip" \
    '            elif p.unsafe:' '            elif False:'
  mutation red "sudo being found" 'by_sudo |= tool == "sudo"' 'by_sudo |= False'
  mutation red "docker prune being found" \
    'if len(words) >= 2 and words[0] in _DOCKER_PRUNE and words[1] == "prune":' 'if False:'
  mutation red "docker rmi of every image being found" \
    'if by_xargs or not names or {"-a", "--all"} & set(args) or any("$(" in n for n in names):' \
    'if {"-a", "--all"} & set(args):'
  mutation red "rm outside the checkout being found" \
    'return path.startswith(_HOME_ROOTS) or path.startswith("/")' 'return path.startswith("/usr")'
  mutation red "apt-get remove/purge/autoremove being found" \
    'hit, setup = (f"{base} {sub}" if sub in _APT_REMOVE else ""), sub in _APT_SETUP' \
    'hit, setup = "", sub in _APT_SETUP'
  mutation red "a substitution scanned as a script of its own" \
    'elif text.startswith("$(", i) or (c == "`" and closer != "`"):' 'elif False:'
  mutation red "bash -c scanned" 'if base in _SHELLS and "-c" in words[1:-1]:' 'if False:'
  mutation red "a comment not being a command" \
    'elif c == "#" and (not cur or cur[-1][-1:].isspace()):' 'elif False:'
  mutation red "quoted text not being a command" \
    '        elif quote:
            cur.append(c)
            i += 1
' ''
  mutation red "a named docker rmi left alone" \
    '            return "docker " + " ".join(args)[:60] + " (every image)", True
        return "", True' \
    '            return "docker " + " ".join(args)[:60] + " (every image)", True
        return "docker rmi", True'
  mutation red "setup and cleanup commands making a setup step" \
    'hit, setup = "", base in _REPORTS or base in _SETUP_TOOLS' 'hit, setup = "", base in _REPORTS'
}
