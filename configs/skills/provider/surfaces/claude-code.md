# Claude Code connection adapter

- Provider/gateway selection is user-scoped Claude Code configuration plus
  environment/credential-store state. Inspect native docs/config supported by
  the installed version before editing.
- The legacy `provider-switch.sh` may be used only when the user already has a
  trusted `~/.claude/providers.json`; it is a Claude-specific compatibility
  adapter, not the universal source of truth.
- Custom gateway model strings are opaque. Validate and shell-quote them; do
  not enforce a static Clade catalog.
- A discovery-managed connection references a trusted `providers.json` entry
  as `store: claude-providers` plus its profile name. Resolve endpoint and
  credential environment variables only inside the adapter; expose only
  catalog observations and safe error categories.
- Restart or start a new Claude Code session when native configuration is read
  only at startup.
