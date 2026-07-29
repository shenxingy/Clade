===TASK===
model: gpt-5.6-terra
timeout: 600
retries: 1
TYPE: VERTICAL
Feature: Wave 0 — Truthful Backlog
---
Reconcile Brainstorm and TODO backlog state

OWN_FILES: BRAINSTORM.md, TODO.md, docs/research/README.md
FORBIDDEN_FILES: orchestrator/**, configs/**, mcp-package/**, plugins/**

Files to edit:
- BRAINSTORM.md
- TODO.md
- docs/research/README.md

Pattern to follow: BRAINSTORM.md resolved sections — preserve historical
evidence, add dated RESOLVED/SUPERSEDED dispositions, and do not delete the
research record.

Implementation:
1. Reconcile all 44 unchecked Brainstorm boxes against landed commits and the
   2026-H2 implementation plan.
2. Mark 33 implemented/superseded items with exact disposition evidence.
3. Keep the Beads note-to-self item as a conditional watch trigger.
4. Promote the accepted execution program into TODO.md with dependency/status
   labels; retain MCP v2 as the first P0 item.
5. Update the research index review date and honest open-backlog summary.

Edge cases:
- Do not mark automatic draft-PR publication as implemented; record it as
  rejected-by-authority-design.
- Do not duplicate universal harness Phases 0–2, which landed in PR #34.

Acceptance criteria:
- BRAINSTORM.md contains no stale unchecked boxes for landed work.
- TODO.md contains only real executable work or explicit conditional items.
- Every resolved historical cluster cites its landed/superseding mechanism.
===TASK===
model: gpt-5.6-sol
timeout: 900
retries: 1
TYPE: VERTICAL
Feature: Wave 0 — MCP SDK v2
---
Migrate both MCP servers to Python SDK v2

OWN_FILES: orchestrator/mcp_server.py, mcp-package/src/clade_mcp/server.py, orchestrator/requirements.txt, mcp-package/pyproject.toml, orchestrator/tests/test_mcp_compact.py, orchestrator/tests/test_clade_mcp_runtime.py, orchestrator/tests/fixtures/**, tests/test-install.sh
FORBIDDEN_FILES: BRAINSTORM.md, TODO.md, orchestrator/event_stream.py, configs/scripts/equip_**

Files to edit:
- orchestrator/mcp_server.py
- mcp-package/src/clade_mcp/server.py
- orchestrator/requirements.txt
- mcp-package/pyproject.toml
- MCP runtime and install tests

Pattern to follow: MCP Python SDK v2 migration guide and
examples/mcpserver/readme-quickstart.py at tag v2.0.0 — use v2 handler
registration and stdio serving while preserving Clade's compact/full modes.

Implementation:
1. Replace v1 low-level decorator registration with the v2 `on_*` handler
   surface or a shared `MCPServer` implementation.
2. Preserve list/search/run skill behavior, structured tool results, and stdio.
3. Raise the dependency to `mcp>=2,<3`; keep Clade's own `httpx` dependency
   explicit where still imported.
4. Update both source surfaces and package/install tests.
5. Verify v2 serves legacy protocol clients through built-in negotiation.

Edge cases:
- V2 low-level handlers no longer auto-wrap bare list/dict results.
- Python model field access is snake_case even though wire aliases remain
  camelCase.
- Stray stdout must not corrupt stdio MCP traffic.

Acceptance criteria:
- Both MCP servers import and start under SDK v2.
- Compact and full discovery/tool-call tests pass.
- No `mcp<2` compatibility bound remains.
- Install/package verification passes.
===TASK===
model: gpt-5.6-terra
timeout: 600
retries: 1
TYPE: VERTICAL
Feature: Wave 0 — Equipment Security
---
Re-screen upstream content during equip sync

OWN_FILES: configs/scripts/equip_sync.py, configs/scripts/equip_audit.py, configs/skills/equip/**, tests/test-equip*.sh, orchestrator/tests/test_equip*.py, plugins/clade/skills/equip/**, mcp-package/skills/equip/**
FORBIDDEN_FILES: orchestrator/event_stream.py, orchestrator/mcp_server.py, BRAINSTORM.md, TODO.md

Files to edit:
- configs/scripts/equip_sync.py
- configs/scripts/equip_audit.py
- equip tests and generated skill copies

Pattern to follow: configs/scripts/equip_common.py pinned-ref/current-commit
helpers — bind every audit decision to the exact fetched commit.

Implementation:
1. Record the audited upstream commit in the audit report.
2. At sync/apply time compare fetched HEAD to that audited commit.
3. If it differs, re-run prompt-injection/red-flag screening or block apply
   until a new report is accepted.
4. Preserve dry-run behavior and explicit `--apply` consent.
5. Regenerate derived skill copies.

Edge cases:
- Tags moving after audit.
- Offline cache with no reachable remote.
- Existing audit reports without a commit field must fail closed on apply but
  remain readable in dry-run mode.

Acceptance criteria:
- `sync --apply` cannot write unaudited upstream drift.
- Dry-run explains the exact audited/fetched SHAs.
- Existing accepted unchanged commits still sync normally.
===TASK===
model: gpt-5.6-sol
timeout: 900
retries: 1
TYPE: VERTICAL
Feature: Wave 1 — Safe Evidence Substrate
---
Redact runtime events before persistence

OWN_FILES: orchestrator/runtime_redaction.py, orchestrator/event_stream.py, orchestrator/worker.py, orchestrator/worker_provider.py, orchestrator/tests/test_runtime_redaction.py, orchestrator/tests/test_event_stream.py
FORBIDDEN_FILES: orchestrator/mcp_server.py, mcp-package/**, configs/scripts/equip_**, BRAINSTORM.md, TODO.md

Files to create/edit:
- orchestrator/runtime_redaction.py
- orchestrator/event_stream.py
- provider stdout/stderr persistence call sites
- focused tests

Pattern to follow: configs/scripts/redact.py high-signal secret detection plus
EventStream's existing append-before-memory crash-safety order.

Implementation:
1. Add a leaf, field-aware recursive sanitizer for JSON-compatible event data.
2. Redact sensitive keys, credentials, authorization headers, private endpoint
   query strings, and configured path patterns before serialization.
3. Record policy version and redaction count without retaining originals.
4. Apply the same boundary to persisted provider stdout/stderr.
5. Preserve event replay and corrupt-line handling.

Edge cases:
- Already-redacted input must be idempotent.
- Arbitrary strings/non-JSON values must not crash event emission.
- Avoid broad patterns that destroy useful stack traces.

Acceptance criteria:
- Canary secrets and private paths never appear in JSONL/SQLite/log fixtures.
- Replay produces sanitized events with intact causal metadata.
- Existing event-stream behavior remains compatible.
===TASK===
