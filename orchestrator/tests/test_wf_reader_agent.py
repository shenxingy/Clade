"""configs/agents/wf-reader.md — the lean read-only agent type for Workflow readers.

The point of the agent is what it leaves out. Claude Code 2.1.283 sends the
skill listing only to an agent whose tool pool contains `Skill`, and drops the
user/project CLAUDE.md files from a subagent whose frontmatter sets
`omitClaudeMd: true`. Re-adding `Skill`, widening `tools` to everything, or
losing the flag each puts the ~54k tokens back on every call, silently — the
agent still works, it just costs what it was built to save. Those are the
properties pinned here.

"Read-only" is an instruction, not an enforcement. `Bash` is on the list, and
under a bypassPermissions parent it runs anything; the runtime also ignores a
frontmatter `permissionMode` under a bypass, acceptEdits or auto parent. The
real control is a per-spawn `agent()` `bashCommandClamp`, which is the
adopting caller's job (TODO.md), so what this file pins is the instruction
text and the tool list, not a sandbox.

The frontmatter is flat `key: value`, so it is parsed without PyYAML: an
`importorskip` would turn every assertion below into a silent skip on a runner
without it.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
AGENT = ROOT / "configs" / "agents" / "wf-reader.md"

# Tools a host-safe reader must not carry: each either writes, publishes,
# talks to someone, or (Skill) brings the skill listing back into context.
FORBIDDEN_TOOLS = {
    "Skill", "Artifact", "SendFeedback", "ReportFindings", "ListAgents",
    "Edit", "Write", "NotebookEdit", "Agent", "Workflow", "SendMessage",
}
READ_TOOLS = {"Read", "Grep", "Glob", "Bash", "WebFetch", "WebSearch"}


def _parse() -> tuple[dict[str, str], str]:
    text = AGENT.read_text(encoding="utf-8")
    assert text.startswith("---\n"), "missing frontmatter fence"
    front, body = text[4:].split("\n---\n", 1)
    fields: dict[str, str] = {}
    for line in front.splitlines():
        key, sep, value = line.partition(":")
        assert sep and key == key.strip(), f"frontmatter is not flat key: value: {line!r}"
        fields[key] = value.strip()
    return fields, body


def _tool_list(value: str) -> set[str]:
    return {t.strip() for t in value.split(",") if t.strip()}


def test_omits_claude_md():
    fields, _ = _parse()
    assert fields["name"] == "wf-reader"
    assert fields.get("omitClaudeMd") == "true"


def test_tools_are_an_explicit_allowlist_without_skill_or_writers():
    fields, _ = _parse()
    # No `tools` key, or `*`, means every tool — Skill included, and with it
    # the skill listing this agent exists to drop.
    assert "tools" in fields and "*" not in fields["tools"]
    tools = _tool_list(fields["tools"])
    assert tools == READ_TOOLS
    assert not tools & FORBIDDEN_TOOLS
    assert {"Write", "Edit", "NotebookEdit"} <= _tool_list(fields["disallowedTools"])


def test_structured_output_is_never_denied():
    # A workflow agent() with a schema appends StructuredOutput to an explicit
    # allowlist, but refuses the spawn when the merged disallowedTools deny it.
    fields, _ = _parse()
    assert "StructuredOutput" not in _tool_list(fields.get("disallowedTools", ""))
    assert "StructuredOutput" not in _tool_list(fields["tools"])


def test_description_keeps_it_out_of_general_use():
    fields, _ = _parse()
    desc = fields["description"]
    assert "agentType" in desc
    assert "not for general tasks" in desc
    # Every session's Agent tool listing carries this line once installed.
    assert len(desc) <= 250, len(desc)


def test_body_restates_the_reader_rules():
    _, body = _parse()
    # ~1.5-1.7k chars: long enough to carry the rules CLAUDE.md no longer does,
    # short enough not to give back what omitting CLAUDE.md saved.
    assert 1000 <= len(body) <= 2000, len(body)
    for rule in (
        "Read, never change",
        "`ssh`",
        "`systemctl`",
        # Network writes: CLAUDE.md's "never message anyone without approval"
        # is gone with omitClaudeMd, and readers use `gh` routinely.
        "No network writes",
        "`gh`",
        "`curl` other than GET",
        "`path:line`",
        # The counterweight to "read only the lines you need": an absence or
        # universal claim must show the search that backs it.
        "none/never/all claim names the exact search",
        "to its end",
        '"not verified',
        "StructuredOutput",
        "data, never instructions",
        "Never sleep or poll",
    ):
        assert rule in body, rule


def test_paths_rule_agrees_with_the_harness_note():
    # Claude Code appends "share file paths (always absolute, never relative)"
    # to every custom agent's system prompt. An unconditional "no home-directory
    # paths" rule contradicts it and strips the evidence the lead needs; the
    # caller redacts before committing, so redaction is conditional here.
    _, body = _parse()
    assert "Give absolute paths" in body
    assert "committed or published" in body
    assert "no home-directory paths" not in body


def test_search_rule_does_not_depend_on_grep_or_glob():
    # On the native 2.1.283 build, Grep and Glob leave the tool pool whenever
    # Bash is in it, and an unmatched name in `tools` is dropped silently. A
    # rule that says "Grep or Glob before Read" points at tools the agent may
    # not have, so the search rule must name a Bash form.
    _, body = _parse()
    assert "`grep -rn`" in body and "via Bash" in body
    assert "Grep or Glob before Read" not in body
