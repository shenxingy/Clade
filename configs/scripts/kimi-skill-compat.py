#!/usr/bin/env python3
"""Report which Clade skills need adaptation or cannot run under Kimi Code.

This is a static, report-only scan of SKILL.md, prompt.md, references/, and
scripts/. It does not execute a skill and does not prove live runtime behaviour.
Every rule below names the Kimi 2.6.0 bundled-source fact it rests on. Where the
current documentation differs, the installed 2.6.0 source is authoritative.

Kimi facts used by the rules:
  * Built-in registrations and input schemas live under
    packages/agent-core-v2/src/agent/tools/ and src/features/. In particular,
    Agent takes {prompt, description, subagent_type?, resume?,
    run_in_background?}; FetchURL takes {url}; TodoList takes {todos?: [{title,
    status}]}; CronCreate takes {cron, prompt, recurring?}. Claude's Workflow,
    Monitor, Artifact, and ToolSearch have no corresponding built-in registration.
  * packages/agent-core-v2/src/features/skill/catalog/registry.ts substitutes
    ${KIMI_SKILL_DIR} and ${KIMI_SESSION_ID}, not Claude's spellings.
  * packages/agent-core-v2/src/session/agentLifecycle/profile/profiles.ts
    registers coder and explore; features/plan/profile/plan.ts registers plan.
  * Claude Code settings/hook configuration is not Kimi's config.toml hook
    contract. A settings-only integration is treated as optional; a procedure
    that generates or depends on the Claude hook lifecycle is core.

A USE is an instructional or executable occurrence. Routing frontmatter, code
comments, negated recommendations, and prose explicitly comparing Claude/Kimi
are MENTIONS and are ignored. Ambiguous ordinary words (Workflow, Monitor,
Artifact, Task) require a tool-call/tool-name shape. An unmapped primitive with
a local availability/optional/fallback marker is DEGRADED. Artifact is the one
shared-guard exception: its explicit "if that tool is available in this runtime"
check covers its later publication uses too. Any unguarded use is CLAUDE-ONLY.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import re
import sys
import tempfile
from pathlib import Path
from typing import NamedTuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
import skill_frontmatter as sf  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
DEFAULT_ROOT = REPO / "configs" / "skills"
CLASSES = ("native", "adapted", "degraded", "claude-only")
TEXT_SUFFIXES = {
    "", ".json", ".md", ".py", ".sh", ".toml", ".ts", ".txt", ".yaml", ".yml",
    ".js",
}


class Rule(NamedTuple):
    primitive: str
    pattern: re.Pattern[str]
    kimi: str | None
    fact: str
    optional_integration: bool = False
    shared_guard: bool = False


def _rule(primitive: str, pattern: str, kimi: str | None, fact: str,
          optional_integration: bool = False, shared_guard: bool = False) -> Rule:
    return Rule(primitive, re.compile(pattern, re.MULTILINE), kimi, fact,
                optional_integration, shared_guard)


_CLAUDE_PROFILES = (
    r"(?:audit-(?:budget|compliance|creative|google|meta|tracking)|"
    r"blog-(?:researcher|reviewer|seo|translator|writer)|"
    r"seo-(?:backlinks|cluster|content|dataforseo|drift|ecommerce|geo|google|image-gen|local|maps|performance|"
    r"schema|sitemap|sxo|technical|visual)|"
    r"bounded-implementer|code-reviewer|copy-writer|creative-strategist|debug-specialist|"
    r"format-adapter|paper-reviewer|second-opinion-(?:codex|gemini|kimi)|security-auditor|"
    r"test-runner|type-checker|verify-app|visual-designer|wf-reader)"
)
_CLAUDE_PROFILE_USAGE = (
    r"\bsubagent_type\s*=\s*[\"'`]" + _CLAUDE_PROFILES + r"\b|"
    r"\b(?i:spawn|dispatch)\b[^\n]*\b" + _CLAUDE_PROFILES + r"\b|"
    r"\b" + _CLAUDE_PROFILES + r"\b[^\n]*\b(?:Task|Agent)`?\s+tool\b|"
    r"\b(?:Task|Agent)`?\s+tool\b[^\n]*\b" + _CLAUDE_PROFILES + r"\b"
)

RULES = (
    _rule("TodoWrite", r"\bTodoWrite\b", "TodoList",
          "features/todo/tools/todo-list/todo-list.ts: todos:[{title,status}]"),
    _rule("WebFetch", r"\bWebFetch\b", "FetchURL",
          "agent/tools/fetch-url/fetch-url.ts: FetchURLInputSchema={url}"),
    _rule("Task", r"\bTask(?:\(|`?\s+tool\b|\s+by\s+their\s+Claude\s+names\b)", "Agent",
          "session/subagent/subagentScopeCacheService.ts: Agent={prompt,description,subagent_type?,...}"),
    _rule("Explore", r"\bsubagent_type\s*=\s*[\"'`]?Explore\b|\bExplore\s+(?:agent|subagent)\b", "explore",
          "session/agentLifecycle/profile/profiles.ts registers explore"),
    _rule("general-purpose", r"\bsubagent_type\s*=\s*[\"'`]?general-purpose\b|\bgeneral-purpose\s+(?:agent|subagent)\b", "coder",
          "session/agentLifecycle/profile/profiles.ts registers coder"),
    _rule("Plan", r"\bsubagent_type\s*=\s*[\"'`]?Plan\b|\bPlan\s+(?:agent|subagent)\b", "plan",
          "features/plan/profile/plan.ts registers plan"),
    _rule("ScheduleWakeup", r"\bScheduleWakeup\b", "CronCreate (rewrite the delay as cron)",
          "features/cron/tools/cron-create/cron-create.ts: {cron,prompt,recurring?}"),
    _rule("BashOutput", r"\bBashOutput\b", "TaskOutput",
          "agent/tools/task/task-output/taskOutputTool.ts registers TaskOutput"),
    _rule("KillShell", r"\bKillShell\b", "TaskStop",
          "agent/tools/task/task-stop/taskStopTool.ts registers TaskStop"),
    _rule("SlashCommand", r"\bSlashCommand\s*(?:\(|(?:\s+tool\b))", "Skill",
          "features/skill/tools/skill.ts: Skill={skill,path?,args?}"),
    _rule("${CLAUDE_SKILL_DIR}", r"\$\{CLAUDE_SKILL_DIR\}", "${KIMI_SKILL_DIR}",
          "features/skill/catalog/registry.ts renderSkillPrompt substitutes KIMI_SKILL_DIR"),
    _rule("${CLAUDE_SESSION_ID}", r"\$\{CLAUDE_SESSION_ID\}", "${KIMI_SESSION_ID}",
          "features/skill/catalog/registry.ts renderSkillPrompt substitutes KIMI_SESSION_ID"),
    _rule("Workflow", r"\bWorkflow(?:\(|`?\s+tool\b|`?\s+script\b)|\bvia\s+Workflow\b", None,
          "No Workflow registration in the 2.6.0 built-in tool registry"),
    _rule("Monitor", r"\bMonitor(?:\(|`?\s+tool\b)", None,
          "No Monitor registration in the 2.6.0 built-in tool registry"),
    _rule("Artifact", r"\bArtifact`?\s+tool\b|\bArtifact\s*\(\s*action|\bpublish an Artifact\b", None,
          "No Artifact registration in the 2.6.0 built-in tool registry", shared_guard=True),
    _rule("ToolSearch", r"\bToolSearch\b", None,
          "No ToolSearch registration in the 2.6.0 built-in tool registry"),
    _rule("Claude subagent profile", _CLAUDE_PROFILE_USAGE, None,
          "Kimi resolves installed profile names; configs/agents profiles are not 2.6.0 built-ins or Kimi bridge agents"),
    _rule("context: fork", r"\bcontext:\s*fork\b", None,
          "Agent uses fork:true only behind the subagent_fork experimental flag, not context:fork"),
    _rule("${CLAUDE_PLUGIN_ROOT}", r"\$\{CLAUDE_PLUGIN_ROOT\}", None,
          "registry.ts has no CLAUDE_PLUGIN_ROOT skill substitution"),
    _rule("${CLAUDE_PROJECT_DIR}", r"\$\{CLAUDE_PROJECT_DIR\}", None,
          "registry.ts has no CLAUDE_PROJECT_DIR skill substitution; use an explicit path"),
    _rule("${CLAUDE_EFFORT}", r"\$\{CLAUDE_EFFORT\}", None,
          "registry.ts has no CLAUDE_EFFORT skill substitution"),
    _rule("claude -p", r"(?<![\w-])claude\s+(?:-p\b|--print\b)", None,
          "The Claude CLI is a separate runtime; Kimi's built-in tools cannot supply claude -p"),
    _rule("Claude hook lifecycle",
          r"\bStop hook\s+(?:detects|re-?prompts|feeds)|"
          r"\bSessionStart\b[^\n]{0,100}(?:auto-?load|inject)|"
          r"(?:auto-?load|inject)[^\n]{0,100}\bSessionStart\b|"
          r"Hook type:\s*\{?(?:PreToolUse|PostToolUse)|"
          r"Produce the JSON snippet to add to\s*`?~/?\.claude/settings\.json",
          None,
          "Kimi uses config.toml hook events/output, not Claude's settings.json lifecycle contract"),
    _rule("Claude settings integration", r"(?:~/?\.claude/settings\.json|\.claude/settings\.json)", None,
          "Kimi reads config.toml/mcp.json, not ~/.claude/settings.json", optional_integration=True),
)
RULE_BY_NAME = {rule.primitive: rule for rule in RULES}

_MENTION_ANY = re.compile(
    r"\bby their Claude names\b|\bClaude-only machinery\b|\bno Kimi equivalent\b|"
    r"\bnot available (?:in|under) Kimi\b",
    re.IGNORECASE,
)
_NEGATED_USE = re.compile(
    r"\bNOT for\b|\bnot for\b|\bdo not use\b|\bdon't use\b|\bnever use\b|"
    r"\binstead of\b|\brather than\b",
    re.IGNORECASE,
)
_OPTIONAL = re.compile(
    r"\boptional\b|\bif available\b|\bif\b[^\n]{0,80}\b(?:available|configured|detected)\b|"
    r"\botherwise\b|\bfall ?back\b|\bgraceful degradation\b|"
    r"\bwhen [^\n]{0,60} unavailable\b",
    re.IGNORECASE,
)
_HEADING = re.compile(r"^#{1,6}\s+")


def _body_lines(text: str) -> list[str]:
    front, body = sf.split_frontmatter(text)
    if front is None:
        return text.splitlines()
    del front
    return body.splitlines()


def _skill_files(directory: Path) -> list[tuple[str, list[str], bool]]:
    found: list[tuple[str, list[str], bool]] = []
    skill_md = directory / "SKILL.md"
    text = skill_md.read_text(encoding="utf-8", errors="replace")
    found.append(("SKILL.md", _body_lines(text), True))
    candidates = [directory / "prompt.md"]
    for part in ("references", "scripts"):
        root = directory / part
        if root.is_dir():
            candidates.extend(
                path for path in root.rglob("*")
                if path.is_file() and path.suffix.lower() in TEXT_SUFFIXES
            )
    for path in sorted(candidates):
        if not path.is_file():
            continue
        rel = path.relative_to(directory).as_posix()
        body = path.read_text(encoding="utf-8", errors="replace")
        found.append((rel, body.splitlines(), path.suffix.lower() in {".py", ".sh", ".js", ".ts"}))
    return found


def _is_mention(line: str, code_file: bool, position: int) -> bool:
    stripped = line.lstrip()
    if code_file and stripped.startswith(("#", "//")):
        return True
    if _MENTION_ANY.search(line):
        return True
    for negated in _NEGATED_USE.finditer(line):
        if negated.start() >= position:
            continue
        prefix = line[negated.start():position]
        if len(prefix) <= 120 and not re.search(r"[.!?;]\s", prefix):
            return True
    return False


def _scan_skill(directory: Path) -> dict:
    evidence: list[dict] = []
    mentions: list[dict] = []
    scanned_files: list[str] = []
    for rel, lines, code_file in _skill_files(directory):
        scanned_files.append(rel)
        optional_heading = False
        for number, line in enumerate(lines, 1):
            if _HEADING.match(line):
                optional_heading = _OPTIONAL.search(line) is not None
            for rule in RULES:
                for match in rule.pattern.finditer(line):
                    item: dict = {
                        "path": rel,
                        "line": number,
                        "text": line.strip()[:300],
                        "primitive": rule.primitive,
                        "kimi": rule.kimi,
                        "fact": rule.fact,
                    }
                    if _is_mention(line, code_file, match.start()):
                        mentions.append(item)
                        continue
                    context = "\n".join(lines[max(0, number - 3):number])
                    item["optional"] = bool(
                        rule.optional_integration or optional_heading or _OPTIONAL.search(context)
                    )
                    evidence.append(item)

    optional_primitives = {
        item["primitive"] for item in evidence
        if item["optional"] and RULE_BY_NAME[item["primitive"]].shared_guard
    }
    for item in evidence:
        if item["primitive"] in optional_primitives:
            item["optional"] = True

    unsupported = {item["primitive"] for item in evidence if item["kimi"] is None}
    required = {item["primitive"] for item in evidence if item["kimi"] is None and not item["optional"]}
    adapted = {item["primitive"] for item in evidence if item["kimi"] is not None}
    if required:
        classification = "claude-only"
    elif unsupported:
        classification = "degraded"
    elif adapted:
        classification = "adapted"
    else:
        classification = "native"
    return {
        "name": directory.name,
        "classification": classification,
        "adaptations": sorted(
            {f"{item['primitive']}→{item['kimi']}" for item in evidence if item["kimi"] is not None}
        ),
        "unsupported": sorted(unsupported),
        "required_unsupported": sorted(required),
        "optional_unsupported": sorted(unsupported - required),
        "evidence": evidence,
        "mentions": mentions,
        "scanned_files": scanned_files,
    }


def scan_tree(root: Path, selected: str | None = None) -> list[dict]:
    if not root.is_dir():
        raise OSError(f"skills directory does not exist: {root}")
    directories = sorted(path.parent for path in root.glob("*/SKILL.md"))
    if selected is not None:
        directories = [path for path in directories if path.name == selected]
        if not directories:
            raise ValueError(f"skill not found under {root}: {selected}")
    if not directories:
        raise ValueError(f"no skill directories with SKILL.md under {root}")
    results = [_scan_skill(directory) for directory in directories]
    if len(results) != len(directories) or {r["name"] for r in results} != {p.name for p in directories}:
        raise RuntimeError("internal scan error: skill directories in != classifications out")
    return results


def _totals(results: list[dict]) -> dict[str, int]:
    totals = {name: sum(row["classification"] == name for row in results) for name in CLASSES}
    totals["skills"] = len(results)
    return totals


def _render_table(results: list[dict]) -> str:
    lines = ["SKILL\tCLASS\tADAPTED\tUNSUPPORTED (required; optional)"]
    for row in results:
        unsupported = f"{', '.join(row['required_unsupported']) or '-'}; {', '.join(row['optional_unsupported']) or '-'}"
        lines.append(f"{row['name']}\t{row['classification']}\t{', '.join(row['adaptations']) or '-'}\t{unsupported}")
    totals = _totals(results)
    lines.append("TOTALS\t" + "\t".join(f"{name}={totals[name]}" for name in (*CLASSES, "skills")))
    return "\n".join(lines) + "\n"


def _render_one(row: dict) -> str:
    lines = [_render_table([row]).rstrip(), "EVIDENCE"]
    if not row["evidence"]:
        lines.append("no Claude-only primitive USES in: " + ", ".join(row["scanned_files"]))
    for item in row["evidence"]:
        disposition = "optional" if item["optional"] else "required"
        lines.append(
            f"{item['path']}:{item['line']}: {item['primitive']} -> {item['kimi'] or 'none'} "
            f"({disposition}) | {item['text']}"
        )
    if row["mentions"]:
        lines.append("MENTIONS (ignored)")
        for item in row["mentions"]:
            lines.append(f"{item['path']}:{item['line']}: {item['primitive']} | {item['text']}")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT, help="skills root (default: configs/skills)")
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    parser.add_argument("--skill", help="scan only this skill and show every evidence line")
    parser.add_argument("--self-test", action="store_true", help="run synthetic positive and negative controls")
    args = parser.parse_args(argv)
    if args.self_test:
        return self_test()
    try:
        results = scan_tree(args.root, args.skill)
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"kimi-skill-compat: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps({"root": str(args.root), "totals": _totals(results), "skills": results},
                         indent=2, ensure_ascii=False))
    elif args.skill:
        sys.stdout.write(_render_one(results[0]))
    else:
        sys.stdout.write(_render_table(results))
    return 0


RULE_EXAMPLES = {
    "TodoWrite": "Call TodoWrite with the implementation steps.",
    "WebFetch": "Fetch the source with WebFetch.",
    "Task": "Use the Task tool for a worker.",
    "Explore": "Use subagent_type=\"Explore\" for read-only exploration.",
    "general-purpose": "Use subagent_type=\"general-purpose\" for implementation.",
    "Plan": "Use subagent_type=\"Plan\" for planning.",
    "ScheduleWakeup": "Call ScheduleWakeup for the next iteration.",
    "BashOutput": "Read it with BashOutput.",
    "KillShell": "Stop it with KillShell.",
    "SlashCommand": "Call the SlashCommand tool next.",
    "${CLAUDE_SKILL_DIR}": "python3 ${CLAUDE_SKILL_DIR}/scripts/run.py",
    "${CLAUDE_SESSION_ID}": "Record ${CLAUDE_SESSION_ID}.",
    "Workflow": "Run the Workflow tool for the core procedure.",
    "Monitor": "Call the Monitor tool for progress.",
    "Artifact": "Publish through the Artifact tool.",
    "ToolSearch": "Call ToolSearch to discover a tool.",
    "Claude subagent profile": "Use the Agent tool with subagent_type=\"security-auditor\".",
    "context: fork": "Use the Task tool with context: fork.",
    "${CLAUDE_PLUGIN_ROOT}": "python3 ${CLAUDE_PLUGIN_ROOT}/scripts/run.py",
    "${CLAUDE_PROJECT_DIR}": "Read ${CLAUDE_PROJECT_DIR}/file.md.",
    "${CLAUDE_EFFORT}": "Record ${CLAUDE_EFFORT}.",
    "claude -p": "Run claude -p for the worker.",
    "Claude hook lifecycle": "The Stop hook detects the sentinel and re-prompts.",
    "Claude settings integration": "Write the optional integration to ~/.claude/settings.json.",
}


def _selftest_skill(root: Path, name: str, body: str, description: str = "Synthetic control") -> None:
    directory = root / name
    directory.mkdir(parents=True)
    (directory / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {description}\n---\n{body}\n", encoding="utf-8"
    )


def _selftest_main(args: list[str]) -> tuple[int, str, str]:
    stdout, stderr = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        code = main(args)
    return code, stdout.getvalue(), stderr.getvalue()


def _selftest_run() -> None:
    with tempfile.TemporaryDirectory(prefix="kimi-skill-compat-selftest-") as tmp:
        root = Path(tmp) / "skills"
        root.mkdir()
        _selftest_skill(root, "native", "Read the file, then run Bash.",
                        "Workflow tool routing metadata")
        _selftest_skill(root, "native-not", "Run the Workflow tool for the core procedure.")
        _selftest_skill(root, "adapted", "Use TodoWrite and WebFetch.")
        _selftest_skill(root, "adapted-not", "Use TodoWrite.\nOptional: use the Artifact tool if available.")
        _selftest_skill(root, "degraded",
                        "Use hosted types only if that tool is available in this runtime.\n"
                        "Check them (`Artifact` tool, action: \"list_types\").\n\n\n\n"
                        "Publish with the Artifact tool after the check.")
        _selftest_skill(root, "degraded-not", "The core procedure requires the Artifact tool.")
        _selftest_skill(root, "ordinary-heading", "## API Mode Workflow (DataForSEO)\nUse Read and Bash.")
        _selftest_skill(root, "negation-scope",
                        "Re-dispatch the blog-writer agent with the diagnostic; use the draft instead of the outline.")
        _selftest_skill(root, "positive-after-negation", "Never use TodoWrite here. Use TodoWrite for the plan.")
        _selftest_skill(root, "mixed-profiles",
                        "Spawn subagents: seo-technical, seo-content.\n"
                        "If credentials are configured, spawn seo-google agent.")
        _selftest_skill(root, "heading-only", "### Optional deep dive\n\n\n\nCall ToolSearch to discover a tool.")
        _selftest_skill(root, "conditional", "If credentials are configured, spawn seo-google agent.")
        _selftest_skill(root, "settings-only", "Write the integration to ~/.claude/settings.json.")
        _selftest_skill(root, "claude-only", "Run the Workflow tool for every execution.")
        _selftest_skill(root, "claude-only-not", "Optional: run the Workflow tool if available.")
        _selftest_skill(
            root, "mention-only",
            "NOT for fan-out: do not use the Workflow tool; use /loop.\n"
            "Task by their Claude names is comparison prose.\n"
            "Never use TodoWrite; the native list is enough.",
        )
        _selftest_skill(root, "support-files", "Read the local instructions.")
        support = root / "support-files"
        (support / "references").mkdir()
        (support / "scripts").mkdir()
        (support / "references" / "tools.md").write_text("Use TodoWrite here.\n", encoding="utf-8")
        (support / "scripts" / "fetch.py").write_text(
            "# WebFetch in a code comment is a MENTION.\nprint('Use WebFetch')\n", encoding="utf-8"
        )
        _selftest_skill(root, "all-primitives", "\n".join(RULE_EXAMPLES.values()))

        code, out, err = _selftest_main(["--root", str(root), "--json"])
        assert code == 0 and not err, (code, err)
        report = json.loads(out)
        rows = {row["name"]: row for row in report["skills"]}
        expected = {
            "native": "native", "native-not": "claude-only",
            "adapted": "adapted", "adapted-not": "degraded",
            "degraded": "degraded", "degraded-not": "claude-only",
            "claude-only": "claude-only", "claude-only-not": "degraded",
            "mention-only": "native", "ordinary-heading": "native", "support-files": "adapted",
            "negation-scope": "claude-only", "positive-after-negation": "adapted",
            "mixed-profiles": "claude-only", "heading-only": "degraded",
            "conditional": "degraded", "settings-only": "degraded", "all-primitives": "claude-only",
        }
        assert {name: row["classification"] for name, row in rows.items()} == expected
        assert len(rows) == len(expected) == report["totals"]["skills"]
        assert sum(report["totals"][name] for name in CLASSES) == len(rows)
        assert rows["native"]["evidence"] == []
        assert rows["mention-only"]["evidence"] == []
        assert len(rows["mention-only"]["mentions"]) == 3
        assert rows["adapted"]["adaptations"] == ["TodoWrite→TodoList", "WebFetch→FetchURL"]
        assert rows["degraded"]["optional_unsupported"] == ["Artifact"]
        assert rows["degraded-not"]["required_unsupported"] == ["Artifact"]
        assert rows["negation-scope"]["required_unsupported"] == ["Claude subagent profile"]
        assert rows["mixed-profiles"]["required_unsupported"] == ["Claude subagent profile"]
        assert rows["positive-after-negation"]["adaptations"] == ["TodoWrite→TodoList"]
        assert {item["primitive"] for item in rows["all-primitives"]["evidence"]} == set(RULE_EXAMPLES)
        support_paths = {item["path"] for item in rows["support-files"]["evidence"]}
        assert support_paths == {"references/tools.md", "scripts/fetch.py"}, support_paths
        assert all(item["path"] != "scripts/fetch.py" or item["line"] == 2
                   for item in rows["support-files"]["evidence"])

        code, table, err = _selftest_main(["--root", str(root)])
        assert code == 0 and not err
        assert table.startswith("SKILL\tCLASS\tADAPTED\tUNSUPPORTED") and "TOTALS\t" in table
        for classification in CLASSES:
            assert f"{classification}=" in table
        code, one, err = _selftest_main(["--root", str(root), "--skill", "support-files"])
        assert code == 0 and not err and "EVIDENCE\n" in one
        assert "references/tools.md:1: TodoWrite -> TodoList" in one
        assert "scripts/fetch.py:1: WebFetch | # WebFetch" in one
        code, native_detail, err = _selftest_main(["--root", str(root), "--skill", "native"])
        assert code == 0 and not err and "no Claude-only primitive USES" in native_detail
        code, _, err = _selftest_main(["--root", str(root), "--skill", "missing"])
        assert code == 2 and "skill not found" in err
        code, _, err = _selftest_main(["--root", str(root / "missing")])
        assert code == 2 and "does not exist" in err
        empty = Path(tmp) / "empty"
        empty.mkdir()
        code, _, err = _selftest_main(["--root", str(empty)])
        assert code == 2 and "no skill directories" in err

        original_scan = _scan_skill

        def renamed(directory: Path) -> dict:
            row = original_scan(directory)
            row["name"] = "renamed"
            return row

        try:
            globals()["_scan_skill"] = renamed
            code, _, err = _selftest_main(["--root", str(root), "--json"])
        finally:
            globals()["_scan_skill"] = original_scan
        assert code == 2 and "internal scan error" in err


def self_test() -> int:
    try:
        _selftest_run()
    except (AssertionError, ValueError, OSError, json.JSONDecodeError) as exc:
        print(f"kimi-skill-compat --self-test: FAILED: {exc}", file=sys.stderr)
        return 1
    print("kimi-skill-compat --self-test: PASSED "
          "(4 classes with positive/negative controls, mention-only controls, all primitive rules, CLI/error paths)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
