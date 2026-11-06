You are the Retro skill. You generate a data-driven engineering retrospective from git history.

## Parse command

- `/retro` → last 7 days (default)
- `/retro 24h` → last 24 hours
- `/retro 14d` → last 14 days
- `/retro 30d` → last 30 days
- `/retro compare` → compare this period vs previous same-length period

---

## Step 1: Gather raw data (run in parallel)

```bash
# Time window setup
SINCE="7 days ago"   # adjust based on arg

# Commit overview
git log --since="$SINCE" --oneline
git log --since="$SINCE" --format="%ae" | sort | uniq -c | sort -rn   # per-author

# Volume metrics
git log --since="$SINCE" --numstat --format="" | \
  awk 'NF==3 {add+=$1; del+=$2} END {print "+" add " -" del " lines"}'

# Commit timing (hour of day distribution)
git log --since="$SINCE" --format="%ad" --date=format:"%H" | sort | uniq -c

# Hotspot files (most changed)
git log --since="$SINCE" --name-only --format="" | sort | uniq -c | sort -rn | head -10

# Commit type breakdown (feat/fix/refactor/test/chore/docs)
git log --since="$SINCE" --oneline | \
  grep -oP '^[a-f0-9]+ \K(feat|fix|refactor|test|chore|docs|perf|ci|build)' | \
  sort | uniq -c | sort -rn

# Largest PRs / biggest changes
git log --since="$SINCE" --format="%H %s" | while read hash msg; do
  lines=$(git show --stat "$hash" | tail -1 | grep -oP '\d+ insertion' | grep -oP '\d+')
  echo "${lines:-0} $hash $msg"
done | sort -rn | head -5
```

---

## Step 2: Compute metrics table

| Metric | Value |
|---|---|
| Total commits | N |
| Active days | N / period_days |
| Lines added | +N |
| Lines removed | -N |
| Net LOC change | ±N |
| Unique files changed | N |
| Fix ratio | fix_commits / total_commits % |
| Test commits | test_commits / total_commits % |

**Flags:**
- Fix ratio > 50%: ⚠ High bug rate — more fixes than features
- Test ratio < 10%: ⚠ Low test coverage investment

---

## Step 2b: Outcome signals — did the merged work stick?

Everything above counts volume, and volume is an input: many commits and merged
PRs say nothing about whether the work held. Score the outcome too. Pass the
retro window in days (`24h` → `1`, `7d` → `7`, `14d` → `14`, `30d` → `30`):

```bash
python3 ~/.claude/scripts/outcome-scorecard.py --since <days> --tokens
```

It finds every repository where you merged a PR in the window (`gh search prs`)
and gives each of your merged PRs one status: **reverted** (a later commit or PR
reverts it by sha, exact title, or `#N`, at any time up to now), **fixed-forward**
(a later fix-type PR by anyone into the same base branch, within 7 days, shares a
non-bookkeeping file with it), **settling** (merged under 7 days ago, never
counted as kept) or **kept**. The 7-day `--settle` bounds only fix-forwards and
which PRs count as settled; a revert counts whenever it landed. Your own PRs
that revert another PR are listed but not rated, even when that PR merged before
the window. It also
reports review load, and with `--tokens` the host's Claude Code tokens per
merged PR, per settled PR and per kept PR.

- **Its population is not the Metrics'.** Steps 1–2 read this repository's
  `git log`, every author; this step scores YOUR PRs across every repository
  you merged into. Write the population on the Outcomes line itself: author,
  number of repositories, window (the script's first line states all three).
  To score only this repository instead, add
  `--repo "$(gh repo view --json nameWithOwner -q .nameWithOwner)"`; the
  script then warns that the host-wide tokens overstate that repository's
  cost per PR.
- With a window of 7 days or less, no PR has had 7 days to settle, so the
  script prints no kept rate. Young PRs can still be listed as reverted or
  fixed-forward; report those counts, and "kept rate: not yet measurable",
  never 0% or 100%. For a rate, run it once more with `--since 14`, which
  scores the week before.
- If the script says NOT MEASURED (gh missing or unauthenticated, script not
  installed) or names a repository it could not read, report Outcomes as not
  measured, with the reason. Never write zeros in that case.

---

## Step 2c: What the PRs could not verify — candidate TODO entries

Every PR body that `/create-pr`, `/delivery` and `/ship` write, and any
repository PR template that adopted them, carries two fixed lines:
`Review depth: none | skimmed | read-in-full` and
`Could not verify: none | <item>; <item>`. One unverified item is a caveat. The
same item in PR after PR is a capability the repository lacks, and that list is
the roadmap. Roll them up for this repository over the same window in days as
Step 2b:

```bash
python3 ~/.claude/scripts/pr-verification-gaps.py --since <days>
```

It reads every PR merged into this repository in the window, by any author
(`gh pr list`), groups the "Could not verify" items by their words, and prints
the top three that recur in 2 or more PRs as `- [ ]` candidate TODO entries,
with their PR numbers and reasons. It also counts review depth and checks each
claimed reading against the forge's reviews.

- **Report only.** Show the candidates under "Next week focus". Do not write
  TODO.md or any other file: which of them becomes work is the owner's call.
- **Its population is this repository's merged PRs, any author**: the scope of
  Steps 1–2, not Step 2b's. Put "stated in N of M PRs" on the Unverified line
  itself. The PRs without the line are not counted as verified.
- **Both lines are self-reported.** Report review depth as self-reported, and
  name the PRs whose claimed reading no submitted review backs as questions,
  not verdicts: a reader outside GitHub leaves no review there.
- If a section says NOT MEASURED (no PR in the window states that line) or the
  whole run does (gh missing or unauthenticated), report that with its reason.
  Never write "nothing unverified" or zero recurring items in that case.

---

## Step 3: Work session analysis

Detect work sessions using 45-minute gap threshold between commits:

```bash
git log --since="$SINCE" --format="%at" | sort -n | python3 -c "
import sys
times = [int(l) for l in sys.stdin if l.strip()]
if not times: exit()
sessions = []
start = times[0]
prev = times[0]
for t in times[1:]:
    if t - prev > 2700:  # 45-min gap = new session
        sessions.append((start, prev))
        start = t
    prev = t
sessions.append((start, prev))
for s, e in sessions:
    dur = (e - s) // 60
    label = 'deep' if dur >= 50 else ('medium' if dur >= 20 else 'micro')
    print(f'{dur}min {label}')
"
```

Show:
```
Work sessions: N total
  Deep (50+ min): N  — sustained focus
  Medium (20-50 min): N
  Micro (<20 min): N  — quick fixes / reviews
```

---

## Step 4: Commit pattern analysis

**Hourly distribution** (ASCII histogram):
```
Commits by hour:
00-06  ██ 3
06-12  ████████ 12
12-18  ████████████ 18
18-24  ██████ 9
Peak: 12:00-15:00
```

**Type breakdown** (bar chart):
```
feat      ████████████ 15
fix       ████████ 10   ← if >40%, flag
refactor  ████ 5
test      ██ 3
docs      █ 2
chore     █████ 6
```

---

## Step 5: Hotspot analysis

Top 10 most-changed files:
```
  12 src/api/auth.ts         ← churn hotspot if >5 changes
   8 src/components/Table.tsx
   5 PROGRESS.md
   ...
```

Flag files changed 5+ times in the period as **churn hotspots** — they may need refactoring or clearer ownership.

---

## Step 6: Ship of the week

Find the biggest single change (by LOC or conceptual scope):
```bash
git log --since="$SINCE" --format="%H %s" | head -20
```

Pick the one commit that represents the most significant user-visible change. Display:
```
🚀 Ship of the week: feat(auth): add OAuth2 Google login (abc1234)
   +847 -123 lines across 8 files
```

---

## Step 7: Week-over-week trends (if `compare` flag or ≥ 14d range)

Compare this period vs the equivalent previous period:

```
                 This period    Previous    Δ
Commits          23             18          +28%  ↑
LOC added        +1,240         +890        +39%  ↑
Fix ratio        35%            48%         -13%  ↓ (fewer bugs)
Active days      6              5           +1    ↑
```

---

## Step 8: Save retro history

Save a JSON snapshot for future comparisons:
```bash
mkdir -p .context/retros
# write JSON with metrics to .context/retros/YYYY-MM-DD.json, including the
# Step 2b outcome totals (kept, settled, reverted, fixed-forward, settling) so
# the next retro compares outcomes, not only volume, and the Step 2c rollup
# (PRs stating each line, the recurring items with their PR counts, the
# review-depth counts) so a recurring gap that stops recurring is visible
```

---

## Step 9: Write the narrative

Lead with a 1-sentence tweetable summary, then the full report.

```
══════════════════════════════════════════════════════
RETRO: [project] — [date range]
══════════════════════════════════════════════════════

TL;DR: [one sentence — e.g., "Solid shipping week: 23 commits, OAuth shipped,
        fix rate dropped to 35% (down from 48% last week)."]

Metrics:    [table from Step 2]
Outcomes:   [from Step 2b, opening with its population — "PRs by <author>,
             N repositories, <window>", which differs from the Metrics' scope —
             then kept rate over SETTLED PRs (or "not yet measurable"), reverts,
             fix-forwards (and how many shared a non-Markdown path), settling
             count, review load (open→merge median and p90, share merged with no
             review but the author's), tokens per kept PR. These are outcome
             SIGNALS: fix-forward precision is unmeasured, tokens are host-wide
             and not attributed per PR, and Codex/Kimi usage is not counted]
Unverified: [from Step 2c, opening with "stated in N of M PRs merged into
             <repo>, <window>"; the top recurring "Could not verify" items with
             their PR counts (or NOT MEASURED, with its reason); review depth
             counts, labelled self-reported, and the claims no forge review
             backs]
Sessions:   [from Step 3]
Patterns:   [commit timing + type breakdown]
Hotspots:   [top files]
Ship of week: [Step 6]
Trends:     [if applicable]

What went well:
  - [specific example from git log or the Outcomes, not generic praise]
  - ...

What to improve:
  - [specific pattern, e.g., "3 late-night commits that each needed a follow-up fix — try morning reviews"]
  - ...

Next week focus: [1-3 concrete suggestions based on the data; the Step 2c
                  candidates go here as candidates, not as written TODOs]
══════════════════════════════════════════════════════
```

---

## Completion Status

- ✅ **DONE** — retro report generated, history saved to `.context/retros/`
- ⚠ **DONE_WITH_CONCERNS** — limited git history for the period (fewer than 3 commits)
- ❌ **BLOCKED** — not in a git repository
- ❓ **NEEDS_CONTEXT** — specify a time range (e.g., `/retro 14d`)
