"""friction-rank.py's mutations, run by test_self_tests_can_fire.py.

That file reached 1,470 of the 1,500-line cap with this block inside it, so the
block lives here, in can_fire/, which that file loads by path. The contract is the one
that file's docstring states: each entry removes ONE guard, and the script's
own --self-test must go red. Its --self-test drives main() on synthetic
transcripts under --root, with --now pinned.

Not a test module (no ``test_`` prefix): pytest does not collect it.
"""

from __future__ import annotations

MUTATIONS: dict[str, list[tuple[str, str, str]]] = {"configs/scripts/friction-rank.py": [
    # ─── Verdict classes ───
    ("a hook denial needs an error or a denial kind — a cat quoting one counts",
     'if refused and text.startswith("PreToolUse:"):', 'if text.startswith("PreToolUse:"):'),
    ("permission refusals", "    if event.denial_kind is not None:\n        return PERMISSION", "    if False:\n        return PERMISSION"),
    ("timeouts from the Bash object", "    if event.timed_out_ms is not None:\n        return TIMEOUT", "    if False:\n        return TIMEOUT"),
    ("the timeout template only where no object was read — a log quoting it is a timeout",
     "if event.interrupted is None and not event.is_error and text.startswith(_TIMEOUT_TEMPLATE):",
     "if not event.is_error and text.startswith(_TIMEOUT_TEMPLATE):"),
    ("the timeout template — a Workflow agent's timeout with no object is missed",
     "if event.interrupted is None and not event.is_error and text.startswith(_TIMEOUT_TEMPLATE):", "if False:"),
    ("a retry follows a verdict — an identical poll after a success counts",
     "if i and classes[i - 1] and _same_call(events[i - 1], event)", "if i and _same_call(events[i - 1], event)"),
    ("a retry has the same input — any next call of the same tool counts",
     "if i and classes[i - 1] and _same_call(events[i - 1], event)", "if i and classes[i - 1] and events[i - 1].name == event.name"),
    ("a retry is sent after the verdict — two identical calls in one batch count",
     "and event.index > (events[i - 1].result_index or 0):", "and True:"),
    ("a retry's text is the verdict it retried past — its own result is shown",
     'prior.result or ""', 'event.result or ""'),
    ("hook errors are read from the attachments", "        if att.kind == HOOK_ERROR:", "        if False:"),
    ("a hook error's next calls are the ones after it — the transcript's first three are shown",
     "after = next((j for j, e in enumerate(events) if e.index > att.index), len(events))", "after = 0"),
    # ─── Families ───
    ("heredoc bodies are stripped before the family is cut",
     'text = tr.strip_heredocs(command).replace("\\\\\\n", " ")', 'text = command.replace("\\\\\\n", " ")'),
    ("a leading cd DIR && is skipped — every such command is Bash:cd", "        elif tok in _PRELUDES:", "        elif False:"),
    ("a subshell's ( is skipped — ( cd x && make ) is Bash:(", "if tok in _SEPARATORS or tok in _OPENERS:", "if tok in _SEPARATORS:"),
    ("subcommands are kept — git commit and git push are one family", "    if name in _SUBCOMMANDS:", "    if False:"),
    ("a wrapper option's value is not the command — sudo -u postgres psql is Bash:postgres",
     "i += 2 if tokens[i] in takes_value else 1", "i += 1"),
    ("a global option's value is not the subcommand — kubectl -n web get is kubectl web",
     "        elif tok in _VALUE_OPTIONS.get(name, ()):\n            skip = True", "        elif False:\n            skip = True"),
    ("a flag cluster asks for inline text — bash -lc is the basename of its script",
     "    if not _CLUSTER.match(tok):\n        return None", "    if True:\n        return None"),
    ("an interpreter option's value is not its script — bash -o pipefail -c is Bash:bash pipefail",
     "            if tok in takes_value:\n                at += 2", "            if False:\n                at += 2"),
    # ─── Reading ───
    ("main thread by default", "    if args.subagents:\n        paths +=", "    if True:\n        paths +="),
    ("a subagent's session is its lead session's", "    session = tr.session_id(path)", "    session = path.stem"),
    ("an unreadable transcript is named in the report", 'unreadable.append(f"{path}: {exc.strerror or exc}")', "pass"),
    ("sessions are counted over readable transcripts — an unreadable one adds a session",
     "for p in readable}),", "for p in paths}),"),
    ("no readable transcript is NOT MEASURED, not zero friction",
     "    if not readable:\n        return _unmeasured(", "    if False:\n        return _unmeasured("),
    ("no transcripts is NOT MEASURED, not zero friction", "    if not paths:\n        return _unmeasured(", "    if False:\n        return _unmeasured("),
    # ─── Ranking ───
    ("ranked by sessions, then count",
     '    return (-len(disc["sessions"]), -disc["count"],', '    return (-disc["count"], -len(disc["sessions"]),'),
    ("held-out weeks are held out", '        part = "held_out" if week in held_weeks else "discovery"', '        part = "discovery"'),
    ("--holdout-weeks N holds out N weeks — 2 holds out only the current one",
     "for k in range(holdout_weeks)}", "for k in range(1)}"),
    ("fewer than 7 held-out days are warned about — hours of data read as a held-out column",
     "    if held_days < _SHORT_HOLDOUT_DAYS:", "    if False:"),
    ("the window's start — a verdict older than --since is ranked", "        if when < start or when > now:", "        if when > now:"),
    ("an undated verdict is not ranked",
     '        if when is None:\n            counts["undated"] += 1\n            continue', "        if when is None:\n            when = now"),
    ("a text's latest occurrence is updated — its first is shown as its latest",
     '        if occ["at"] >= text["latest"]["at"]:\n            text["latest"] = occ',
     '        if False:\n            text["latest"] = occ'),
    ("between equally common texts the most recent leads — the oldest file's is shown",
     '-item[1]["latest"]["at"]))', "0))"),
    # ─── Refusals table ───
    ("a refusal's first sentence groups it across families", "    return line[:cut + 1] if cut != -1 else line", "    return line"),
    ("the refusals table holds hook errors",
     "_REFUSALS = (HOOK_DENIAL, PERMISSION, HOOK_ERROR)", "_REFUSALS = (HOOK_DENIAL, PERMISSION)"),
    ("the refusals table holds permission refusals",
     "_REFUSALS = (HOOK_DENIAL, PERMISSION, HOOK_ERROR)", "_REFUSALS = (HOOK_DENIAL, HOOK_ERROR)"),
    ("the refusals table holds no is_error — every failing command's output is a refusal",
     "_REFUSALS = (HOOK_DENIAL, PERMISSION, HOOK_ERROR)", "_REFUSALS = (HOOK_DENIAL, PERMISSION, HOOK_ERROR, IS_ERROR)"),
    # ─── Report ───
    ("exactly the next 3 calls", "_NEXT_CALLS = 3", "_NEXT_CALLS = 4"),
    ("the caveat is printed — friction read as a defect list", "    print(CAVEAT)\n", ""),
]}
