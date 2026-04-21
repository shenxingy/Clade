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

## Detection algorithm

Used by `equip_common.py:detect_layout()`:

1. If `configs/skills/` exists → **Layout A**
2. Else if `skills/` exists AND (`install.sh` OR `plugin.json`) → **Layout B**
3. Else if path is under `~/.claude/` → **Layout C**
4. Else if `WIKI.md` AND `skills/` → **Layout D**
5. Fallback: ask user

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
