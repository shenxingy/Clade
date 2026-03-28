# VERIFY — [Project Name]
<!-- Managed by /review skill. Edit checkpoint descriptions freely; statuses are updated by the agent. -->
<!-- Legend: ✅ pass  ❌ fail  ⚠ known limitation  ⬜ not yet tested -->

**Project type:** ai / ml
**Last full pass:** never
**Coverage:** 0 ✅, 0 ❌, 0 ⚠, 0 ⬜ untested

---

## Model I/O Contracts
<!-- Core input/output behavior must be stable and predictable. -->

| ID | Checkpoint | Status | Verified | Notes |
|----|-----------|--------|----------|-------|
| M1 | Standard input → output matches expected schema (fields, types, format) | ⬜ | — | |
| M2 | Empty / blank input → handled gracefully (validation error or safe default) | ⬜ | — | |
| M3 | Very long input (near/over context limit) → truncated or rejected, not crash | ⬜ | — | |
| M4 | Non-English input → handled per spec (supported or explicit error message) | ⬜ | — | |
| M5 | Structured output (JSON/code) → schema validated before use by caller | ⬜ | — | |

## Prompt Robustness
<!-- The system must behave consistently under adversarial or unexpected inputs. -->

| ID | Checkpoint | Status | Verified | Notes |
|----|-----------|--------|----------|-------|
| P1 | Prompt injection attempt → model follows system prompt, not injected instruction | ⬜ | — | |
| P2 | Off-topic / irrelevant input → polite refusal or redirect, not hallucination | ⬜ | — | |
| P3 | Ambiguous input → asks clarifying question or returns safe default | ⬜ | — | |
| P4 | Repeat-exact-same-input twice → consistent output (deterministic enough) | ⬜ | — | temp=0 needed |

## Output Validation
<!-- Every output must be validated before being used or shown to users. -->

| ID | Checkpoint | Status | Verified | Notes |
|----|-----------|--------|----------|-------|
| OV1 | Required output fields always present (no silent missing keys) | ⬜ | — | |
| OV2 | Code output: `ast.parse()` / syntax check before saving or executing | ⬜ | — | |
| OV3 | Numeric output: within expected range (no negative counts, no NaN) | ⬜ | — | |
| OV4 | Sensitive data (keys, PII) not included in output shown to users | ⬜ | — | |
| OV5 | Model exit code 0 with error message in output → detected and treated as failure | ⬜ | — | |

## Fallback & Resilience
<!-- The system must degrade gracefully when the model is unavailable or misbehaves. -->

| ID | Checkpoint | Status | Verified | Notes |
|----|-----------|--------|----------|-------|
| F1 | Model API unavailable → error surfaced to caller, no crash or silent failure | ⬜ | — | |
| F2 | Model timeout → caller receives timeout error within [N]s, not infinite wait | ⬜ | — | set N |
| F3 | Unexpected output format → validation catches it, fallback applied | ⬜ | — | |
| F4 | Retry logic: transient failures retried N times with backoff | ⬜ | — | |
| F5 | Budget / rate limit hit → request deferred with recoverable status, not dropped | ⬜ | — | |

## Pipeline Integration
<!-- The model output must correctly drive downstream processing. -->

| ID | Checkpoint | Status | Verified | Notes |
|----|-----------|--------|----------|-------|
| PI1 | Model output correctly drives downstream step (data flows end-to-end) | ⬜ | — | |
| PI2 | Intermediate state persisted correctly (resume possible after interruption) | ⬜ | — | |
| PI3 | Multiple pipeline runs don't produce duplicate records or side effects | ⬜ | — | |
| PI4 | Failed step is correctly marked and does not cascade to corrupt downstream | ⬜ | — | |

## Performance & Cost
<!-- Resource usage must stay within acceptable bounds. Establish baseline before setting targets. -->

| ID | Checkpoint | Status | Verified | Notes |
|----|-----------|--------|----------|-------|
| PC1 | P95 latency for typical input < [target] s (measure baseline on short/medium/long inputs separately) | ⬜ | — | set target |
| PC2 | Token usage for typical input within expected bounds (±20% of baseline) | ⬜ | — | baseline first |
| PC3 | Cost per run within budget for expected daily volume | ⬜ | — | |
| PC4 | GPU utilization and VRAM usage within safe range (if local model) | ⬜ | — | if applicable |

## Safety & Output Filtering
<!-- Model output must not harm users or leak sensitive data. -->

| ID | Checkpoint | Status | Verified | Notes |
|----|-----------|--------|----------|-------|
| SF1 | Output does not contain harmful, illegal, or abusive content for any reasonable input | ⬜ | — | |
| SF2 | System prompt constraints obeyed — user cannot override via prompt injection | ⬜ | — | |
| SF3 | Sensitive data (API keys, credentials, PII: names, emails, IPs) absent from output shown to users | ⬜ | — | |
| SF4 | Off-topic or out-of-scope requests → explicit refusal message, not hallucinated answer | ⬜ | — | |

## Data Quality (if training / fine-tuning)
<!-- Training pipeline must produce clean, reproducible results. -->

| ID | Checkpoint | Status | Verified | Notes |
|----|-----------|--------|----------|-------|
| DQ1 | Dataset loading: correct record count, no truncation or silent skips | ⬜ | — | if applicable |
| DQ2 | Random seed set → training run reproducible | ⬜ | — | if applicable |
| DQ3 | Eval metrics on held-out set within expected range | ⬜ | — | if applicable |

---
<!-- Add new checkpoints above this line. /review appends discovered scenarios here automatically. -->
