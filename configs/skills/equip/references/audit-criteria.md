<!-- Updated: 2026-04-20 -->

# Audit Criteria — Red Flag Checklist for Absorbed Equipment

This file drives the `equip_audit.py` scorer. Each rule has a pattern (regex or heuristic), a severity, and a remediation.

## Severity scale

| Severity | Meaning | Default decision |
|---|---|---|
| `block` | Must fix before adoption | NEEDS-REVIEW (or SKIP) |
| `warn` | Should fix but not blocking | NEEDS-REVIEW |
| `info` | Nice to know | ADOPT with note |

## Rules

### 1. Security

| ID | Pattern | Severity | Remediation |
|---|---|---|---|
| SEC-01 | `\beval\s*\(` in prompt or script | block | Remove or replace with safe alternative |
| SEC-02 | `\bcurl\s+[^\|]*\|\s*(bash\|sh)` (curl pipe shell) | block | Replace with `curl -o file && verify && bash file` |
| SEC-03 | Hardcoded API key pattern: `(api_key\|secret\|token)\s*[:=]\s*["'][A-Za-z0-9_\-]{20,}` | block | Move to env var, reject the skill |
| SEC-04 | Unquoted shell var: `\$[A-Z_]+` in bash command context without quotes | warn | Quote it |
| SEC-05 | `sudo\s` in skill prompt | block | Skills should never require sudo |

### 2. Noise / Marketing

| ID | Pattern | Severity | Remediation |
|---|---|---|---|
| NOI-01 | Footer text containing `Buy Pro\|Join community\|AI Marketing Hub\|Upgrade to\|Subscribe to` | warn | Strip the footer block before writing |
| NOI-02 | Affiliate/referral link: `utm_source=\|?ref=\|affiliate\|partnerid` | warn | Strip the link or replace with plain URL |
| NOI-03 | Repeated self-promotion across multiple skills (same URL in 3+ prompts) | warn | Strip on sync |

### 3. Model / API Drift

| ID | Pattern | Severity | Remediation |
|---|---|---|---|
| DRF-01 | Retired model alias: `claude-3-opus-20240229\|claude-3-sonnet-20240229\|claude-2\|claude-instant` | warn | Rewrite to current alias (see `~/.claude/models.env`) |
| DRF-02 | Pinned old Anthropic API version `anthropic-version:\s*2023-` | warn | Bump to 2024-10-22 or use SDK default |
| DRF-03 | Deprecated endpoint `/v1/complete\b` (legacy text-completion) | block | Rewrite to messages API |

### 4. Bloat

| ID | Pattern | Severity | Remediation |
|---|---|---|---|
| BLT-01 | `prompt.md` > 500 lines | info | Flag for human review — may be verbose |
| BLT-02 | `prompt.md` > 1500 lines | warn | Exceeds Claude Code 1-shot Read limit; suggest split |
| BLT-03 | Same caveat/warning repeated ≥3 times in one prompt | info | Candidate for consolidation |

### 5. License

| ID | Pattern | Severity | Remediation |
|---|---|---|---|
| LIC-01 | No LICENSE file in upstream repo | warn | Ask user — is this safe to adopt? |
| LIC-02 | GPL/AGPL license (viral) | warn | Flag for user: may force project license change |
| LIC-03 | Attribution removed from prompt when local differs from upstream | warn | Preserve attribution |

### 6. Dependency

| ID | Pattern | Severity | Remediation |
|---|---|---|---|
| DEP-01 | Requires MCP server (documented in prompt/references) | info | Note in audit; user must install MCP separately |
| DEP-02 | Paid API dependency: `DataForSEO\|SemRush\|Ahrefs\|OpenAI` with cost per call | info | Note cost; suggest gate behind confirm |
| DEP-03 | Python package imported that's not in requirements/pyproject | warn | Add to project deps or reject |

### 7. Overlap

| ID | Heuristic | Severity |
|---|---|---|
| OVR-01 | Upstream skill name matches a local `native` skill | warn |
| OVR-02 | Upstream skill's frontmatter `when_to_use` keywords overlap >50% with an existing local skill | info |

### 8. Quality

| ID | Heuristic | Severity |
|---|---|---|
| QLT-01 | No `references/` directory in upstream skill | info |
| QLT-02 | Empty or trivial `prompt.md` (<20 lines) | info |
| QLT-03 | SKILL.md missing required frontmatter (`name`, `description`, `when_to_use`) | warn |

---

## Decision matrix

For each skill, sum severities:

- 0 blocks + 0 warns → **ADOPT** (clean)
- 0 blocks + 1-2 warns → **ADOPT** with remediation notes
- 0 blocks + 3+ warns → **NEEDS-REVIEW**
- ≥1 block → **NEEDS-REVIEW** (with remediation) or **SKIP** (if block is LIC-02, SEC-03)
- Overlap OVR-01 hit → **SKIP** by default (user can override)

Score is reported as `(10 - 2*blocks - warns)/10`, clamped to 0-10.

---

## Merge strategy (applied by equip_sync.py)

Given base (last synced fingerprint), ours (current local), theirs (remote HEAD):

| Case | base | ours | theirs | Action |
|---|---|---|---|---|
| Unchanged | = | = | = | no-op |
| Upstream-only | = | = | ≠ | auto-apply theirs (safe upgrade) |
| Local-only | = | ≠ | = | keep ours (preserve local edits) |
| Same delta | = | ≠ | ≠ | no-op if ours == theirs, else conflict |
| New upstream | (none) | (none) | (new) | adopt iff decision == ADOPT |
| New local | (none) | (new) | (none) | keep ours (our addition) |
| Deleted upstream | (existed) | = | (deleted) | ask user — delete or keep? |
| Modified remediation | — | — | — | apply remediation (e.g. strip NOI-01 footer) before write |
