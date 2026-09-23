# Progress Log

> **Role: a dated journal — what happened, when.** Entries are history and are
> not stale by virtue of being old; do not read them as current state. Open work
> lives in [TODO.md](TODO.md). Decided 2026-08-29.

Older entries live in [docs/progress-archive/](docs/progress-archive/) — 65 archived, newest month first.

---
### 2026-09-23 — The artifact standard: a spine, a lint, and a survey of 1,032 pages

The owner asked why hub pages "lack content or state things unclearly" and
how the most-published colleague's pages differ. Measured, not guessed: over
926 report pages 72% have no next-step section, 69% no limits, 53% no key or
terms, 32% carry a figure, and 2 pass every check — hub-wide, not personal.
The strongest pages share one decoded shape (claim headline, number strip
with denominators, graded verdict, colour key and terms, claim headings,
reading lines under tables, an instruction as the close). Shipped as the
`/artifact` skill with three references, `artifact-lint.py` (22 checks,
bilingual, `--survey`, 17 pinned mutations), a path-scoped rule, and an
internal exemplar page rendered in both themes. Study:
docs/research/2026-09-23-artifact-standard.md.

---
### 2026-09-18 — Kimi quota in the footer, through the documented door

The 2026-09-17 note said Kimi had no usage API and declined to build one on
principle. Two REST guesses had been read as a survey; the reference lists
`GET /api/v1/oauth/usage` on `kimi web`, with the schema. So `/kimi-usage` and
a `[status_line]` footer now exist on the same shape as `codex-usage`: the
product's own local server, its own loopback token, reuse-or-spawn, and the
OAuth credential file untouched — Kimi rotates refresh tokens under a lock
with a tombstone on conflict, which is the concrete reason, not just the rule.
Verified in a real Kimi 2.0.1 TUI; the render path is ~40 ms inside the 300 ms
budget. Cost that remains: a refresh boots a ~600 MB server for ~2 s, at most
every five minutes while a session is active — the upstream payload PR that
would remove it is in TODO.md.

---
### 2026-09-12 — CI moved to hardware we already own, plus the fixer

The owner's standing position, said out loud again because nothing retained it:
hosted CI costs money, we have a Linux server and a Mac and a Windows box, and
the principle applies to every project. An auto-promoted rule already ended with
*"that is the ci-cost rule above"* — there was no ci-cost rule above. That is the
`standing-preference` class this repo added to its own taxonomy ten days
earlier: the tell is a repeat, not a defect.

- **Measured first.** Hosted CI bills per job, rounded up per job, Linux 1x /
  Windows 2x / macOS 10x. This repo's four jobs take 24s, 39s, 60s and 73s and
  bill **five** minutes. Clade is public, so its runners are free and the saving
  here is latency; the money is in the private repos. The policy therefore went
  in the **global** file, not this one.
- **Shipped `configs/scripts/ci-local.py` (#91).** Parses the workflow files and
  runs the same `run:` blocks, so it cannot drift from CI by construction —
  which matters because the hand-written checklist in `CLAUDE.md` drifted twice.
  5/5 jobs in ~180s.
- **Three defects found by running it, not by reasoning about it.** Inheriting
  the terminal's stdin hung a suite for 13 minutes at 9% CPU and produced five
  phantom failures. `actions/setup-python` had to be stood in for, because a
  distribution-managed Python refuses `pip install` under PEP 668. And a job
  whose every step was skipped reported as **passed** — the exact lie the tool
  exists to prevent.
- **Shipped `/green`,** the repair half. Its first rule outranks its goal: never
  weaken a gate to make it pass, with the cheats named.
- **Drilled it.** Removed `re.ASCII` from `redact.py` to reintroduce the CJK
  bypass. Five tests went red, the failing test named the cause, the fix
  restored the cause, net diff zero, no test file touched.

---
### 2026-09-02 — Full audit: eleven controls that existed and never applied

A whole-repository review, filed to [TODO.md](TODO.md) before any fix, then
implemented. The recurring defect had one shape: **a control that exists, is
documented as working, and never fires.** Found eleven times.

- **Security.** The orchestrator control plane had no authentication and
  `/ws/chat` started a permission-skipping PTY — unauthenticated RCE over the
  tailnet. Closed with default-deny ASGI middleware. Separately, `redact.py`
  used Unicode `\b`, so a key pasted in Chinese prose was never matched.
- **A retrospective scrub** (`scrub-corrections.py`). The filed item said two
  files; it was three, because two were `.bak-*` copies. A raw scan of JSONL
  also misses a key that begins a line. A census of 1,039 transcripts found 158
  occurrences.
- **Instruments that could not fire.** `prompt-tracker.sh` had never delivered a
  message in 386,760 prompts. `session-scorecard.sh` read a field present in 0
  of 983 records. `rule-effectiveness.json` is empty because the classifier
  emits thirteen closed labels (twelve domains plus `unknown`) while rules are filed under free text. `stats.json`
  held unresolved git conflict markers. The poll counter written the same day
  reported zero everywhere because its guard matched the `>/` of `2>/dev/null`.
- **Both new instruments now carry `--self-test`,** run in CI.
- **Encoded three standing briefs** that were being re-typed: `/landscape`, the
  recovered design methodology, and `install.sh --ultracode`. Added
  `standing-preference` to the correction taxonomy — the only class whose
  evidence is a count rather than an incident.
- **`docs/layers.json`** now declares which surfaces actually run, because this
  audit spent most of its effort on a layer switched off months earlier.

