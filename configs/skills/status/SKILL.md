---
name: status
description: Show a provider-neutral, freshness-aware snapshot of active Agent work, Git delivery, execution identity, and usage limits. Use when the user asks what is running, whether progress is updating, which runtime/provider/model is active, or whether work is stuck.
---

# Status

Render one `clade.status/v1` snapshot. Separate observed facts from estimates,
attach source/freshness, and preserve unknown values as unknown. Read
`prompt.md` for the core contract and only the current runtime file under
`surfaces/` for collection mechanics.
