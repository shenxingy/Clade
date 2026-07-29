# Generic connection adapter

- Inspect host-native configuration only through documented interfaces.
- If no adapter exists, provide the requested `clade.execution/v1` metadata
  shape and stop before mutating vendor-specific files.
- Never invent a live catalog. Use `declared` for opaque metadata and
  `unavailable` when a configured probe cannot be completed.
- Never emulate another runtime by launching its CLI without explicit user
  direction.
