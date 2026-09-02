# Progress Log

> **Role: a dated journal — what happened, when.** Entries are history and are
> not stale by virtue of being old; do not read them as current state. Open work
> lives in [TODO.md](TODO.md). Decided 2026-08-29.

Older entries live in [docs/progress-archive/](docs/progress-archive/) — 60 archived, newest month first.

---
### 2026-08-30 — Software-Fundamentals Review (Ng, *AI Engineering Skills Map*)

Read the article's five areas against this repository and checked each claim
against the tree rather than agreeing with it in prose. Most of it described
things already in place; one item was a real hole.

- **Shipped (`#88`):** four GitHub Action references were pinned to mutable
  tags while eight others carried full commit SHAs — and the four were both
  `uses:` in `pr-honeypot-check.yml` and both in `vouch-gate.yml`, the two
  workflows that run on `pull_request_target` with `issues: write` /
  `pull-requests: write` against fork PRs. That is the one context where a
  moved tag executes attacker-influenced code holding this repository's write
  token. `configs/scripts/check-action-pinning.py` now fails CI on any
  unpinned reference; local `./` actions are exempt and `docker://` is
  reported rather than silently passed.
- **Measured and rejected — database indexing.** The `tasks` table declares no
  index and `WHERE status = …` is its dominant filter, so `EXPLAIN QUERY PLAN`
  reports `SCAN tasks`. The largest real `tasks.db` on this machine holds
  **12 rows**. Indexing that is the premature abstraction this repository's
  engineering values warn against, so nothing was changed. Recorded here so
  the finding is not rediscovered and "fixed" later.
- **Assessed as already covered:** system architecture (strict import DAG with
  a CI gate, file-size limits, architecture-map coverage), testing strategy,
  security and reliability (the 2026-08-29 wave), and production operation
  (`event_stream`, `tracing`, and `notification_webhook` alerting on
  run_complete / high_failure_rate / loop_converged).
- **Deferred, with the decisions written down rather than left in a
  conversation:** see the two 2026-08-30 entries in [TODO.md](TODO.md).

---
### 2026-07-29 — Delivery Lifecycle Hardening + Loop Checkpoint Recovery

- Added a safe `abandon` transition to the `delivery` skill controller for
  superseded, unpublished work: an exact-head lease, a non-empty reason, and
  idempotency only for the same head+reason. Published GitHub PR work may
  abandon only after a live forge check proves the PR is CLOSED (not OPEN or
  MERGED) at the recorded head; abandonment terminalizes the branch lease
  without deleting work (`9975895`).
- Hardened abandonment to discover PRs by the recorded branch instead of
  trusting a possibly-stale `published` flag: an unrecorded OPEN PR now blocks
  abandonment, and an unrecorded MERGED PR at the exact recorded head is
  flagged for reconciliation rather than mislabeled abandoned (`26e88ec`).
- Fixed `PATCH /api/tasks/{id}` to revalidate the effective persisted
  connection against the effective runtime whenever either `connection` or
  `agent_runtime` changes, not only when a fresh `connection` value is
  supplied — an invalid connection/runtime pairing is now rejected at
  mutation time instead of first failing at task execution (`c5a5c92`).
- Made `loop-runner.sh` checkpoint recovery crash-safe and explicit: only an
  identity-matched `--resume` restores a checkpoint, a normal launch ignores a
  stale one, and `--help` has no side effects (`25949fe`).
- Refreshed the installed Codex plugin cache version for the delivery workflow
  changes that preceded Loop recovery (`8d93e1e`); Loop itself is distributed
  through Claude/MCP and was installed separately from merged `main`.
- The documentation convergence Loop reproduced a follow-on control-flow gap:
  workers committed and verified the requested state, but the coordinator left
  all 5 goal checkboxes open and exited `stuck_no_commits`. The unsafe
  worker-side marking experiment remains retired; a coordinator-owned,
  phase-safe replacement is promoted to the P0 follow-on in `TODO.md`.

---
### 2026-07-28 — Local Rollout + Research Program Closeout

- Installed merged `main` into this server's Claude and Codex user
  distributions; source-parity and preservation assertions passed without
  printing credential or connection values.
- Expanded the local Orchestrator settings through the canonical loader/saver:
  current runtime, connection, provider, and semantic merge fields are present;
  the retired `worker_provider` field is absent; the file is owner-only.
- Refreshed the installed Clade Codex plugin from the repository source with a
  cache-busted version, pruned stale remote-tracking refs, and closed every
  unconditional item promoted by the July expert/project re-screen.

---
### 2026-07-28 — Provider-Neutral Positioning + Truthful Merge History

- Repositioned English/Chinese public docs around native Claude/Codex/MCP
  surfaces and shared identity, evidence, evaluation, delivery, and fleet
  contracts without implying that evidence grants publication authority.
- Documented human-grounded correction pairing and corrected stale
  Claude-only/Hermes migration claims.
- Replaced Orchestrator's hard-coded squash merge with live policy:
  merge-commit for child topology, rebase for one coherent commit, explicit
  choice for ambiguous multi-commit history, and exact-head locking for every
  automated merge.

---

### 2026-03-01 — Loop: docs-review-goal

Docs accuracy sweep: cleared BRAINSTORM.md, fixed Phase 8/9 ordering in TODO.md, updated session-report filename format, updated VISION.md skills list, updated CLAUDE.md file map.

