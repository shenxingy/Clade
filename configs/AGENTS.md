# Clade Ground Rules — vendor-neutral

This file follows the AGENTS.md open standard so that every AGENTS.md-aware
runtime reads the same text, regardless of vendor, model, or permission
mode: Kimi Code (`~/.kimi-code/AGENTS.md`), OpenCode, Goose, and any other
runtime that resolves the shared `~/.agents/AGENTS.md`. Vendor-specific
channels (`~/.claude/CLAUDE.md`, the Codex managed block) carry adapted
wording of the same rules; this file is the canonical source they adapt
from. Edit it here and re-run `install.sh`.

## Repository entry points across projects

Treat every repository's README as the product's first visit: discovery →
understanding → credible proof → first successful use. Improving the wording
alone does not complete repository onboarding work.

- Study relevant projects' rendered READMEs, media and navigation, separately
  for each product category. Record what a pattern helps a reader understand;
  popularity is not proof that the pattern improves conversion.
- Show the actual product or result near the opening: an authentic screenshot,
  recorded terminal/demo, input/output comparison, or an explanatory diagram.
  Logos and badges alone do not demonstrate the product. Match the medium to
  the project; label fixtures, illustrative diagrams and unverified behavior.
- Give a clear next action, honest prerequisites and maturity, a runnable first
  task with an expected result, and recovery/help. Keep a compact map of real
  repository responsibilities and the docs users and contributors need.
- Cover localized and separately distributed package READMEs as entry points.
  Use public relative links, meaningful alt text, readable media, maintained
  assets and real license/status information. Never expose private data or
  fabricate screenshots, testimonials, metrics or execution results.
- Inspect the rendered result on desktop and phone, light and dark, including
  image loading, enlargement, links and the first-use path. Fix the findings;
  a source-only review cannot establish visual quality or usability.
- For open-source onboarding, check that help, issue and contribution routes
  work for the intended audience. Labels alone are not starter tasks: give a
  newcomer a bounded action with an acceptance check. Match claims and media
  to the version readers can obtain; an internal feature is not a release.

Apply this during repository creation, README/setup changes and documentation
release review. The installed `document-release` skill carries the detailed
`references/repository-entrypoints.md` acceptance standard; use `frontend-design`
for visual work and report unavailable evidence instead of claiming it passed.

## Artifact reports across projects

For artifact/report pages in any project, load the installed `artifact` skill
before drafting. It selects the structure from the reader's question and owns
the rendered-output and fresh-reader review in `references/review.md`. Reuse
the project's design system; missing review evidence is UNVERIFIED. If the
skill is unavailable, name the installation gap instead of claiming compliance.
Product UI and marketing sites use `frontend-design` instead.

## External web retrieval

For web searches and URL reading, use the installed `web-search` skill to
select native tools or TinyFish, keeping analysis in the current session.
Official documentation tools and explicit provider choices take precedence.
If unavailable, use exposed native tools and name the routing installation gap.
This does not apply to repository or file searches.

## Large compute and experiments

Before large CPU/GPU experiments or data batches, load the installed `compute`
skill and read `~/.clade/compute-policy.md` when present. Apply personal host
preferences only within site rules, effective user/group/project quotas and
actual allocations; share remaining allowances across concurrent jobs/hosts.
Keep private topology and quota values out of public repositories. Inspect live
CPU/RAM/GPU/VRAM, cgroup limits, other workloads and storage. Stage network-backed hot data to verified local disk;
smoke-test correctness and recovery, then profile before choosing concurrency,
shards and backend. Prefer established schedulers and bounded dynamic dispatch.
Full resources mean durable queueing, not oversubscription. Require validated
checkpoints, an exact resume command and verified restart support before
unattended scale. Record placement, measured throughput, limits and recovery
evidence. Missing tooling or a broken scheduler is a named gap, never a pass.

## Don't block

Default state is motion. When something stalls you, climb this ladder —
never stop at a lower rung than the situation forces.

1. **Keep going.** Carry the task to completion. Reversible actions — file
   edits, test runs, builds, refactors of code you just wrote — never
   require stopping for approval or confirmation.
2. **Re-earn "stuck".** Before concluding a problem is unsolvable, check
   whether it is undecided rather than undecidable. If any reasonable
   default exists, take it, note it in one line in the workspace's decision
   log, and continue. A reversible wrong choice is cheaper than an
   unanswered question: make it, and let the outcome be reviewed.
3. **Park it, don't stop on it.** When a sub-problem genuinely cannot move
   now, write it down — what you need, what you already tried — in the
   workspace's decision or blocker log, then continue with the rest of the
   task. One open question never idles work that is independent of it.
4. **Only now wait for the human.** Stop and ask solely when the next step
   is destructive or irreversible, mutually exclusive with a plausible
   alternative, or requires credentials, secrets, or authority you do not
   have. Surface it once, with the evidence already gathered — not after
   exhausting retries — and keep everything else unblocked.

Never: retry the same failing approach in a loop; ask "should I proceed?"
or "want me to add it?"; end a turn whose only obstacle is your own
indecision.
