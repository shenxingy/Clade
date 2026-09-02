**English**（中文版尚未提供 — [README 中文版](../README.zh-CN.md)）

← Back to [README](../README.md)

# Orchestrator Web UI

## Table of Contents

1. [Overview](#overview)
2. [Trust Pipeline](#trust-pipeline)
3. [Control Plane](#control-plane)
4. [GUI Settings Reference](#gui-settings-reference)
5. [Broadcast to All Workers](#broadcast-to-all-workers)
6. [Iteration Loop (Autonomous Refinement)](#iteration-loop-autonomous-refinement)

---

## Overview

**Identity + evidence + evaluation + delivery + fleet truth.** The Orchestrator
is an optional control plane around native Claude Code and Codex workers. It
resolves a secret-free connection identity, records append-only attempt
evidence, calibrates verifiers, and tracks exact delivery state across projects.

The web UI shows queues, workers, provider catalogs, evidence/eval health,
usage, and delivery state. Task and settings mutations are explicit control
actions; viewing a green card never grants publish or merge authority.

Claude/Codex runtime selection is distinct from the inference provider, native
profile, wire protocol, and model. The Orchestrator stores references and
provenance, not credentials.

```bash
cd orchestrator && ./start.sh
# → Opens http://localhost:8765 in your browser
```

The FastAPI backend requires Python 3.9+. The React UI must be built —
`start.sh` does it for you on first run, or `cd orchestrator/web && npm ci &&
npm run build` by hand. Until it is built, `/web` answers 503 naming that
command and `/` redirects there; the API itself is unaffected. There is no
longer a legacy fallback UI: the pre-Vite `app-*.js` files were removed once
`index.html` became the Vite shell, which had left the fallback serving a page
that could not boot.

Every route requires a bearer token — see
[Control-plane authentication](configuration.md#control-plane-authentication).

## Trust Pipeline

```
queued task
  → resolve runtime + native connection + provider + protocol + opaque model
  → execute in an isolated worker/worktree
  → append timing + Git SHA + test + oracle + cost + artifact evidence
  → quarantine failures, disagreements, reverts, and explicit corrections
  → human review may promote a sanitized regression fixture
  → exact-SHA delivery state follows CI, repository policy, and authority
```

Verifier-aware cheap→strong routing is default-off. It requires automatic
routing, a deterministic verifier contract, bounded low-risk ownership, and
replay evidence. Production break-even reports are observational and cannot
change routing policy.

## Control Plane

```
┌──────────────────────────────┬───────────────────────────────┐
│ Fleet                        │ Evidence + evaluation         │
│ projects / queues / workers  │ North Star / guardrails       │
│ provider catalogs / usage    │ quarantine / human review     │
├──────────────────────────────┼───────────────────────────────┤
│ Execution                    │ Delivery                      │
│ runtime / connection / model │ exact SHA / CI / PR topology  │
│ capability provenance        │ history semantics / cleanup   │
└──────────────────────────────┴───────────────────────────────┘
```

## GUI Settings Reference

Open the **⚙ Settings** panel (top-right of the Web UI) to configure:

| Setting | Default | Effect |
|---------|---------|--------|
| Auto-start workers | ON | Workers launch immediately when `proposed-tasks.md` is written |
| Auto-push | ON | Push to feature branch after each commit |
| Auto-merge | ON | Queue or merge `orchestrator/task-*` PRs only after label, metadata, and repository-policy checks |
| Merge history | `auto` | Live child topology → merge commit; one coherent commit → rebase; ambiguous multi-commit history stops for an explicit choice. Squash requires explicit/sole-policy semantics |
| Auto-review | ON | Post AI code review comment on each PR |
| **Oracle validation** | OFF | Haiku independently reviews each diff before push — catches "completed but wrong" silently; rejects bad pushes |
| **Auto model routing** | OFF | Picks model by scout score: score ≥80 → haiku, 50-79 → sonnet, <50 → sonnet + ask-first warning |
| **Context budget warnings** | ON | Token bar on every worker card (green → amber at 120K → red at 160K); writes `.claude/context-warning-{id}.md` with `/compact` instructions |
| **AGENTS.md → Generate** | — | Builds file→branch ownership map from `git log`; copy output to `.claude/AGENTS.md` to prevent cross-worker collisions |
| **Webhook secret** | _(empty)_ | HMAC-SHA256 secret for `POST /api/webhooks/github`. **Security note:** if left empty, the endpoint accepts all requests — set this before exposing the orchestrator to the internet |

## Broadcast to All Workers

When all running workers need the same correction mid-run, use the **→ All Workers** bar visible at the top of the workers section in Execute mode:

```
Example: "The DB schema changed — column is now user_id not userId"
→ All running workers stop, receive the message as prepended context, and restart
```

Useful when you realize a global constraint changed and every worker needs to know.

## Iteration Loop (Autonomous Refinement)

Closes the review → fix → verify feedback loop for any iterative artifact (papers, code audits, content QA).

```
1. Execute mode → Loop section
2. Enter: artifact path = paper.tex  (or server.py, README.md, etc.)
           codebase dir = ./src       (optional, for DATA_CHECK workers)
           K = 2, N = 3               (converge when ≤2 changes for 3 consecutive iters)

3. ▶ Start Loop — the supervisor:
     FIXABLE   → spawns a worker to fix it automatically
     DATA_CHECK → spawns a read-only worker to verify a claim against your codebase
     DEFERRED  → adds to the accordion below (requires human review — never auto-fixed)
     CONVERGED → loop ends, toast fires

4. After all workers finish → count changes → check convergence → repeat
5. Converged? Review deferred items in the accordion.
```

The loop runs fully unattended. Set `max_iterations` in Settings as a safety cap.
