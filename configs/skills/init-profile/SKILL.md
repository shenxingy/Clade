---
name: init-profile
description: Generate `.claude/PROJECT_PROFILE.md` — the project-specific facts that should be loaded into every session (deployment topology, host mapping, env file locations, verification commands). Run once per project after clone.
when_to_use: "set up project profile, init project for Claude, document deployment topology, capture host mapping, first-run setup, /init-profile — NOT for /init (which generates CLAUDE.md)"
argument-hint: ''
user_invocable: true
---

# Init-Profile Skill

Capture project-specific facts that the SessionStart hook will inject every time. Pairs with the `Environment Fingerprint` block (host-level facts) by adding the `Project Profile` block (project-level facts).

## What it does

Writes `.claude/PROJECT_PROFILE.md` with five sections, filled in interactively. The session-context.sh hook auto-loads this file on every SessionStart, so the agent has the facts upfront and stops guessing.

## Why it exists

Without a profile, the agent re-discovers the same facts each session ("where does prod run?", "is this hostname local or remote?", "where are the env secrets?"). With a profile, those facts live in the system prompt from session 1.

## Process

1. **Detect what already exists.** Read these for clues:
   - `CLAUDE.md` (deployment URLs, commands)
   - `.env`, `.env.example`, `.env.*.local`, `brands/*.local.env`
   - `package.json`, `Dockerfile`, `docker-compose.yml`, `vercel.json`, `netlify.toml`
   - `~/.profile` / `~/.zshrc` for project-specific env vars
   - Recent `git log` for clues on dev workflow

2. **Ask the user** (one question per section, skip if already obvious from step 1):

   **a. Hosts & topology**
   - Which hostname is "production"? Which is "dev"? Are any of them THIS machine?
   - Examples: "prod = vercel.com (remote)", "Aries = this machine, runs local dev"

   **b. Service URLs**
   - Live production URL?
   - Local dev URL(s) and ports?

   **c. Secret/env file locations**
   - Where are the real secrets stored? (gitignored .env paths)
   - Which env vars are critical and where do they come from?

   **d. Verification commands**
   - One-line "is this thing healthy" commands per environment.
   - Example: `gh api repos/x/y/actions/runs --jq '.workflow_runs[0].conclusion'`

   **e. Aliases the user uses for this project**
   - "When I say X, I mean Y." (e.g., "the brand env" = `brands/*.local.env`)

3. **Write `.claude/PROJECT_PROFILE.md`** in this format:

   ```markdown
   # Project Profile — <project name>

   ## Hosts
   - <hostname>: <role> (this machine | remote)
   - <hostname>: <role> (this machine | remote)

   ## URLs
   - Production: <url>
   - Local dev: <url(s)>

   ## Env / secrets
   - <path>: <what's in it>

   ## Verify commands
   - <env>: `<command>`

   ## Aliases
   - "<phrase user uses>" → <what it actually maps to>
   ```

4. **Confirm** — show the file content, ask the user to approve before writing.

5. **Do NOT git-commit.** The user decides what's safe to commit. `.claude/PROJECT_PROFILE.md` may contain internal hostnames or URLs that shouldn't be public — recommend `.gitignore` if the project is public.

## Output

- File: `.claude/PROJECT_PROFILE.md`
- One-line confirmation of where it landed and that it'll auto-load next session.

## Notes

- Keep the profile under 50 lines. Long profiles bloat every SessionStart prompt.
- If a fact changes (new prod URL, new hostname), edit the file directly — no need to re-run `/init-profile`.
- This skill is project-scoped. Host-level facts (Tailscale IP, sibling projects, gh/gcloud auth) are captured automatically by the `Environment Fingerprint` block in session-context.sh — don't duplicate them here.
