---
name: radar
description: "Autonomous discovery of concepts, methods, and vocabulary we have NOT heard of yet — sweeps broadly, diffs against a known-concepts ledger, and reports only what is genuinely new plus whether it names a gap in this stack. A fixed topic list can only refresh what you already named; radar surfaces what you did not know to look for."
when_to_use: "periodic/scheduled discovery of unknown-unknowns, concept sweeps, what's new in agent engineering, what are we missing, 新概念, 我们没听过的, 有什么没跟上的 — NOT for a named topic (/research), model releases (/model-research), or internal priorities (/next)"
user_invocable: true
---

# Radar — find what we didn't know to look for

`/research` answers a question you can already phrase. Radar exists for the
other failure: **you cannot search for a word you have never heard.**

The motivating miss is concrete. "Graph engineering" — the successor framing to
loop engineering — reached this stack because a human mentioned it, not because
anything here noticed. Every scheduled-research design that starts from a topic
list would have missed it identically, because the list would have contained
"agents", "RAG", "context engineering", and not the term that had yet to exist.

So the unit of work is not *a topic*. It is **the delta between what the field
is saying and what this stack's ledger says it knows.**

## The ledger is the mechanism

`~/.claude/research/known-concepts.md` records every concept this stack has
already encountered — one per line, lowercase, with the date first seen.

It lives in `~/.claude/`, not a project: the field does not change per
repository, and a per-repo ledger would relearn the same terms N times.

Novelty is defined mechanically: **a term not in the ledger is a candidate.**
That is the entire trick, and it is why the ledger must be seeded honestly and
appended to on every run. A ledger that is not updated re-reports the same
findings forever; a ledger that is padded with terms nobody actually understood
suppresses real discoveries.

## Procedure

Three lanes feed the sweep. Running only the first is the common failure — the
web tells you what the field says, never what *you* keep tripping over.

| Lane | Source | Already exists? |
|---|---|---|
| A. The field | Broad web probes (§1) | No — this skill adds it |
| B. Named practitioners | `docs/who-to-learn-from.md` | Yes, but manual + quarterly |
| C. Your own usage | `~/.claude/corrections/history.jsonl` | Yes, but unmined |

**Lane B** — do not rebuild the roster. Read `docs/who-to-learn-from.md`, take
the Tier-1 entries whose canonical piece has changed since `Last reviewed`, and
run them through the same triage. Append genuinely new names *to that file*,
not to the ledger; the ledger is for concepts, that file is for people.

**Lane C — the one nobody runs.** The correction history is a record of where
this stack actually failed *you*, which no amount of web sweeping can supply.
It is mined for a different question than the rule-promoter asks: not "should
this one become a rule" but **"what do I get corrected about repeatedly, and
what does that pattern say is structurally missing?"**

Read it as a JSON stream (`jq -c '.'`), and cluster on:

- Recurring `project` + `type` pairs, and recurring language in `prompt` — three
  corrections of the same class is a design signal, not three mistakes.
- Entries carrying `reverted_files` — a rejected diff is the strongest evidence
  available; the words may be vague, the diff never is. Read the caveat below
  before trusting this field.
- `repeat: true` — flagged recurrence, already computed.

**Know the schema before you grep it.** `history.jsonl` records are
`{timestamp, prompt, project, type}`, plus `reverted_files` and `repeat` on
some. There is no `domain` and no `root_cause` — this spec asked for both until
2026-08-31, which sent three runs looking for fields that were never written.
`domain` lives in the *other* file, `cross-project-rules.jsonl`.

**Two serialization styles, one file.** Records written up to 2026-08-14 are
spaced (`{"timestamp": "..."`), records from 2026-08-15 on are compact
(`{"timestamp":"..."`). At the 2026-08-31 sweep that was 853 spaced and 110
compact out of 963. Any pattern keyed to one style silently drops the other —
grepping `'"prompt":"'` returns 110 and reads like the whole file. Parse with
`jq`, which handles both; never line-grep this file for a count.
`configs/scripts/session-scorecard.sh` had exactly this bug and was worse than
latent: its awk matched only the compact form AND used gawk's 3-argument
`match()`, which errors out on mawk — the default `awk` here — where a trailing
`|| echo 0` turned the error into a plausible zero. Both correction counters had
therefore been structurally 0 for the life of the file. It now parses with `jq`,
which is style-agnostic by construction, and `tests/test-session-scorecard.sh`
pins it.

**`reverted_files` means what it says, but only since 2026-09-02.** The field is
now the intersection of the shadow with the revert command's *own pathspec*, and
the loose session list it used to hold lives under its true name `session_files`.
`repeat` is meaningful only when `revert_scope` is `paths`: `git revert` takes no
pathspec, `git reset --hard` cannot take one, and the hook is async, so for those
forms the file set is not knowable at hook time — `reverted_files` is `[]` and
`repeat` is `null`, which is honest rather than a substituted guess.

**Exclude `revert_scope:"probe"` from any rejection cluster — and do not trust
its absence.** The marker has been installed since 2026-10-10, yet 0 of the 115
records written 2026-10-05 → 10-12 carried it. It marks a mutation test — the
practice the global CLAUDE.md *requires* — but only recognised the round-trip
(`git apply`/`git stash pop` after the revert) and the label `MUTATION`, and the
dominant real shape has neither: `sed -i X` or `python3 - "$f" <<'EOF'`, then
the tests, then `git checkout -- X`. The same-command-edit signal (landed
2026-10-16 in #124) now covers that shape: 5 of the 40 implicit-revert records
of 2026-10-12 → 10-19 came out `probe`. Three shapes still read as `paths`, so
discount them by hand: a shell redirect into the reverted file (`git show
REV:f > f`, `echo … >> f`; 2 that week, 4 in the whole file), a generator run
and then discarded (`npx tsx gen.mjs; git diff out.json; git checkout --
out.json`; 3 that week), and a mutation made in an EARLIER tool call than the
revert. On 2026-09-23 seven consecutive records were
probes, two with `repeat:true`; across all 103 `paths`-scoped records then, 3 of
the 6 `repeat:true` were probes.

**Discount a subagent's revert in records written before 2026-10-23.**
`revert-detector.sh` now writes nothing for a call whose hook input carries
`agent_id` (a subagent) or that runs under `CLADE_WORKER_TASK_ID` (a dispatched
worker), once that change is installed. Before it, 172 of the 220
implicit-revert records of 2026-09-22 → 10-22 on the author's machine were
issued by Workflow subagents inside their own runs — 157 of them from a
worktree or `/tmp` working directory — and no field marks them. For older
records, set aside any whose `project` is a worktree or scratch path before
clustering, and confirm the rest against the session transcript.

**Discount a record whose only revert sits inside a heredoc body.** Agents write
files through `python3 - <<'EOF'`, and prose about git inside the body used to
trigger the hook and choose its `project` (a `cd` in a README became the
project key). Of 386 implicit-revert records up to 2026-10-05, 16 of the 323
unclipped ones contain no revert outside a heredoc body, and up to 43 clipped
ones may be the same. The hook strips heredoc bodies only once the 2026-10-05
change is installed. Before that, re-check any record whose prompt contains
`<<`.

Records written **before 2026-09-02** carry the old semantics: `reverted_files`
is the last 20 files touched in the session, never intersected with anything, and
`repeat` largely measured session length and overlap. When a cluster spans that
boundary, check the record for `revert_scope` — its absence dates the record —
and confirm the older half against the actual diff before calling it evidence.

A cluster that keeps recurring despite an existing rule means the rule is the
wrong instrument. Escalate it to something structural — a hook, a CI gate, a
test — rather than rewording the prose. The `/generate-hook` skill exists for
exactly that conversion. `configs/hooks/lib/rule-effectiveness.sh` was meant to
track which rules keep getting missed, but it cannot fire: a miss needs a
`rules.md` rule whose domain equals the correction's, and the two vocabularies
are disjoint (13 fixed technical domains vs 224 free-form ones across 681 rules
in 58 `rules.md` files, 0 shared — measured 2026-10-12). On the author's machine
`rule-effectiveness.json` has been `{}` since 2026-04-15. Until that is fixed,
find recurrence by clustering `history.jsonl` yourself, as above.

**Also read Claude Code's own verdict on our hooks.** A hook whose output Claude
Code rejects still runs, exits 0 and passes its tests, and delivers nothing.
The only record is a `hook_non_blocking_error` attachment in the session
transcript. Tally them every run (add any other profile's `projects/` dir):

```bash
grep -rh --include='*.jsonl' '"type":"hook_non_blocking_error"' ~/.claude/projects \
  | jq -rc 'select(.attachment.type? == "hook_non_blocking_error")
      | [.attachment.hookName, (.attachment.stderr | gsub("\\s+"; " ") | .[0:90])] | @tsv' \
  | sort | uniq -c | sort -rn
```

The 2026-10-19 sweep found two dead hooks this way, both with green suites,
because each suite read the hook's output and never what Claude Code did with
it: `skill-suggest.sh` (309 rejections since 2026-08-26, no `hookEventName`) and
the rewrites in `pre-tool-guardian.sh` (41, a top-level `decision:"allow"`).

### 1. Sweep broadly — probes, not topics

Run searches whose shape invites unfamiliar vocabulary. Rotate them; do not
narrow to what you already track:

- Succession framings: `"X is the new Y" AI agents`, `beyond <current paradigm>`,
  `successor to <known term>`, `what replaced <known term>`
- Vocabulary shifts: `new term AI engineering <current month year>`,
  `stopped calling it <known term>`
- Practitioner surfaces: Hacker News discussion trends, arXiv recent-and-cited,
  named practitioner blogs, framework changelogs and their *rationale* sections
- Negative space: `why <known approach> doesn't work`, `limitations of <known term>`

Bias toward the last 90 days. Prefer sources that argue rather than announce —
a post explaining why a paradigm broke names its successor.

### 2. Extract candidate terms

Pull every named concept, method, architecture, or piece of vocabulary. Keep
the term, a one-line definition **in the source's words**, and the URL.

Do not filter for relevance yet. Filtering before diffing is how a genuinely
novel idea gets discarded for looking irrelevant.

### 3. Diff against the ledger

Drop anything already listed. What remains is the discovery set.

If the discovery set is empty, say so plainly and stop. A quiet week is a real
result; manufacturing a finding to justify the run is worse than silence.

### 4. Triage each survivor against this stack

For each new concept, answer three questions, in this order:

1. **What is it, in one sentence?** Source's claim, not your paraphrase of the hype.
2. **Do we already have it under another name?** Compare *mechanism*, not
   vocabulary. `/loop` ≈ Ralph; a declared state graph ≠ an agent graph. Most
   "gaps" die here, and that is the point.
3. **If we genuinely lack it — is it a deficiency or a difference?** Name the
   concrete thing it would let us do that we cannot do today. If you cannot
   name one, it is a difference. Say so and move on.

Never mark something as a gap on step 1 alone. That rule exists in `CLAUDE.md`
for exactly this workflow.

### 5. Report, bounded

At most 5 findings, ranked by "would this have changed a decision we made".
Each gets: term, one-line definition, our status (`have it` / `different` /
`genuine gap`), and one line of evidence for that status — a file path, a
module, a command. Assertions without a locator are not findings.

### 6. Append to the ledger

Add every candidate examined — including the ones judged irrelevant. The ledger
records *encountered*, not *adopted*; otherwise the same dead end resurfaces
every run.

Format: `- YYYY-MM-DD  <term>  — <one-line definition>`

## Scheduling

Radar is worth running unattended. Weekly is the natural cadence — fast enough
that a shift is caught within a cycle, slow enough that the discovery set is
not noise.

Wire it with the `schedule` skill (cloud cron) or a local `crontab` entry
invoking Claude Code headless. Whatever runs it must be able to write
`~/.claude/research/`.

## 7. Close the loop — a digest nobody acts on is theatre

Discovery is only the first third. The pattern that actually moved this stack
was *found gap → built it → verified → committed*, inside one session. A weekly
file accumulating in `~/.claude/research/` while nothing changes is worse than
not running: it produces the feeling of keeping up without the fact of it.

So every finding graded **genuine gap** must leave a durable, actionable trace
before the run ends:

- **Small and unambiguous** (a missing check, a one-file addition): build it now,
  with a test, and say so. Do not file a TODO for work that takes ten minutes —
  identified is not the same as executed.
- **Large or a real architectural fork**: append one line to the project's
  `TODO.md` (or `BRAINSTORM.md` if the shape is still open), naming the gap, the
  concrete capability we lack, and the evidence locator. Then say plainly that
  it is queued and why it was not built now.

Findings graded `have it` or `different` need no trace beyond the ledger. Say
which of ours already covers it, with a locator — that sentence is what stops
the same idea being re-litigated next quarter.

## Output

Write the digest to `~/.claude/research/radar-YYYY-MM-DD.md` and print the
ranked findings. If run interactively, print only — the human decides whether
it is worth a file.

**When the harness refuses the write** — it treats `~/.claude/**` as a
sensitive path in every mode short of bypass, so an unattended `acceptEdits`
run cannot reach its own ledger — stage the two files under exactly these
names: `radar-YYYY-MM-DD.md` and `known-concepts-append-YYYY-MM-DD.md`, in the
directory the cron prompt names (`.radar-staged/` inside the run's worktree;
older runs used `$HOME`). `radar-cron.sh` folds both into place before and
after each sweep. Do not end the run by asking a human to `cat >>` them: four
such requests sat unactioned for five weeks (2026-08-17 → 2026-09-21) while
every sweep in between diffed the field against a ledger missing its
predecessors' findings.

**Code edits in an unattended run** go only into the worktree the cron gives
you as your working directory, on its own `radar/<date>` branch. You cannot run
bash or git there, and you do not need to: the wrapper runs `bash -n` and the
affected shell suites in a no-network sandbox, commits to that local branch
with the results, and leaves it for review — it never pushes. Do not edit any
other checkout (you cannot reach one), and do not call an edit verified. Until
2026-10-20 the agent edited whichever Clade checkout was open: the 10-12 run's
edits sat on `fix/warm-pace` for four days and the 10-19 run's on `main`.

Close with one line that is honest about coverage: which probe families ran,
how many candidates were examined, and what was NOT swept. A radar that hides
its blind spots reads as completeness it does not have.
