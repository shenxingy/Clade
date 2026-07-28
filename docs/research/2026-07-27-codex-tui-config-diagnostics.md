# Codex TUI configuration diagnostics

Date: 2026-07-27

Branch: `fix/codex-tui-config-diagnostics`

## Scope

Investigate four values shown by the locally built Codex TUI:

1. `Clade git:(fix/fail-closed-agent-runtime) 🦢 +29% (5d)`
2. A duplicated `--dangerously-bypass-hook-trust` warning
3. `OpenAI Codex (v0.0.0)`
4. `permissions: YOLO mode`

The live account page reported:

- General weekly usage: 76% left, resets August 1
- GPT-5.3-Codex-Spark weekly usage: 100% left, resets August 3

## Findings

### 1. `+29% (5d)` was stale and wrong

Clade's Claude Code and Codex helpers intentionally use the same pace formula:

```text
pace delta = usage% - elapsed% × 0.95
```

Therefore:

- positive means quota is being consumed faster than the 95% target pace;
- negative means quota is being consumed slower than the target pace.

With approximately 24% used when the target cumulative usage was approximately
29%, the expected value was approximately `-5%`, not `+5%` or `+29%`.

The custom renderer reads `~/.codex/statusline-usage.json`. Before the manual
refresh, that file had not changed since July 23 and still contained:

```json
{
  "used_percent": 58,
  "pace_delta": 28.8,
  "resets_in": "5d"
}
```

The renderer rounded the persisted `28.8` to `+29`. It did not validate the
cache age or the absolute reset timestamp. The installed `refresh-usage`
command existed, but no hook, alias, timer, or renderer path invoked it.

A manual refresh on July 27 returned current values and rendered the expected
sign:

```text
General: 25% used, 75% left, pace -4.1, resets in 5d
Spark:    0% used, 100% left
Footer:   🐥 -4% (5d)
```

The one-point difference from the earlier 76%-left account-page snapshot is
consistent with additional usage after that snapshot.

Persistent remediation belongs to the custom status-line package:

1. Treat a cache older than a short TTL as unavailable instead of rendering it.
2. Start a single-flight asynchronous refresh when the cache is stale.
3. Recompute `resets_in` from `resets_at` at render time.
4. Add regression cases for stale cache suppression and
   `24% used / ~29% target -> ~-5%`.

### 2. The hook-trust warning is accurate, but duplicate rendering is not

The interactive `cx` alias is:

```sh
alias cx='codex --dangerously-bypass-approvals-and-sandbox --dangerously-bypass-hook-trust'
```

The warning is therefore expected for that invocation. It is rendered twice
because the locally built Codex path forwards the same startup warning through
two channels:

- `codex-rs/tui/src/lib.rs` converts `config.startup_warnings` into app-server
  `ConfigWarningNotification` values.
- `codex-rs/core/src/session/session.rs` converts the same values into
  `EventMsg::Warning` events.

The current `~/.codex/config.toml` already records trusted hashes for both
installed Clade hooks. Removing only `--dangerously-bypass-hook-trust` from
`cx` would remove this warning and restore review when a hook changes. If the
bypass flag remains intentional, the TUI should deduplicate the two warning
channels in the Codex fork.

### 3. `v0.0.0` and the test announcement have one packaging cause

`codex` resolves to the locally built binary under
`~/.local/lib/codex-statusline/bin/codex`. Its source checkout is
`~/projects/codex-statusline-patch`, and that checkout's
`codex-rs/Cargo.toml` sets the workspace package version to `0.0.0`.

The same checkout contains an announcement rule that deliberately matches
local development builds:

```toml
content = "This is a test announcement"
version_regex = "^0\\.0\\.0$"
to_date = "2027-05-10"
```

Thus the banner and `Tip: This is a test announcement` are expected for this
development build, but they are not appropriate release-facing metadata. The
fork's packaging process should stamp a nonzero fork/release version; doing so
also stops the test-only announcement from matching.

### 4. `YOLO mode` is accurate

The running processes were invoked with
`--dangerously-bypass-approvals-and-sandbox`, so `permissions: YOLO mode`
correctly describes the active sandbox and approval policy.

`notice.hide_full_access_warning = true` hides the separate full-access warning;
it does not change the permission mode or suppress the hook-trust warning.

## Ownership boundary

The pace formula and live app-server reader are present in Clade, but the broken
cache lifecycle, custom renderer, version stamp, test announcement match, and
duplicate startup-warning rendering are owned by the separate
`codex-statusline-patch` installation/source tree. A permanent implementation
should be made in an isolated branch/worktree of that repository rather than
editing its currently dirty shared worktree or disguising the problem in
Clade's native `codex-usage` helper.
