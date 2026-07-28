# Generic connection adapter

- Inspect host-native configuration only through documented interfaces.
- If no adapter exists, provide the requested `clade.execution/v1` metadata
  shape and stop before mutating vendor-specific files.
- Never emulate another runtime by launching its CLI without explicit user
  direction.
