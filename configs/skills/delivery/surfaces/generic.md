# Generic runtime surface adapter

- Treat runtime-native snapshot, worktree, approval, resume, and publication
  capabilities as unknown until probed.
- Use plain Git only for operations allowed by the context profile and delivery
  authorization. Do not infer GitHub, a persistent checkout, or an interactive
  human.
- When the runtime cannot keep a detached commit reachable, create the Clade
  preservation ref or export a patch before termination.
- Report unsupported external actions explicitly; equal experience means the
  same safety and durable outcome, not pretending every runtime has the same UI.
