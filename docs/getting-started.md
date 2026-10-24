[English](getting-started.md) | [中文](getting-started.zh-CN.md)

← Back to [README](../README.md)

# Getting started

This guide separates commands run in your shell from commands typed in an
agent's chat. Choose one native surface first. Install only the optional
Orchestrator if you need its task, evidence, or fleet APIs.

## Contents

- [Prerequisites](#prerequisites)
- [Claude Code](#claude-code)
- [Codex](#codex)
- [MCP](#mcp)
- [Optional Orchestrator](#optional-orchestrator)
- [First workflow](#first-workflow)
- [Updating](#updating)
- [Troubleshooting](#troubleshooting)
- [Further reading](#further-reading)

## Prerequisites

- macOS or Linux, or Windows through Git Bash, for the full framework.
- An installed, authenticated Claude Code CLI plus Git, Bash, Python 3, and
  `jq` for the Claude framework. Python 3.11 is
  recommended for the repository's helper scripts.
- A plugin-capable Codex CLI and Python 3 for Codex's generated hooks.
- Python 3.10+, `uv`, and an authenticated Claude or Codex CLI on `PATH` for MCP.
- Node/npm only if you build the optional Orchestrator web UI.

Check versions in a shell before installing:

```bash
python3 --version
jq --version
claude --version   # if using Claude Code
codex --version    # if using Codex
uv --version       # if using MCP
```

Missing `jq` does not prevent all files from being copied, but the installer
cannot merge hooks into `~/.claude/settings.json` without it. Install `jq`, then
rerun the installer.

## Claude Code

In a shell, from a clone:

```bash
./install.sh
python3 configs/scripts/validate-skills.py configs/skills --quiet
```

The installer writes framework files under `~/.claude/`, updates the managed
Clade block in `~/.codex/AGENTS.md`, writes provider-neutral guidance to
`~/.agents/AGENTS.md`, and adapts Kimi Code files when that runtime is detected.
With `jq` present, it replaces the `hooks` and `statusLine` fields in
`~/.claude/settings.json`, adds deny rules, and updates skill settings. Save
your current configuration if you need to retain custom hooks or a status line;
review `install.sh` before running it.

Start a new Claude Code session in the project you want to work on. In agent chat, paste:
`Use Clade verify to run one documented check in this repository. Report
which command ran, its result, and anything you could not check.` Then ask it to
run `/verify`. You should see the installed skill respond and a repository check
report. Confirm the installed files under `~/.claude/` and the hooks in a fresh
session; `validate-skills.py` checks the source tree, not the installed copy.

## Codex

Requires a plugin-capable Codex CLI and Python 3 for the generated hooks. In a shell:

```text
codex plugin marketplace add shenxingy/Clade
codex plugin add clade@clade
```

Open the project you want to work on in a new Codex thread. In Codex chat, run `/hooks` and inspect Clade's two
hook definitions before trusting them. Then use `$clade:verify` on a small task.
The plugin is generated from `configs/`; maintainers can check it with:

```bash
python3 configs/scripts/regen-codex-plugin.py --check
```

An existing thread can retain an older plugin bundle. Follow the update and
recovery procedure in [Native Codex support](codex.md) before resuming parallel
work.

## MCP

Requires Python 3.10+, `uv`, and an authenticated Claude or Codex CLI resolvable
on the MCP client's `PATH`. Add this JSON to the client's MCP configuration:

```json
{
  "mcpServers": {
    "clade": {
      "command": "uvx",
      "args": ["clade-mcp"],
      "env": { "CLADE_RUNTIME": "codex" }
    }
  }
}
```

This example selects Codex, whose default sandbox is `workspace-write`.
Set the MCP server's launch working directory to your intended repository in
your client configuration; the server uses its own current directory, not a
negotiated client workspace. Clients differ in how they configure this.

`claude` is the default if `CLADE_RUNTIME` is omitted, and `auto` prefers Claude
when installed. The Claude runtime passes `--dangerously-skip-permissions`: use
it only with isolation you control. A client approval dialog does not sandbox
the spawned CLI. Codex also has an explicit bypass option; leave it unset for
this setup. See [runtime options](../mcp-package/README.md#runtime-selection). In the client's MCP tool view, call
`clade_list_skills`; the response should list skills and the selected runtime.
That call is a discovery smoke test, not a test of a coding task or repository
permissions. Do not mount MCP inside a client that already has Clade's native
surface.

## Optional Orchestrator

The Orchestrator is a separate FastAPI and web application. Native Claude and
Codex use do not need it. If you need its control plane, follow
[the Orchestrator guide](orchestrator.md), including its distinct startup ports
and web build step. Do not infer that a running web page means a worker has
executed or verified a task; inspect the task and evidence records.

## First workflow

Use a disposable branch and a small task with an existing test. Ask the agent to
inspect the repository, propose a change, implement it, and run the repository's
documented checks. Review the diff and any evidence before deciding whether to
commit or open a PR. Clade's delivery checks do not grant push, merge, or release
authority.

## Updating

- Claude framework: pull a reviewed Clade checkout and rerun `./install.sh`, then
  open a new session.
- Codex: follow [the plugin update helper](codex.md#updating-while-sessions-exist)
  when other threads are live; start a new thread after updating.
- MCP: keep `"command": "uvx"` and temporarily set
  `"args": ["--upgrade", "clade-mcp"]`, then restart the client. This permits
  a package upgrade on launch. Restore `"args": ["clade-mcp"]` after checking
  the new version so normal launches do not request upgrades.

## Troubleshooting

**A skill is missing.** Start a fresh agent session. For Claude, rerun the
installer and check `~/.claude/skills/`; for Codex, check the marketplace and
`/hooks`; for MCP, call `clade_list_skills` and inspect `CLADE_RUNTIME`.

**Hooks did not appear.** Confirm `jq` is installed, rerun `./install.sh`, and
inspect the managed section of `~/.claude/settings.json`. Do not replace the
whole settings file with a copied example.

**The wrong runtime runs.** MCP uses `CLADE_RUNTIME`; `auto` prefers Claude when
available. Native Claude and Codex surfaces do not need MCP and should not be
combined with it.

**The Orchestrator page is 503.** Build its frontend as described in
[its guide](orchestrator.md); `orchestrator/start.sh` and a bare `uvicorn`
command use different default ports.

**A task says it is done but the result is uncertain.** Inspect the diff, run the
repository's real checks, and review evidence. A green-looking report is not a
substitute for the repository's own acceptance criteria.

## Further reading

[When to Use What](when-to-use-what.md) maps goals to skills. [How It Works](how-it-works.md)
explains hooks and evidence. [CONTRIBUTING](../CONTRIBUTING.md) covers source
changes, tests, and community reports.
