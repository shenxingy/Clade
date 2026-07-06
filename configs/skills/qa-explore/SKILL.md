---
name: qa-explore
description: Git-log-scoped exploratory regression hunting — scopes a pass from recent commit history, forms concrete side-effect hypotheses per commit (not just re-testing stated intent), then manually drives the live app via curl or Playwright MCP to probe them. NOT the fixed anchor/VERIFY.md checks (use /verify) and NOT a PR-diff review (use /review-pr) — this is open-ended exploration with no maintained fixture, bounded by time and commit count.
when_to_use: "explore for regressions, what could recent commits have broken, hunt for regressions, exploratory QA pass, antirez-style regression hunt, manually poke the app after a batch of commits — NOT for the fixed behavior-anchor checklist (use /verify) or a VERIFY.md walkthrough (use /review)"
argument-hint: "[since <ref-or-date>]"
user_invocable: true
---
