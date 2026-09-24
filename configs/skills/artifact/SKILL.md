---
name: artifact
description: "Write a single-page HTML report artifact that a PhD, a PM and an engineer can read at a glance — a research finding, status report, architecture page, RCA, handoff or work-log — with the section spine, publication-quality figures, colour tokens for both themes and a mechanical lint (artifact-lint.py) run before it is published to an artifact hub or as a Claude Artifact."
when_to_use: "write an artifact page, report page, research finding page, status report page, RCA page, handoff page, paper-quality figure, chart colours for a report, architecture diagram for a report, 写artifact, 发一个artifact, 做一页报告, 研究报告页, 汇报页面, 论文图, 图表配色, 架构图页面 — NOT for a whole-system cross-repo landscape (use /landscape), the hub publishing mechanics alone (use /internal-deploy), product UI or a marketing site (use /frontend-design), or a blog chart (use /blog-chart)"
argument-hint: '[type: finding|status|architecture|rca|handoff|decision|reference|worklog] [source files or notes]'
user_invocable: true
---

# Artifact

One page that answers, from its first screen, what the problem is now, how
sure we are, and what the next step is — then carries the evidence. The
executable instructions live in `prompt.md`; this body is the Codex-facing
summary.

## What it does

1. Reads the brief and fixes the page's type, reader question and publish
   target; resolves the organisation's design system before styling anything.
2. Collects every number with its source, population, window and date, and
   grades each claim verified / inferred / speculation.
3. Writes the spine for the type (`references/spines.md`), picking parts from
   the element inventory of the strongest published reports, slides and decks
   (`references/anatomy.md`): a headline that
   is a finding, a ≤120-word deck, a number strip with denominators, a graded
   verdict, a key-and-terms section with one colour per entity, claim
   headings with eyebrow labels, and the back matter — what did not work,
   limits and claims not made, one next step with an owner, sources and
   reproduction, what the page does not cover.
4. Draws the one to three figures the page turns on (`references/figures.md`)
   and, for architecture pages, C4 context and container diagrams with a
   legend (`references/diagrams.md`) — inline SVG, tokens for both themes,
   captions that state the takeaway.
5. Runs `python3 ~/.claude/scripts/artifact-lint.py <page>` and fixes every
   FAIL and WARN (or writes the reason on the page), then screenshots the
   page in light and dark before publishing.

## Usage

```
/artifact finding notes/v9-xref.md          # a research result page
/artifact status                            # where the project stands, from the repo + hub
/artifact architecture apps/halo            # as-built system page with C4 L1 + L2
/artifact rca incident-2026-09-21.md        # post-mortem in the SRE field order
/artifact worklog                           # the living Goal · Now · Human TODO · Blockers page
```

Publishing goes through `/internal-deploy` (hub) or the Artifact tool
(Claude Artifacts); this skill owns what is on the page, not where it lands.
