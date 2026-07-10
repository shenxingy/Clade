<!-- Updated: 2026-04-20 -->

# Project Layouts — Where Equipment Lives

Different projects organize skills/agents/scripts differently. `/equip` detects the layout so it can map remote paths to local paths.

## Supported layouts

### Layout A: "Kit-style" (e.g., Clade)

```
<project>/
  configs/
    skills/<name>/{SKILL.md,prompt.md,references/}
    agents/*.md
    scripts/*.{sh,py}
    hooks/*.sh
  install.sh
```

Install script copies `configs/**` → `~/.claude/**`.

**Signal**: `configs/skills/` dir exists AND `install.sh` writes to `~/.claude/`.

### Layout B: "Plugin-style" (e.g., AgriciDaniel/claude-seo, claude-ads, claude-blog, claude-cybersecurity)

```
<project>/
  skills/<name>/{SKILL.md,references/}
  agents/*.md
  scripts/*.{sh,py}
  install.sh
  plugin.json  (optional, for Claude Code plugin marketplace)
```

Install copies `skills/**` directly to `~/.claude/skills/**`.

**Signal**: top-level `skills/` dir exists AND either `install.sh` exists OR `plugin.json` present.

### Layout C: "Dotfiles" (e.g., user's personal ~/.claude)

```
~/.claude/
  skills/<name>/
  agents/
  scripts/
```

No source directory — the runtime location IS the project.

**Signal**: project root IS `~/.claude/` or symlinked there.

### Layout D: "Vault-style" (e.g., AgriciDaniel/claude-obsidian)

```
<vault>/
  skills/<name>/
  bin/setup-vault.sh
  WIKI.md
```

Similar to Layout B but the project root is an Obsidian vault.

**Signal**: `WIKI.md` at root AND `skills/` dir.

### Layout E: "Skill-at-root" (upstream-only; e.g., scamai/design-system)

```
<repo>/
  SKILL.md          ← agent-facing rules (the skill entrypoint)
  DESIGN.md         ← optional deep spec the SKILL.md links to
  tokens.css, components/, brand/, ...   ← assets shipped with the skill
```

The repo IS one skill — SKILL.md at the root, assets beside it. Typical for
company overlay repos (a design system, a workflow pack) meant to be dropped
into any product and handed to an AI assistant.

**Signal**: `SKILL.md` at repo root AND no `skills/` / `configs/skills/` dir
(`equip_common.py:is_single_skill_repo()`).

**Absorption**: the whole repo maps to one local skill dir named after the
upstream id (`upstream_skill_dirs()` returns the repo root; the cache dir is
named by upstream id, so `design-system` → `configs/skills/design-system/`).
`.git/` is always excluded from hashing/sync. `--base-ref` 3-way merge is
unsupported for this layout (it assumes `skills/<name>` paths) and degrades
to the no-base behavior.

## Detection algorithm

Used by `equip_common.py:detect_layout()` (LOCAL project side — Layout E is
an upstream shape and is detected separately, see below):

1. If `configs/skills/` exists → **Layout A**
2. Else if `skills/` exists AND (`install.sh` OR `plugin.json`) → **Layout B**
3. Else if path is under `~/.claude/` → **Layout C**
4. Else if `WIKI.md` AND `skills/` → **Layout D**
5. Fallback: ask user

Upstream side, `equip_common.py:upstream_skill_dirs()` resolves the skill
list: container dir children for A/B/D, or `[repo root]` for **Layout E**
(root `SKILL.md`, no container).

## Path mapping for sync

When adopting upstream skills, apply this transform:

| Local layout | Upstream layout | Example mapping |
|---|---|---|
| A | B | `skills/seo-audit/` → `configs/skills/seo-audit/` |
| A | A | `configs/skills/seo-audit/` → `configs/skills/seo-audit/` |
| B | B | `skills/seo-audit/` → `skills/seo-audit/` |
| C | B | `skills/seo-audit/` → `~/.claude/skills/seo-audit/` |

Equip cares only about skills, agents, scripts under the standard roots. Other files in the upstream (README, LICENSE, CI configs) are ignored by default. User can override per-upstream in `upstreams.yaml`:

```yaml
- id: claude-seo
  include:
    - "skills/**"
    - "agents/**"
    - "scripts/dataforseo_*.py"
  exclude:
    - "skills/seo-ecommerce/**"  # opt out of this one
```
