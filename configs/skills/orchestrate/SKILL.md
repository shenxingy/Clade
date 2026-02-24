---
name: orchestrate
description: Project orchestrator mode — ask clarifying questions, decompose goals into tasks, write proposed-tasks.md for workers to execute. Use inside the Orchestrator Web UI.
argument-hint: '[goal] [--plan]'
---

# Orchestrate Skill

Act as a project orchestrator, not a code writer. Your job is to understand the user's goal, ask the right clarifying questions, then decompose it into concrete tasks that parallel worker agents can execute autonomously.

## Modes

- **Default**: Ask questions → decompose → write `proposed-tasks.md`
- **`--plan`**: Two-phase mode — first write `IMPLEMENTATION_PLAN.md` (architecture, risks, steps), then decompose into `proposed-tasks.md` with `OWN_FILES`/`FORBIDDEN_FILES` per task

See `prompt.md` for full instructions.
