---
name: internal-deploy
description: Deploy to the company intranet and prove the served state — publish a single HTML report to the Artifact Hub (slug directory + manifest under the hub root), or rebuild and reload an app behind its process manager and reverse proxy, then smoke-verify the internal URL and report exactly what changed. NOT public/cloud deployment or CI pipeline configuration.
when_to_use: "内网部署, 部署artifact, 发布到内网, artifact hub发布, internal deploy, intranet deploy, 发布报告到hub, 部署后验证, deploy and verify, smoke verify"
user_invocable: true
---

# Internal Deploy

Ship to the company intranet and verify the served result, in two modes.
The executable instructions live in `prompt.md`; this body is the
Codex-facing summary.

Key contracts:

- The concrete machine map (hub root path, process-manager app name,
  proxy config, internal URLs, publish timers, credential locations) is
  never hard-coded here — it resolves from the target repo's CLAUDE.md /
  infra docs, or from the operator's private global-instructions tail.
  If no map resolves, stop and say which file should carry it.
- Mode A (artifact publish): head normalization first (doctype, charset,
  viewport), slug directory + manifest with owner/source/tags/version,
  version bump or dated slug on republish, then verify over the internal
  HTTPS URL — never the file on disk — before reporting the URL.
- Mode B (app deploy): clean-tree preflight, build, zero-downtime reload,
  smoke the health endpoint plus key pages through the proxy URL, check
  process error logs, and state the rollback path before declaring done.
- Report: Bottom line + Needs you (or "Nothing needed from you.") + URL + what
  changed (commits) + smoke evidence + parked items.
- Lead first: every published report opens, directly under its headline and one as-of
  line, with the lead block `<section id="bottom-line">` — **Bottom line**: the verdict
  the reader acts on, in one or two sentences; **Needs you**: each action or decision the
  owner must take, with a date, or the literal "Nothing needed from you." /
  「不需要你做什么。」; a blocker line only when the owner must know it now. Bylines,
  provenance, version notes, contents bars, goals and number tiles go below it, and
  provenance and version history go to the foot. A page whose first screen is a
  chronology gets sent back (2026-09-23: "你不要给我时间线…直接给我最终的结论"), and so
  does one whose first screen does not say what its owner must do (2026-11-22).
  Work-log headers run Human TODO · Blockers · Now · Goal. `artifact-lint.py` holds the
  position (`lead` FAIL, `lead-ask` WARN); the first-screen review judges the words.
- Deploying is outward state: confirm ambiguous version intent first.
