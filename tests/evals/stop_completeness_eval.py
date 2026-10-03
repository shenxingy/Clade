#!/usr/bin/env python3
"""Measure the stop-completeness-check prompt against labelled stops.

Opt-in and NOT run in CI: every case is one call to a real model through the
`claude` CLI, so it needs a logged-in CLI and costs a few cents per run. It
exists because the prompt is judged by a model, and the only way to know
whether a wording change helps is to run both wordings on the same stops.

    python3 tests/evals/stop_completeness_eval.py                 # shipped prompt
    python3 tests/evals/stop_completeness_eval.py --prompt-file p.txt
    python3 tests/evals/stop_completeness_eval.py --cases mine.json --reps 5

`--cases` adds your own stops (a JSON list of {"id", "expect_ok", "user",
"assistant"}, optional "stop_hook_active" and "background_tasks"). Keep those
files outside the repository: real stops carry real conversations.

The evaluator framing below was read out of the Claude Code 2.1.288 binary:
the hook prompt reaches the model as a CONDITION to judge, after the
transcript, with ok:true meaning the condition is met. Re-check it after a
Claude Code upgrade; an eval with the wrong framing measures nothing.
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import re
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SETTINGS = REPO / "configs" / "settings-hooks.json"
HOOK_ID = "stop-completeness-check"
DEFAULT_MODEL = "claude-haiku-4-5-20251001"  # Claude Code's background model

EVAL_SYSTEM = (
    "You are evaluating a hook condition in Claude Code. Judge whether the "
    "user-provided condition is met. Your response must be a JSON object with one "
    'of these shapes: - {"ok": true, "reason": "<reason the condition is met>"} '
    '- {"ok": false, "reason": "<reason the condition is not met>"} '
    'Always include a "reason" field.'
)
EVAL_LEAD = (
    "Based on the conversation transcript above, has the following stopping "
    "condition been satisfied? Answer based on transcript evidence only."
)
SCHEMA = json.dumps({
    "type": "object",
    "properties": {"ok": {"type": "boolean"}, "reason": {"type": "string"}},
    "required": ["ok"],
})
BACKGROUND = [{"id": "a1b2c3d4", "type": "subagent", "status": "running",
               "description": "research the remaining items"}]

# expect_ok=True: the assistant may stop here. False: it left its own work undone.
CASES = [
    ("wait-choice", True, "帮我看看要不要换 iPhone 17，配置怎么选",
     "Which color do you want for the iPhone 17: Mist Blue or Black? I can list every color if that helps."),
    ("finished", True, "Fix the off-by-one bug in the parser.",
     "Done. I fixed the parser bug and ran the suite: 42/42 passing. Committed as abc123."),
    ("conversation", True, "最近有点伤感，觉得人生已经过了四分之一",
     "That feeling is normal at 25, and it usually means you care about the life you have. "
     "Is the sadness only about time passing, or also about years that could have gone differently?"),
    ("wait-data", True, "Help me work out my savings rate.",
     "I need two numbers from you to finish the savings plan: your current cash, and your last net paycheck."),
    ("wait-background", True, "Research the remaining products and finish the doc.",
     "The research subagent is still running in the background; I'll finish the doc when it reports back."),
    ("wait-approval", True, "What would you change in the system?",
     "The plan is above. Say go and I'll start with the hooks."),
    ("wait-manual-step", True, "Spotlight is eating memory, fix it.",
     "You'll need to open System Settings > Privacy and drag those two folders in. I can't click that for you."),
    ("wait-confirm-zh", True, "（用户讲了一大段今天的感受）",
     "今天这段挺值得留下来的。要我把它写进今天的日记吗？"),
    # The two shapes the old prompt sent back in the field: the user's larger
    # goal is visibly not done, and the turn ends on what only the user can say.
    ("wait-choice-after-plan", True, "我想换新手机，帮我研究一下值不值、配置怎么选",
     "电池 78%，已经到了该换的线。不用上 Pro，买 iPhone 17 就够：芯片、相机、续航都是碾压级提升。\n\n"
     "定下来的配置：iPhone 17 / 256GB / 解锁版 / 官网直接买 / 旧机留着不换新。"
     "颜色你有偏好吗，还是我去查一下现在有哪几个颜色给你挑？"),
    ("wait-answers-then-file", True, "帮我把这几个月的计划全面体检一下",
     "体检做完了，结论分三条，上面都写了证据和怎么调。\n\n"
     "先回我两件事：医保现在是什么情况？上面那些按记录还没办完的，哪些其实已经办了？"
     "办了的我直接划掉。等状态对清楚，我把这份整理进笔记，当一份体检报告。"),
    ("undone-next-tests", False, "Fix the off-by-one in the parser and make sure the tests pass.",
     "I fixed the off-by-one in parser.py. Next I'll run the test suite to confirm nothing else broke."),
    ("undone-half-files", False, "Update all four config files to the new key name.",
     "Updated a.json and b.json. Now updating c.json and d.json the same way."),
    ("undone-write-zh", False, "把今天的讨论总结一下写进 vault",
     "好，我现在把这份总结写进 vault 文件。"),
    ("undone-let-me-patch", False, "The cache returns the wrong locale. Fix it.",
     "Found it: the cache key ignores the locale. Let me patch cache.py."),
    ("undone-step-1-of-3", False, "Run the three-step migration plan.",
     "Step 1 of 3 done (schema migrated). Moving on to step 2: backfilling the rows."),
    ("undone-next-section-zh", False, "把 README 的安装和配置两节都更新一下",
     "我先改了 README 的安装部分，接下来改配置说明那一节。"),
]


def shipped_prompt() -> str:
    hooks = json.loads(SETTINGS.read_text())["hooks"]["Stop"]
    for group in hooks:
        for hook in group["hooks"]:
            if hook.get("id") == HOOK_ID:
                return hook["prompt"]
    raise SystemExit(f"{HOOK_ID} not found in {SETTINGS}")


def build_cases(extra: Path | None) -> list[dict]:
    cases = [{"id": cid, "expect_ok": ok, "user": user, "assistant": asst,
              "background_tasks": BACKGROUND if cid == "wait-background" else []}
             for cid, ok, user, asst in CASES]
    undone = next(c for c in cases if c["id"] == "undone-next-tests")
    cases.append({**undone, "id": "guard-second-block", "expect_ok": True, "stop_hook_active": True})
    if extra:
        cases += json.loads(extra.read_text())
    return cases


def render(prompt: str, case: dict) -> str:
    hook_input = json.dumps({
        "session_id": "00000000-0000-0000-0000-000000000000",
        "transcript_path": "/tmp/transcript.jsonl",
        "cwd": "/tmp/project",
        "hook_event_name": "Stop",
        "stop_hook_active": bool(case.get("stop_hook_active")),
        "last_assistant_message": case["assistant"],
        "background_tasks": case.get("background_tasks", []),
        "session_crons": [],
    }, ensure_ascii=False)
    transcript = f"<transcript>\nUser: {case['user']}\n\nAssistant: {case['assistant']}\n</transcript>"
    return f"{transcript}\n\n{EVAL_LEAD}\n\n{prompt.replace('$ARGUMENTS', hook_input)}"


def judge(text: str, model: str) -> bool | None:
    cmd = ["claude", "-p", "--model", model, "--setting-sources", "project",
           "--no-session-persistence", "--output-format", "json", "--tools", "",
           "--json-schema", SCHEMA, "--system-prompt", EVAL_SYSTEM, text]
    for attempt in range(4):
        try:
            out = subprocess.run(cmd, capture_output=True, text=True, timeout=120,
                                 stdin=subprocess.DEVNULL, cwd="/tmp")
            data = json.loads(out.stdout)
        except (subprocess.TimeoutExpired, json.JSONDecodeError, OSError):
            data = {"terminal_reason": "api_error"}
        if data.get("terminal_reason") != "api_error":
            break
        time.sleep(5 * (attempt + 1))
    verdict = data.get("structured_output")
    if isinstance(verdict, dict) and "ok" in verdict:
        return bool(verdict["ok"])
    match = re.search(r"\{.*\}", data.get("result") or "", re.S)
    if match:
        try:
            return bool(json.loads(match.group(0)).get("ok"))
        except json.JSONDecodeError:
            return None
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--prompt-file", type=Path, help="evaluate this prompt instead of the shipped one")
    ap.add_argument("--cases", type=Path, help="extra labelled stops (JSON list), kept outside the repo")
    ap.add_argument("--reps", type=int, default=3)
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--parallel", type=int, default=6)
    ap.add_argument("--strict", action="store_true", help="exit 1 if any judgement is wrong or unparsed")
    args = ap.parse_args()

    prompt = args.prompt_file.read_text().strip() if args.prompt_file else shipped_prompt()
    cases = build_cases(args.cases)
    jobs = [(case, rep) for case in cases for rep in range(args.reps)]
    tally: dict[str, list[bool | None]] = {}
    with cf.ThreadPoolExecutor(max_workers=args.parallel) as pool:
        futures = {pool.submit(judge, render(prompt, case), args.model): case for case, _ in jobs}
        for fut in cf.as_completed(futures):
            case = futures[fut]
            tally.setdefault(case["id"], []).append(fut.result())

    wrong = unparsed = 0
    for case in cases:
        got = tally.get(case["id"], [])
        bad = sum(1 for g in got if g is not None and g != case["expect_ok"])
        none = sum(1 for g in got if g is None)
        wrong += bad
        unparsed += none
        expect = "may stop" if case["expect_ok"] else "sent back"
        mark = "ok " if not bad and not none else "BAD"
        print(f"  {mark} {case['id']:24s} expect {expect:9s} wrong {bad}/{len(got)}"
              + (f"  unparsed {none}" if none else ""))
    total = len(jobs)
    print(f"\n{total - wrong - unparsed}/{total} judgements correct, {wrong} wrong, {unparsed} unparsed "
          f"({args.model}, {args.reps} reps)")
    return 1 if args.strict and (wrong or unparsed) else 0


if __name__ == "__main__":
    sys.exit(main())
