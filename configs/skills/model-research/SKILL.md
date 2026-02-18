---
name: model-research
description: Research latest Claude models and update selection guide — run when new models drop or periodically to stay current
argument-hint: '[--apply]'
---

# Model Research Skill

Searches the web for latest Claude model information, compares benchmarks and pricing, then updates the model selection guide.

## What it does

1. Searches for latest Claude model announcements, benchmarks, and pricing
2. Compares against the current guide in `docs/research/models.md`
3. Shows what changed (new models, price changes, benchmark updates)
4. With `--apply`: updates `models.md`, `session-context.sh` model guidance, and `batch-tasks/prompt.md` model assignment

## Usage

```
/model-research              # Research + show diff (no changes written)
/model-research --apply      # Research + update all configs
```
