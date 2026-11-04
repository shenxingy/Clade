[English](readme-media.md)

[Back to README](../README.md)

# README presentation and evidence

## Contents

- [Workflow diagrams](#workflow-diagrams)
- [Local check](#local-check)
- [Presentation references](#presentation-references)
- [Maintaining the entry points](#maintaining-the-entry-points)

## Workflow diagrams

The workflow and MCP bridge SVGs in `assets/` are original explanatory diagrams,
not screenshots of an agent session. They describe the current responsibilities:
Clade supplies workflow guidance, the selected assistant edits the project,
repository checks provide evidence, and delivery needs the relevant authority.
The Orchestrator is optional. See [layer status](layers.json).

Desktop and phone variants keep labels readable; the root README has English and
Chinese diagrams. The MCP package uses public raw asset URLs so its README can
also display outside GitHub. Those URLs pin the asset commit; update the pin
when changing the diagram. It shows task execution; listing skills does not
run the agent. The source-tree MCP bridge and OpenClaw adapter use separate
Mermaid diagrams because their execution paths differ from the published package.

The dark background and blue, green, and orange accents reuse Clade's existing
banner palette. The SVGs use text and vector shapes with no external resources,
script, or third-party artwork. Each has an accessible title and description;
README image alt text also explains the flow.

## Local check

From the Clade clone, without installing hooks or calling an agent:

```bash
python3 configs/scripts/check-layers.py
```

The check verifies declared layer paths and status, and that source directories
are covered by the map. In the run used for this README, it returned exit zero:

```text
check-layers: 6 layers declared and consistent — cli=load-bearing, orchestrator=dormant, mcp-package=generated, codex-plugin=generated, cc-plugin-agents=generated, openclaw-adapter=dormant
```

This is a real repository check. It does not demonstrate a complete coding
session, provider authentication, throughput, or automatic delivery. For your
first installed workflow, use [Getting started](getting-started.md#first-workflow)
and inspect the resulting diff and verification evidence.

## Presentation references

The research compared actual rendered entry points, not only README source or
image counts. Relevant patterns included:

| Reference | What it helps a visitor understand | Applied here |
| --- | --- | --- |
| [Aider](https://github.com/Aider-AI/aider) | A terminal demo shows what a coding tool does during use | Show workflow responsibilities and an actual runnable check; do not invent a chat transcript |
| [OpenHands](https://github.com/OpenHands/OpenHands) | A product view and task-oriented entry point explain the interface | Lead with the workflow and setup choice; do not portray the dormant Orchestrator as the main product |
| [Spec Kit](https://github.com/github/spec-kit) | A named workflow makes a multi-step tool easier to follow | Connect task, checks, and reviewable output in a compact diagram |
| [Superpowers](https://github.com/obra/superpowers) | Direct workflow prose can itself be useful | Keep instructions concrete and avoid adding decorative media to reference-only pages |

These are presentation references, not evidence that a layout increases
conversion or that popularity validates every product claim. No upstream
artwork or screenshots are copied into this repository.

## Maintaining the entry points

Edit diagrams when the execution path changes. Check root and language variants,
MCP package READMEs, the source bridge, and optional adapters according to their
actual audiences. Keep install prerequisites, permissions, first checks, help,
and the directory map consistent. Internal evaluation/archive READMEs remain
technical reference pages and do not need promotional headers.

Render the result at phone, tablet, and desktop widths, in light and dark themes.
Inspect image loading, text fit, full-size access, anchors and setup commands.
GitHub controls the page layout; diagrams supplement the accessible text rather
than replace it. The durable acceptance standard is in the
[document-release reference](../configs/skills/document-release/references/repository-entrypoints.md).
