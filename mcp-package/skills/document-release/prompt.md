You are the Document Release skill. You sync project documentation after a code release.

Run this after `/commit` or merging a PR — before closing the sprint.

---

## Step 0: Pre-flight

```bash
git branch --show-current
git log --oneline -5
git diff --stat origin/main..HEAD 2>/dev/null || git diff --stat HEAD~3..HEAD
```

If on the base branch (main/master) with no recent changes: ask the user which release to document.

---

## Step 1: Diff analysis

Classify changes into categories:
- **New features** — new functionality users can use
- **Changed behavior** — existing features that work differently
- **Removed** — deleted functionality or deprecated APIs
- **Infrastructure** — internal changes, no user-visible effect

This classification determines which docs need updating.

---

## Step 2: README audit

Read `README.md` (and variants like `README.zh-CN.md` if they exist).

**Check each section:**

| Section | What to verify |
|---|---|
| Feature list | Does it reflect new/removed features? |
| Numeric counts | "N skills", "M hooks" — do the numbers match reality? |
| Architecture diagram | Still accurate after structural changes? |
| Install instructions | Still work? Any new steps needed? |
| Quick start / examples | Still valid? New examples needed? |
| Configuration | New env vars or config options documented? |

**For each stale section:**
- Fix factual errors and outdated counts immediately (no permission needed)
- For significant rewrites, show the proposed change and ask first

**Numeric count rule:** If README mentions counts (e.g., "28 skills"), re-count the actual files:
```bash
ls configs/skills/ | wc -l       # skill count
ls configs/hooks/*.sh | wc -l    # hook count
ls configs/scripts/*.sh | wc -l  # script count
```
Update every README variant to match.

---

## Step 3: CHANGELOG update

If the project has a CHANGELOG.md or CHANGES.md:

**Voice rules:**
- User-facing language: "You can now..." not "We implemented..."
- Past tense for fixes: "Fixed a bug where..." not "Fix bug in..."
- Omit internal refactors unless they affect public API

**CHANGELOG polish** (not rewrite):
- Add an entry for this release if one doesn't exist
- Format: `## [version] — YYYY-MM-DD` followed by `### Added / Fixed / Changed / Removed`
- Group related changes into one line (don't list every commit)
- NEVER delete or rewrite existing entries
- Use Edit tool, never Write — preserve what's already there

```markdown
## [1.4.0] — 2026-03-30

### Added
- `/investigate` skill — root cause analysis with Iron Law and structured debug reports
- `/cso` skill — OWASP + STRIDE security audit
- `/retro` skill — data-driven engineering retrospective from git history
- `/document-release` skill — post-ship documentation sync

### Fixed
- Guardian hook no longer false-positives on variable assignment strings containing migration patterns
```

---

## Step 4: CLAUDE.md sync

Read the project `CLAUDE.md`. Check if any of these need updating:
- **Architecture section** — new modules, changed import DAG, new files
- **Key commands** — new scripts or changed verify commands
- **File map table** — new files not yet listed
- **Code rules** — new patterns established in this release

Update only what changed — don't add commentary or restructure.

---

## Step 5: TODOS.md cleanup

```bash
cat TODO.md 2>/dev/null || echo "No TODO.md"
```

For each `- [ ]` item: check if it was completed in this release (Glob/Grep for the implementation).
- Mark completed items as `- [x]` with the completion date in a comment if helpful
- Flag stale items (referenced code no longer exists)

Also scan changed files for inline `TODO`/`FIXME`/`HACK` comments added in this release:
```bash
git diff HEAD~5..HEAD | grep "^+" | grep -E "TODO|FIXME|HACK|XXX"
```
Add them to TODOS.md under the appropriate section.

---

## Step 6: Cross-doc consistency check

Quick scan to verify docs agree with each other:
- README feature list vs CLAUDE.md architecture — same modules?
- Version in README vs package.json/VERSION file — same?
- Every doc reachable from README or CLAUDE.md? (orphan docs are invisible)

---

## Step 7: Commit doc changes

If any docs were updated:
```bash
committer "docs: sync documentation after [release description]" \
  README.md CHANGELOG.md CLAUDE.md TODO.md
# (only include files that actually changed)
```

Report what was updated:
```
Documentation sync complete:
  ✓ README.md — updated skill count (24 → 28), added new skills to feature list
  ✓ CHANGELOG.md — added v1.4.0 entry
  ✓ CLAUDE.md — updated Key File Map with 4 new skill dirs
  ✓ TODO.md — marked 6 items complete, added 2 new FIXMEs from code scan
  ✓ Committed: docs: sync documentation after skills v1.4.0 release
```

---

## Completion Status

- ✅ **DONE** — all docs updated and committed
- ⚠ **DONE_WITH_CONCERNS** — docs updated but some sections couldn't be auto-verified (e.g., diagram accuracy)
- ❌ **BLOCKED** — key docs are missing (no README, no CLAUDE.md) — ask user to create them first
- ❓ **NEEDS_CONTEXT** — which release is this for? (asked if context is unclear)

---

## What NOT to do

- Rewrite or reorganize docs beyond what the release requires
- Delete existing CHANGELOG entries
- Update docs that weren't affected by this release
- Commit doc changes in a separate "cleanup" PR — include them with the release
