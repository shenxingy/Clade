<!-- STATUS: DONE 2026-09-02 — all ten requirements verified landed; the file
     sat at the repository root carrying ten unchecked boxes because nothing
     ticked them, and check-roadmap-authority.py did not look at root goal
     files. It does now. -->

# Goal (archived): Close the Claude Code 2.1.x / Codex 0.145 adaptation gaps

> Archived 2026-09-02. Every requirement below was verified delivered against
> the code before this file was moved out of the repository root. The boxes are
> ticked here to record that outcome; the loop that owned this goal is over.

## Outcome, requirement by requirement

| # | Requirement | Delivered by |
|---|-------------|--------------|
| 1 | Plugin manifest resolves its components | `.claude-plugin/plugin.json` drops the `agents` key in favour of a generated root `agents/`; `check-cc-plugin-components.sh` reports skills=136 agents=37 |
| 2 | `claude plugin marketplace add` is a working install path | `.claude-plugin/marketplace.json`; `claude plugin validate . --strict` resolves it and descends into the plugin. The network round-trip is the one item no test covers — it needs a live fetch |
| 3 | Plugin version no longer drifts | `regen-cc-plugin.py:canonical_version()` derives it from the Codex manifest; `--check` is a CI gate |
| 4 | CI fails on an invalid shipped manifest | `.github/workflows/validate-plugin.yml` installs the CLI unconditionally, then validates and resolves components. `check-cc-plugin-components.sh` exits 1 rather than skipping when the CLI is absent |
| 5 | Correction-pairing shadows are cleaned up | `configs/hooks/session-end-cleanup.sh` on `SessionEnd`; degrades safely with no `session_id`, no directory, or a `CP_SHADOW_DIR` override, and rails the unlink to `session-*.jsonl` |
| 6 | `post-edit-check.sh` findings reach Claude | writes findings to stderr and exits 2, with `asyncRewake` set on the hook |
| 7 | `skill-suggest.sh` findings reach Claude | runs synchronously, self-bounded by re-exec under `timeout 5` |
| 8 | `doc-align-check.sh` / `prompt-tracker.sh` left as-is, deliberately | recorded in `docs/reference/hooks.md` |
| 9 | Subagent recursion limit actually enforced | `install.sh` merges `CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH=1` into `.env` rather than replacing the section |
| 10 | Every behaviour change covered by a test | `tests/test-hooks.sh` covers 5, 6, 7 and the settings wiring; `tests/test-install.sh` covers 9 on fresh install and re-install |

---

Clade's integration surfaces were audited against Claude Code 2.1.227 and Codex
CLI 0.145.0. No breaking change had landed, but several Clade features were
found to be silently inert, and several manifests advertise capabilities the
repository does not actually deliver. This goal describes the end state where
every one of those gaps is closed and guarded by a test.

Two gaps were already fixed in commit `3eaf257` and are NOT in scope here:
the `SessionStart` matcher widening (`startup|clear|fork`) and the
`secret-scanner` async→sync change. Do not re-open them.

## Context: why each requirement exists

An `async: true` command hook has no channel back into the turn — that is
precisely why Claude Code added `asyncRewake` (runs in background, wakes Claude
on exit code 2, surfacing stderr, or stdout when stderr is empty, as a system
reminder). Any async hook whose only product is `systemMessage` or
`hookSpecificOutput.additionalContext` is therefore writing into a void.

`claude plugin validate` is the authoritative manifest validator and accepts
`--strict` to turn warnings into a non-zero exit. A plugin manifest that
declares no component paths, in a repository whose root has no `skills/`,
`agents/`, `commands/`, or `hooks/hooks.json`, installs as an empty plugin.

## Requirements

- [x] The Claude Code plugin manifest at `.claude-plugin/plugin.json` resolves
      to Clade's real components. It declares the component paths that match
      this repository's actual layout (skills and agents live under `configs/`,
      not at the repository root), so a plugin install yields the same skills
      and agents that `install.sh` deploys, rather than an empty plugin. Do not
      relocate `configs/skills/` or `configs/agents/`, and do not change where
      `install.sh` deploys them — declaring paths in the manifest is enough.

- [x] `claude plugin marketplace add shenxingy/Clade` is a working install path
      for Claude Code, mirroring the `codex plugin marketplace add` path that
      already works for Codex. This requires a marketplace manifest that Claude
      Code recognizes, in the location Claude Code looks for it. The existing
      Codex marketplace manifest at `.agents/plugins/marketplace.json` is a
      different format for a different tool and must keep working unchanged.

- [x] The Claude Code plugin manifest's version no longer drifts from the rest
      of the project. Today it reads `0.2.0` while the Codex plugin manifest
      reads `0.3.1+codex.20260729071755`. Whatever mechanism keeps them
      consistent must make a future drift visible rather than silent.

- [x] CI fails when a plugin or marketplace manifest shipped by this repository
      is invalid. The gate uses `claude plugin validate` — the authoritative
      validator — rather than a hand-rolled schema check that would drift from
      the real loader. The gate must genuinely fail on a broken manifest; a job
      that skips when the CLI is unavailable, and therefore reports green on a
      broken manifest, does not satisfy this requirement. Prove the gate works
      by confirming it rejects a deliberately corrupted manifest before you
      restore it.

- [x] The correction-pairing shadow files at
      `/tmp/claude-edit-shadows/session-<session_id>.jsonl` are cleaned up when
      the session that owns them ends. Today `edit-shadow-detector.sh` and
      `hooks/lib/correction-pair.sh` only ever write and read them; nothing
      deletes them, so they accumulate for the life of the machine. Claude Code
      exposes a `SessionEnd` lifecycle event suited to this. Cleanup must only
      remove shadows it can attribute to ended sessions — it must never delete
      a live parallel session's shadow, and it must degrade safely when
      `session_id` is absent, when the directory does not exist, and when
      `CP_SHADOW_DIR` overrides the default location.

- [x] `post-edit-check.sh` no longer discards its findings. It runs in the
      background (it can take up to 180s, so it must not block the turn), but
      when it finds a real problem that finding reaches Claude instead of
      disappearing. Use the mechanism Claude Code provides for exactly this
      case. The hook's two current findings — the post-edit check failure
      message and the uncommitted-file-count warning — must both survive to
      Claude; a silent success path must remain silent and must not wake Claude.

- [x] `skill-suggest.sh` no longer discards its findings. Its only output is
      `hookSpecificOutput.additionalContext`, which an async hook cannot
      deliver. Choose the delivery mechanism that fits a fast, advisory,
      per-edit hook, and keep its worst-case contribution to `Edit`/`Write`
      latency bounded and explicit.

- [x] `doc-align-check.sh` and `prompt-tracker.sh` are deliberately left as-is
      and that decision is recorded where the next reader will find it, so a
      future audit does not re-flag them as bugs. They emit low-value advisory
      `systemMessage` output; the noise is not worth the latency or the wake.

- [x] The Agent Ground Rules statement "Subagents must not delegate
      recursively" is actually enforced rather than being an unenforced
      convention. Claude Code 2.1.221 changed the default subagent spawn depth
      from 1 to 3, so the rule now needs a real control to back it. Whatever
      `install.sh` does to apply this must preserve any unrelated keys the user
      already has in the same settings section — the existing hook merge
      replaces `.hooks` wholesale, and blindly copying that pattern for a
      section users also write to would destroy their settings.

- [x] Every behavior change above is covered by a test that fails if the
      behavior regresses, following the existing `tests/*.sh` conventions, and
      the documentation that describes Clade's hooks matches reality. At least
      `docs/how-it-works.md` (hook table) and `docs/reference/hooks.md` (hook
      inventory and the stale "SubagentStart/SubagentStop — scenario does not
      apply" / "SessionEnd — low value" judgments) currently describe a
      different system than the one that will exist after this work.

## Success criteria

- `bash -n configs/hooks/*.sh configs/scripts/*.sh install.sh` passes
- `cd orchestrator && find . \( -name .venv -o -name node_modules -o -name __pycache__ \) -prune -o -name "*.py" -print | xargs -n1 python -m py_compile` passes
- `cd orchestrator && .venv/bin/python -m pytest tests/ -v` passes
- `bash tests/test-install.sh` passes, including a re-install over existing settings
- `configs/scripts/regen-mcp-package.sh` and
  `python3 configs/scripts/regen-codex-plugin.py --check` report no drift
- `claude plugin validate .` reports no errors
- Existing hook behavior is unaffected: the `startup|clear|fork` session
  baseline, the synchronous secret scanner, and the correction-pairing
  async/sync split (silent signals stay async and data-only; only an explicit
  correction escalates to context) all still work as documented in `CLAUDE.md`

## Constraints

- `configs/settings-hooks.json` and `install.sh` are each touched by several
  requirements. Parallel workers must not edit either file concurrently —
  group the changes to a shared file into a single task with a single owner.
- Do not use `git add .`; commit with `committer "type: message" <files>`.
- Do not weaken or delete an existing test to make a new one pass.
- If a requirement turns out to be wrong or impossible as stated, record the
  finding and what you did instead rather than silently narrowing the scope.
