---
title: "Anthropic, 'The components of agent memory' — read against Clade: the dream ships natively, is switched off here, so we ran one by hand"
date: 2026-11-09
review_date: 2026-12-09
status: needs_work
summary: >
  The owner asked to learn from Anthropic's post on agent memory (Lance Martin,
  2026-11-06: capture salience in-session, "dream" offline to correct notes against
  transcripts, build linked representations, keep the always-loaded layer small, one
  writer per page). A 36-agent sweep mapped 11 components onto Clade and native Claude
  Code 2.1.283, measured the live memory, and attacked every claimed gap twice. Result:
  1 of 10 survived (Workflow agents overwrite each other's scratch files), and the
  post's central mechanism already ships natively — Claude Code's auto-dream — but is
  switched off server-side on this account, so `autoDreamEnabled: true` does nothing.
  Its absence is measurable: 12 of Clade's 32 project memories were stale, wrong or
  contradicted a CLAUDE.md, one of them in the always-loaded index for ~55 days. A
  hand-run dream fixed them; the store now ignores the dream's lock and session logs.
integrated_items:
  - "Hand-run dream of Clade's own project memory (2026-11-09): 21 topic files and the MEMORY.md index corrected against the repo and both CLAUDE.md files; every index line ≤ ~150 chars; no deletions (outside the repo — the dotfiles sync store)"
  - "Sync store ignores Claude Code's auto-dream lock (.consolidate-lock) and session logs (projects-memory/*/logs/); sync-health uses the native index cap of 25,000 characters (branch fix/memory-store-native-dream)"
  - "Workflow rule: name each agent's own scratch sub-directory in its brief (branch docs/workflow-scratch-per-agent) — the one gap that survived both refuters"
needs_work_items:
  - "Re-audit Clade's memory on 2026-12-09 and decide whether a scheduled reconcile is worth building (TODO § 2026-11-09 agent memory)"
  - "memory-staleness.sh resolves the memory dir from the transcript dir, not the git root Claude Code uses — wrong for 120 of 463 sessions; latent while no memory declares anchors"
reference_items:
  - "COVERED natively — C4 salience and a small index, C5 'say what memory is for' (no fixed write rule), C7 a [[link]] wiki with an index, C8 the 200-line / 25,000-character index cap"
  - "COVERED by Clade — C8 for rules (auto-audit's 40 KB promotion budget, promoted-archive.md, path-scoped rules), C10 cross-session patterns (auto-audit, friction-rank, harness-usage, radar)"
  - "REFUTED with reopen conditions — C1-G1, C2-G1, C3-G1, C3-G2, C6-G1, C8-G1, C9-1, C10-G1, C11-G1 — see the table"
---

← [Research index](README.md)

# "The components of agent memory", read against Clade

## Verdict

**The post's central tool — an offline "dream" that checks notes against the record
and keeps the index small — already ships in Claude Code, and it is switched off on
this account. Clade does not build its own; it ran one by hand, made the sync store
safe for the native one, and fixed the one coordination gap the post's evidence
predicts.**

- **Native, but off.** Claude Code 2.1.283 carries a background consolidation
  ("auto-dream", setting `autoDreamEnabled`). Its gate reads a server flag first
  (`tengu_onyx_plover`); all five cached copies on this host say
  `{"enabled": false, "minHours": 24, "minSessions": 3}`, so the setting is never
  read. No `.consolidate-lock` exists under any config dir or the store, and none is
  in the store's 738-commit history: it has never run here.
- **What its absence costs, measured.** Of Clade's 32 project memories, 12 were
  defective — 5 stale, 2 wrong, 5 contradicting a CLAUDE.md — and 8 of the 32
  always-loaded index lines were too. One had carried a fire rate CLAUDE.md declares
  unreproducible ("~17%") for about 55 days. Fixed by a hand-run dream that applied the
  native prompt's own rules; the agent that applied it re-checked the audit first and
  upheld 20 of its 21 points.
- **One gap survived.** Workflow agents share one session scratchpad and pick
  conventional file names: 24 of 560 runs had live agents writing the same path
  (the post's shared-table result: 41 of 57 facts kept, 57 of 57 with one writer per
  page). The global template now tells the lead to name each agent's sub-directory.
- **Nothing else is a gap.** Nine other candidates fell to a refuter, most to "fix the
  content, not the mechanism" — which the hand-run dream did.

## What the post says, in one paragraph

Memory is knowledge from experience kept between sessions as readable context — not
weights, not in-context learning, not compaction. Writing a note is a prediction that
it will matter; stronger models close the loop (record the failure, test a theory,
write the rule and how it was confirmed) and save only what the environment will not
show again, so their memory stays small (Pokémon: 413 files and one badge against
nine files and four). Tell the model what memory is for, not how: a fixed "record only
failures" rule cut the memory gain for the strongest models. Because in-session
salience is a guess, an offline pass — dreaming — re-reads the transcripts, corrects
notes, builds linked pages (useful for questions that span documents, useless when
one document answers; a wiki can grow larger than its source), keeps the injected top
layer small, and repairs dangling links. One agent per page, quoting rather than
summarising, beat several agents overwriting one shared table.

## The components against Clade

Verdict "refuted" means the claimed gap did not survive both refuters: one looking for
an existing mechanism, one asking whether closing it would change an outcome here.

| id | Component | Where it lives here | Verdict | Reopens when |
|---|---|---|---|---|
| C1 | Memory ≠ compaction | Native keeps compact, extract-memories and dream apart; Clade's stores are distinct | refuted (C1-G1: `session-context.sh` re-injects a compact-state that never holds a task; bytes, not behaviour) | A session acts on another session's compact-state |
| C2 | Capture salience in-session | Native typed notes, "record from failure AND success"; Clade adds failure-only channels (corrections, revert, /learn) | refuted (C2-G1: notes do not link to their writing session) | A wrong note is found whose source session would have settled it |
| C3 | Loop with provenance: test, then write the rule and how it is known | Native rule + Why; `/handoff` marks UNCONFIRMED; `anchors:` (#211) can mark "verified at commit X" | refuted (C3-G1: no writer declares anchors; C3-G2 already filed — rules are never tested) | The 2026-12-09 re-audit finds defects anchors would have caught |
| C4 | Salience: keep what the world will not re-show; small memory | Native "What NOT to save"; store median 5 files per project, largest index 97 lines | covered natively | An index nears either cap (`sync-health.sh` warns at 80%) |
| C5 | Say what memory is for, not how | Clade gives the main thread no memory-write rule; native prompt only | covered (different, not deficient: four agent bodies carry failure-leaning save lists, no outcome data) | Those agents' memories are measured |
| C6 | Dream: correct notes against transcripts | Native auto-dream — off here; Clade's anchor check never fires (0 of 980 files declare anchors) | refuted as a Clade build (C6-G1); done by hand today; C6-G2 dropped by the cap | The account flag opens, or the re-audit shows decay |
| C7 | Linked representations (wiki) | Native [[links]] + index; 830 of 980 memory files link; docs/research index | covered; GC-C7-1 (no link maintenance) dropped by the cap, one instance fixed by hand | A multi-document question is answered wrongly for want of a page |
| C8 | Promote up, keep the top layer small, leave links | auto-audit 40 KB budget, promoted-archive.md, path-scoped rules; native index cap | covered for rules; C8-G1 refuted — already filed (TODO 2026-10-24: the global file is 42,499 chars) | That item closes |
| C9 | One writer per page; reflect on failures to fix the build instructions | Ledgers are appends under a lock or a PR; rules.md / MEMORY.md merge as union | **C9-2 survived** (scratch collisions); C9-1 refuted (`stats.json` loses increments under `-X ours`, no outcome changed) | Concurrent same-path Writes stay above 0 after the rule |
| C10 | Cross-session gap filling | auto-audit cross-project, friction-rank, harness-usage, radar; index pointers 0 dangling of 975 | refuted (C10-G1: [[link]] to a superseded note; the one instance fixed by hand) | A second superseded-link instance is found |
| C11 | When to write; cadence by volatility and access | Native dream: fixed 24 h / N sessions; reads concentrated (Gini 0.93) | refuted (C11-G1: nothing helps choose anchors) | Same as C6 |

## The native auto-dream, decoded

Read from the 2.1.283 binary (`~/.local/share/claude/versions/2.1.283`), confirmed by
the lead where marked †.

- **Gate.**† `Lje()` returns false unless `tengu_onyx_plover.enabled` or `.available`
  is true; only then does it read `autoDreamEnabled`. Also off for SDK entrypoints
  (`sdk-cli` and friends), `--bare`, remote sessions and hooks-off settings.
- **Cadence.** At least `minHours` (24) since the last run and `minSessions` (3 on this
  account's flag, default 5) transcripts touched since, then a lock:
  `.consolidate-lock` in the memory dir, holding the PID; its mtime *is* the
  last-consolidated time, and it is left in place after a success.
- **The prompt.**† "Dream: Memory Consolidation": orient (list the dir, read the
  index), gather (session logs under `logs/YYYY/MM/DD/`, drifted memories, a narrow
  grep of transcripts), consolidate (merge, absolute dates, delete contradicted facts),
  prune and index (≤ 200 lines, ~25 KB, one line ≤ ~150 chars), and reconcile against
  CLAUDE.md (a stale memory is fixed; a stale CLAUDE.md is only annotated). Shell is
  read-only plus `rm` of `.md` files in the memory dir.
- **Index cap.**† `MEMORY.md` is cut at 200 lines or 25,000 characters of the trimmed
  text (`Z3=25000`, compared with the string's length) — not 25 × 1,024 bytes, which
  `sync-health.sh` had assumed.
- **Age warning.**† A recalled topic file gets "This memory is N days old … verify
  against current code" when its **mtime** is more than a day old. Index lines never
  get it, and the store resets mtime: a pull or an adoption copy writes the file anew.
  A note whose `modified:` says 2026-09-02 carried the 2026-11-07 mtime of its adoption
  and read as two days old on 2026-11-09. Filed, not fixed (TODO).
- **On this host's store**, had the flag opened: the lock is per-host state that
  `sync-push.sh` would have committed, and a pull on another machine resets its
  mtime — the dream clock. Session logs would have been pushed to GitHub. Both are now
  ignored. Still open: `MEMORY.md` merges as `union`, so a line one host's dream prunes
  can come back from another host's edit (shown on a scratch repo); each profile's
  dream sees only its own transcripts.

## Measured baseline (2026-11-09, this host)

| Quantity | Value | Population · command |
|---|---|---|
| Defective Clade project memories | 12 of 32 files (5 stale, 2 wrong, 5 contradict a CLAUDE.md); 8 of 32 index lines | every topic file in the Clade store key, against repo HEAD 1825984 and both CLAUDE.md files; hand audit; the fixing agent re-checked it first (20 of 21 points upheld) |
| Longest-lived wrong note in the always-loaded index | ~55 days ("fires 17%") | `git log -L` on CLAUDE.md's red-phase paragraph vs the index line |
| Memory files that declare `anchors:` | 0 of 980 | every topic `.md` in the 60 store dirs, `grep -l` |
| Sessions that read / wrote a memory topic file | 135 / 102 of 463 (29% / 22%) | main-thread transcripts, 30 days, all profiles, symlinks deduplicated (`transcripts.py`). The 2026-11-07 figure (163 / 126 of 593) could not be re-derived |
| Store topic files never read in 30 days | 845 of 980 (86%); reads Gini 0.93; top 20 files = 51% of reads | same sessions |
| Topic files rewritten in a later session | 13 of 167 (8%); 0 deleted | files written in those sessions |
| Index lines over 150 chars | 832 of 1,122 across 59 indexes; 0 indexes over either cap (largest 97 lines, 17,778 chars) | every `MEMORY.md` in the store |
| Workflow runs with live agents writing one path | 24 of 560 multi-agent runs; 26 full-file Writes onto another agent's file | every `subagents/workflows/wf_*` run dir, 2026-10-08 → 11-09; overlap of writer lifetimes |

## Evidence from the post (Anthropic's own evaluations; populations as stated there)

- CL-Bench 1.0 database task: Opus 5, Opus 5.5 and Sonnet 5.5 close the
  failure → theory → tested rule loop; Sonnet 4.6 leaves untested guesses. A
  "record only failures" rule removed much of the memory gain for Opus 5 and 4.7;
  prompting Sonnet 4.6 to read memory first and test theories nearly doubled its
  score. Sonnet 5 read memory unprompted 9 of 10 times.
- Pokémon Red at ~10,000 steps, one run each: Sonnet 3.7 kept 413 files in 225
  folders (one badge); Fable 5 nine files, two folders and a `global.md` (four).
- A 350,000-file, ~420M-token internal corpus, 25 questions: dreaming over 2 → 128
  sessions took wiki-only answers from 13% to 48% of graded criteria; search plus wiki
  reached 61% against search alone at 53%, saving ~20,000 tokens per question.
- A merger document set, 24 questions (most multi-document): 87% with the wiki, 73%
  with search alone. A single-document legal brief: no gain. One wiki grew larger than
  its sources.
- Contract terms in a LAB task: several agents on one shared table kept 41 of 57
  graded facts; one agent per contract quoting terms word for word kept 57 of 57.

## How we would know we are wrong

- **Decay.** Re-run the hand audit on 2026-12-09. Twelve defects accumulated over
  roughly ten weeks; if four or more of the files present then are defective again, a
  scheduled reconcile is worth building (TODO). Fewer, and a monthly hand pass is
  enough.
- **The flag opens.** When any cached `tengu_onyx_plover` reads `enabled: true`, the
  native dream starts on its own; decide then about the `union` resurrection and
  whether one profile should own the dream.
- **Scratch collisions.** Re-run the overlap count over Workflow runs started after the
  template change; if concurrent same-path Writes do not fall toward zero, move the rule
  into `check-workflow-script.py` as a warning.

## Provenance

- Post: <https://www.anthropic.com/research/components-of-agent-memory>, published
  2026-11-06, written by Lance Martin; fetched 2026-11-09. The text is not committed.
- Binary: Claude Code 2.1.283, the version installed on the author's host.
- Measurements: a 36-agent Workflow run (11 component maps, 4 measurements, 20
  refuters, 1 completeness critic) on 2026-11-09; the lead re-checked the flag values,
  the gate, the prompt, the index cap, the store history and one scratch-collision
  instance by hand.
- Not measured: the owner's Mac (its account flag, its transcripts); whether the
  corrected memories change any later session's behaviour.
