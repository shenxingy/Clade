# Internal Deploy

Ship to the company intranet and prove the served state. Two modes.
Deploying is outward state: when the version intent is ambiguous (two
candidate builds, unclear which is final), confirm before shipping.

## Step 0 — Resolve the machine map (never hard-coded in this skill)

Concrete targets live in the target repo's CLAUDE.md / infra docs / deploy
scripts, or in the operator's private global-instructions tail: hub root
path, slug conventions, process-manager app name, proxy vhost, internal
HTTPS URLs, publish/rebuild timers, credential file locations. Read them
from there. If no map resolves, stop and name the file that should carry
it — do not guess hostnames or paths.

## Mode A — publish one HTML artifact to the hub

1. **Pre-flight**: confirm this file is the intended final version
   (mtime/version; if another copy exists elsewhere, diff and say which
   won). Head normalization, the standing audit standard: first lines
   must be `<!doctype html>`, `<meta charset>`, `<meta viewport>`;
   no external CDN refs that break on an intranet without internet
   (inline or same-origin assets instead). The lead is in place: the first
   block under the headline is the bottom line plus what the owner must do
   (see "Report shape" below), and
   `python3 ~/.claude/scripts/artifact-lint.py <page>` shows no `lead`
   FAIL; a `lead-ask` WARN is fixed, not explained away.
2. **Slug**: kebab-case from the title unless the house style says dated
   slugs (`name-YYYY-MM-DD`) — follow existing siblings in the hub root.
3. **Write**: `mkdir <hub-root>/<slug>/` (if permission denied, stop and
   report — never sudo). Copy as `index.html`. Write `manifest.json`
   beside it, same schema as sibling slugs: `acl, description, entry,
   files, owner, published_at (UTC ISO-8601), publisher, retired, slug,
   source {branch, dir, host, repo}, tags, title, url, version`.
   Republishing an existing slug = version bump with the old manifest's
   fields carried over; otherwise pick the next version number.
4. **Verify the served state**: `curl -sS <internal-url>/<slug>/ | head`
   through the HTTPS vhost (not the file on disk). If a root index map
   exists and rebuilds on a timer, note when the next rebuild picks the
   new slug up and re-check then or trigger the documented rebuild command.
5. **Report**: URL, slug, version, what was published, verification output.

## Mode B — deploy an app behind process manager + reverse proxy

1. **Pre-flight**: on the deploy host (or the documented deploy path);
   `git status` clean on the intended branch; frozen install
   (`pnpm ci` / `npm ci` / lockfile equivalent); production build passes.
2. **Ship**: zero-downtime reload of the documented process-manager app
   (e.g. cluster reload); confirm all instances online; confirm the
   proxy vhost still points at the right port.
3. **Smoke over the real URL**: health endpoint, then the key pages
   (login redirect, one page per top route), through the public/internal
   HTTPS name — never only localhost. Tail the process error log for
   exceptions right after reload.
4. **Rollback path**: state it before declaring done (previous build dir /
   process-manager resurrect / previous container tag, whichever the
   project actually has).
5. **Also**: if the project keeps deploy logs or TODO/GOALS bookkeeping,
   update them in the same pass.

## Report (either mode)

URL(s) · what changed (commits / artifact version) · smoke evidence
(command + status for each check) · anything parked · rollback path.

## Failure modes to avoid

- Verifying the file on disk instead of the served URL.
- Shipping from a dirty tree or a stale branch "because it built".
- Bundling 收钱/login/auth-flow changes with unrelated work in one deploy.
- Editing the proxy vhost or manifest schema without checking sibling
  configs for the established pattern first.

## Report shape (both modes)

The published page and the chat report both open with the **lead**, before any rounds, dates or timeline:

1. **Bottom line** — the conclusion the reader acts on, in one or two sentences.
2. **Needs you** — each action or decision the owner must take, with a date when there is one; or the literal line "Nothing needed from you." / 「不需要你做什么。」
3. A blocker or risk the owner must know now — only when there is one.

On the page this is `<section id="bottom-line">` (`<strong>Bottom line:</strong>` … `<strong>Needs you:</strong>` …; Chinese `结论：` … `需要你：` …) directly under the headline. Only a one-line eyebrow, the headline and one short as-of line sit above it. Bylines and provenance ("drafted by …", "prepared for …"), version notes, contents bars, terms, goals, methods and number tiles go below it; provenance and version history go to the foot. A work-log's header runs Human TODO · Blockers · Now · Goal. Then the evidence. Never lead with a chronology or a byline.
