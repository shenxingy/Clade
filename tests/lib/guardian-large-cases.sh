#!/usr/bin/env bash
# Commands longer than one exec argument may be — cases for
# tests/test-pre-tool-guardian.sh, which sources this file and calls
# large_cases. Apart because that suite sits near the 1,500-line cap
# (test_conventions.py). It uses the suite's payload, run_sh, run_py,
# classify, case_failed and counters. GUARDIAN_LARGE_ONLY=1 runs only these,
# which is how orchestrator/tests/test_hook_guards_can_fire.py mutates the
# guards they pin; GUARDIAN_SIDE=sh skips the Codex mirror.
#
# Linux will not start a program when any one argument is over 128 KiB
# (MAX_ARG_STRLEN, 131,072 bytes). Every deny reason quotes the command, and
# until 2026-11-26 pre-tool-guardian.sh handed it to jq with --arg: past that
# size jq never ran, the hook printed nothing and exited 0, and Claude Code ran
# the call. Probed that day: a heredoc of harmless lines and then a delete of
# the home directory was refused at 122,924 and 129,098 bytes, and ran at
# 131,107 and above. Both rewrites failed the same way and ran the original.
# The Codex mirror refused at every size.
#
# Each lg_ok reads the status of the [[ … ]] test on the line before it.
# shellcheck disable=SC2319

# lg_body — about 140 KiB of harmless heredoc lines
lg_body() {
  awk 'BEGIN { for (i = 1; i <= 1840; i++) printf "harmless line %04d of a heredoc that pads this command past one exec argument\n", i }'
}
# lg_word <n> — one word of n x's
lg_word() { awk -v n="$1" 'BEGIN { s = "x"; while (length(s) < n) s = s s; print substr(s, 1, n) }'; }

# lg_ok <label> <status> <detail> — one case: status 0 passes
lg_ok() {
  TESTS_RUN=$((TESTS_RUN + 1))
  if [[ "$2" == 0 ]]; then
    TESTS_PASSED=$((TESTS_PASSED + 1))
    printf "  ${GREEN}✓${NC} %s\n" "$1"
  else
    printf "  ${RED}✗${NC} %s\n      %s\n" "$1" "$3"
    case_failed
  fi
  return 0
}
# lg_run <sh|py> <command> [PATH prefix] — sets LG_V (verdict), LG_WHY (deny
# reason) and LG_NEW (rewritten command). A PATH prefix puts a jq shim first.
lg_run() {
  if [[ "$1" == py ]]; then
    run_py "$2"; LG_V=$(classify "$RUN_OUT" "$RUN_RC" codex)
  else
    RUN_OUT=$(payload "$2" | PATH="${3:+$3:}$PATH" bash "$HOOK" 2>/dev/null); RUN_RC=$?
    LG_V=$(classify "$RUN_OUT" "$RUN_RC" claude)
  fi
  LG_WHY=$(jq -r '.hookSpecificOutput.permissionDecisionReason // empty' <<< "$RUN_OUT" 2>/dev/null)
  LG_NEW=$(jq -r '.hookSpecificOutput.updatedInput.command // empty' <<< "$RUN_OUT" 2>/dev/null)
}
lg_py() { [[ "${GUARDIAN_SIDE:-both}" != sh ]]; }
# lg_jq_failing <text> — a directory holding a jq that exits 5 when one of its
# arguments contains <text> and is the real jq otherwise
lg_jq_failing() {
  local d real
  real=$(command -v jq)
  d=$(mktemp -d "$NOREPO_CWD/jq.XXXXXX")
  # shellcheck disable=SC2016  # the shim's own text: its $@ and $a are for it
  printf '#!/usr/bin/env bash\nfor a in "$@"; do case "$a" in *%s*) exit 5 ;; esac; done\nexec %q "$@"\n' "$1" "$real" > "$d/jq"
  chmod +x "$d/jq"
  printf '%s' "$d"
}

large_cases() {
  local head home want t0 word shim
  head="cat <<'EOF'"$'\n'"$(lg_body)"$'\n'"EOF"$'\n'
  home="${head}rm -rf ~/"

  section "Commands over 128 KiB — the guardian still decides"
  (( ${#home} > 131072 + 8192 ))
  lg_ok "the fixture is past one exec argument (${#home} > 131,072 bytes)" $? \
    "only ${#home} bytes: every case below would pass on the old hook"

  lg_run sh "$home"
  [[ "$LG_V" == BLOCK && "$LG_WHY" == "Catastrophic rm -rf blocked on system/home directory. Target: ~/. "* ]]
  lg_ok "shell: a home delete after the heredoc is refused, by its own rule" $? "got $LG_V: ${LG_WHY:0:160}"
  [[ ${#LG_WHY} -lt 4096 && "$LG_WHY" == *"… [command clipped: the first 2000 of ${#home} characters are shown]" ]]
  lg_ok "shell: the refusal quotes the first 2,000 characters, and says so" $? \
    "reason of ${#LG_WHY} characters ends: ${LG_WHY: -160}"
  if lg_py; then
    lg_run py "$home"; [[ "$LG_V" == BLOCK ]]
    lg_ok "codex: a home delete after the heredoc is refused" $? "got $LG_V"
  fi

  lg_run sh "${head}echo done"; [[ "$LG_V" == ALLOW && -z "$RUN_OUT" ]]
  lg_ok "shell: the heredoc alone gets no decision (control)" $? "got $LG_V: ${RUN_OUT:0:160}"
  if lg_py; then
    lg_run py "${head}echo done"; [[ "$LG_V" == ALLOW ]]
    lg_ok "codex: the heredoc alone gets no decision (control)" $? "got $LG_V"
  fi

  # The rewrites: the safer command runs, the heredoc kept byte for byte.
  want="${head}rm -rf \"\${BUILD_DIR:?pre-tool-guardian: refusing a recursive delete on unset BUILD_DIR}/out\""
  lg_run sh "${head}rm -rf \"\$BUILD_DIR/out\""; [[ "$LG_V" == REWRITE && "$LG_NEW" == "$want" ]]
  lg_ok "shell: a delete of an unset variable after the heredoc is rewritten" $? "got $LG_V, ${#LG_NEW} characters"
  if lg_py; then
    lg_run py "${head}rm -rf \"\$BUILD_DIR/out\""; [[ "$LG_V" == REWRITE && "${LG_NEW//pre_tool_guardian:/pre-tool-guardian:}" == "$want" ]]
    lg_ok "codex: the same rewrite" $? "got $LG_V, ${#LG_NEW} characters"
  fi
  want="${head}git push --force-with-lease origin feat/x"
  lg_run sh "${head}git push -f origin feat/x"; [[ "$LG_V" == REWRITE && "$LG_NEW" == "$want" ]]
  lg_ok "shell: a force push after the heredoc is rewritten to --force-with-lease" $? "got $LG_V, ${#LG_NEW} characters"
  if lg_py; then
    lg_run py "${head}git push -f origin feat/x"; [[ "$LG_V" == REWRITE && "$LG_NEW" == "$want" ]]
    lg_ok "codex: the same rewrite" $? "got $LG_V, ${#LG_NEW} characters"
  fi
  lg_run sh "${head}git push --force origin main"
  [[ "$LG_V" == BLOCK && "$LG_WHY" == "Force push to main/master blocked: it names main/master. "* ]]
  lg_ok "shell: a force push to main after the heredoc is refused, by its own rule" $? "got $LG_V: ${LG_WHY:0:160}"

  # pkill's pattern written twice. The count was a grep with PAT as its
  # argument, and the text after the last pkill came from ${COMMAND##*pkill},
  # 40 s on this command; the hook is killed at 5 s. The refusal's first
  # sentence names PAT, so this reason is one the clip does not bound: only
  # stdin gets it to jq. (The Codex mirror has no pkill rule.)
  word=$(lg_word 143000)
  t0=$SECONDS
  lg_run sh "pgrep -f $word; pkill -f $word"
  [[ "$LG_V" == BLOCK && "$LG_WHY" == "pkill -f xxx"*" will match the command line of the shell running it, "* ]]
  lg_ok "shell: a 143,000-character pkill pattern written twice is refused" $? "got $LG_V: ${LG_WHY:0:80}"
  (( SECONDS - t0 < 5 ))
  lg_ok "shell: and decided inside the hook's 5 s timeout" $? "took $((SECONDS - t0)) s"

  # When jq itself fails, the call is still refused: a fixed refusal, or for a
  # rewrite a refusal of the original command.
  shim=$(lg_jq_failing permissionDecision)
  lg_run sh 'rm -rf ~' "$shim"
  [[ "$LG_V" == BLOCK && "$LG_WHY" == "pre-tool-guardian refused this command and could not write why: jq failed."* ]]
  lg_ok "shell: a refusal jq cannot write goes out as a fixed one" $? "got $LG_V: ${LG_WHY:0:160}"
  shim=$(lg_jq_failing updatedInput)
  # shellcheck disable=SC2016  # the command under test, unexpanded
  lg_run sh 'rm -rf "$BUILD_DIR/out"' "$shim"
  [[ "$LG_V" == BLOCK && "$LG_WHY" == "pre-tool-guardian could not write the safer form of this command, so it refuses it rather than run the original."* ]]
  lg_ok "shell: a rewrite jq cannot write refuses the original command" $? "got $LG_V: ${LG_WHY:0:160}"
}
