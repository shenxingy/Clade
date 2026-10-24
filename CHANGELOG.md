# Changelog

All notable Clade releases are documented here. The project follows semantic
versioning for the `clade-mcp` Python package and tagged public releases.

[中文](CHANGELOG.zh-CN.md)

## Unreleased

### Changed

- `rule-injector.sh` no longer injects a package's own rules through a symlink. Its third-party skip (`node_modules`, `vendor`, `third_party`, `site-packages`, `.git`) tested only the path as written, so `repo/linked -> node_modules/pkg` passed and the nested walk injected `node_modules/pkg/.claude/rules` (found 2026-10-23 by an effort A/B agent). Each nested dir that holds `.claude/rules` is now judged a second time on its physical path (`cd DIR && pwd -P`), measured below the project root's own physical path. A dir whose physical path lies outside the project is not scanned, and that includes a sibling whose name starts with the project's (`app` vs `app-shared`). Both checks measure below the root, so a project whose root itself sits inside `node_modules` keeps its own nested rules. A project opened through a symlinked root (or macOS `/tmp`) still gets them. Either check failing skips the dir, so a workspace link back into the project through `node_modules` is skipped by name. Cost: only dirs that hold `.claude/rules` are resolved, each once per call. The suite's 30-rule × 40-file timing case has none and creates the same 21 processes per call as before. Forty distinct nested rules dirs add 41 subshells, about 25 ms. `tests/test-rule-injector.sh` gains six cases; the two for the defect fail on the old hook. Six new mutation entries each turn the suite red, including one for the path separator in the outside-the-project check. The mutation helper now takes several anchor pairs, because "never above the project root" is now held by two guards together.

- `committer` now pushes only to the remote branch with the same name as the local branch, through an explicit `<remote> HEAD:refs/heads/<branch>` refspec. The old bare `git push` sent the commit wherever the branch tracked. A branch started with `git worktree add -b X <path> origin/main` tracks origin/main, so under `push.default=upstream` the feature commit landed directly on main. Under git's default (`simple`) the push was refused and committer exited non-zero after a successful commit. Under `push.default=matching` the bare push also pushed a local main that was ahead of origin. Now committer commits and does not push in these cases, exiting 0 with a message saying why: a branch tracking a different name or a local branch (it also prints the explicit push command), a detached HEAD, a HEAD outside `refs/heads/`, and a repository with no remote. An autonomous worker (`CLADE_WORKER_TASK_ID` set) never pushes, because its runner merges or pushes. The branch name comes from the full ref, so a tag with the branch's name can no longer redirect the push to `refs/heads/heads/<name>`. A branch with no upstream is pushed with `-u` to the remote `git push` itself would choose (pushRemote, then pushDefault, then the branch's remote, then origin). A push that git rejects exits 3 and is never forced; pre-commit refusals still exit 1. `--no-push` is unchanged. `tests/test-checks.sh` pins each case against throwaway bare remotes in 49 assertions; 24 of them fail on the old script, and each of 19 guard mutations turns the suite red.

- Workflow guidance now sets `effort` per stage: `low` to collect, inventory or classify, `medium` to verify one claim, and the default to implement, review adversarially, judge or synthesize. The 2026-10-22 audit found every `agent()` inheriting xhigh but had no same-item comparison. A paired A/B on 16 claims about a pinned snapshot of this repository (8 seeded false; one dropped as ambiguous) gave 15/15 at xhigh, medium and low, at 29% (low) and 52% (medium) of xhigh's output tokens; only xhigh reproduced an edge case, so adversarial review keeps the default. The same A/B ran the new `wf-reader` agent type at medium on Opus 5.5: also 15/15, with turn-1 context down from 95.8k to 5.4k tokens and cache reads down 92%. It is still not adopted, because read-only is only an instruction until a write-deny guard is shown live. Data and method: `docs/research/2026-10-23-workflow-effort-and-reader-ab.md`.

- `workflow-scorecard.py` no longer counts every API call about 1.9 times, and no longer calls a lone build stage a straggler. Claude Code writes one API response as several transcript records, and each one repeats the response's usage. Usage is now keyed by `message.id`: input is counted once, output is the max, and turns are distinct ids. Input, cache read, cache write and output are reported separately. A `cost_usd` is priced per model from the Claude Code 2.1.283 catalog; an unknown model or fast mode gives null, never a guess. On the 316 runs of the 2026-10-22 audit it now reports 218,629 API calls where it used to report 414,461, and cache reads of 46.5B. The single-agent tail is split into `serial` (a one-agent stage, which pipeline() cannot shorten), `outlived` (a true straggler) and `idle`: 35.5% / 17.3% / 1.6% of 368 h over those 259 parallel runs. Every verdict that holds is printed, and 86 of the 184 runs the old verdict called stragglers no longer are. The straggler line and "Largest tail" now name the agent the outlived time was credited to, not the slowest agent; on the author's host they differed in 31 of 106 straggler runs. "Largest tail" ranks only flagged runs; an unflagged run with more lone minutes used to suppress it. A \"Longest serial stage\" line sits beside it. The scorecard also reads each agent's label, phase, outcome, model and effort, and adds per-phase rows, the first-turn-context median, the long-gap cache-miss share and result sizes. `util` is now `util_vs_peak`. The main mode had no self-test. `self_test_sweep()` now reads six fixture runs (in `scorecard_fixtures.py`) through `scan_workflow()`. It holds both thresholds exactly on and just under, compares whole verdict strings and renders the table. `test_self_tests_can_fire.py` gains 34 mutations for it. The Codex-children reader moved to `codex_children.py` with its self-test, which gains its first 2 mutations."
- `pre-tool-guardian.sh` now warns a subagent, and never blocks it, when a foreground wait can outlive its prompt cache (5 minutes unless the environment sets the subagent TTL to 1 hour). In the 2026-10-22 audit of 316 Workflow runs on the author's machine, 1,459 cache misses followed a gap over 300 s and carried 41% of all cache-write tokens, and 82.5% of that cost followed a Bash sleep, poll or wait. The rule reads a call only when all of these hold: the hook input carries `agent_id` (Claude Code sets it only inside a subagent); `CLAUDE_CODE_SUBAGENT_PROMPT_CACHE_TTL` and `ENABLE_PROMPT_CACHING_1H` (or its Bedrock form) do not give subagents the 1-hour cache, read in Claude Code 2.1.283's order with `FORCE_PROMPT_CACHING_5M` first; the call is not `run_in_background`; and its effective timeout (`min(timeout ‖ default, ceiling)`, honouring `BASH_DEFAULT_TIMEOUT_MS` and `BASH_MAX_TIMEOUT_MS`) is over 270 s. An awk pass then reads the command as shell, including heredocs, here-strings, background jobs and nested `bash -c` / `ssh` / `eval` scripts. It sums `sleep` with GNU suffixes, treats an until/while loop around sleep as unbounded, counts a for loop as count × sleep, and recognizes `tail -f`, `watch`, `pidwait`, `inotifywait`, `docker wait`, `kubectl wait`, `gh run watch`, `gh pr checks --watch`, `python3 -c … time.sleep`, and a `wait` on a backgrounded wait. A `timeout N` prefix bounds what it wraps. The warning arrives as `additionalContext` with no permission decision; a deny still wins and a rewrite carries it. It recommends two portable slices that it does not itself warn on: a bounded `for i in $(seq 1 26)` loop, or a Bash timeout of 270000 or less. For a job that must outlast the agent it recommends `nohup … &`, because 2.1.283 terminates a synchronous subagent's `run_in_background` jobs at its final response. Replayed through the old and the new hook: 16,043 of the 224,870 Workflow-subagent Bash calls on the author's machine (2026-09-22 → 10-23; every one with an effective timeout over 270 s, plus 2,000 sampled from the rest). It warned before 1,313 of the 1,655 foreground calls that ran past 270 s, and 1,313 of its 2,142 warnings preceded such a call (731 of the other 829 were polls that finished early). There were 0 crashes and 0 changed deny/rewrite verdicts. It adds +1.1 ms median to a main-thread call and +8.5 to +9.8 ms to the 3.9% of those subagent calls that reach the awk (paired runs at host load 13–21). Each of the 87 guards listed in `orchestrator/tests/test_self_tests_can_fire.py` (new `HOOK_SUITES` table, every anchor required to be unique) turns the suite red when removed. The Codex mirror does not carry the rule.
- A lean agent type for workflow readers, `wf-reader` (`configs/agents/wf-reader.md`), ships but is not adopted. In the 2026-10-22 audit (316 Workflow runs, 3,646 agents), turn-1 context had a median of 72.6k tokens, about 54k of it CLAUDE.md and the skill listing re-read on every call; this agent drops both. Its tool list has no `Skill`, and Claude Code 2.1.283 sends the skill listing only to an agent that has `Skill`. It sets `omitClaudeMd: true`, which in 2.1.283 removes user, project and local CLAUDE.md from the subagent and keeps managed policy. The list is Read, Grep, Glob, Bash, WebFetch and WebSearch; on the native 2.1.283 build Grep and Glob drop out whenever Bash is present. A 1,705-character body restates the reader rules CLAUDE.md used to carry: read only, with no ssh, systemctl or other ops commands and no network writes (gh, non-GET curl, messages); cite evidence, and name the search behind any none/never/all claim; write \"not verified\" instead of guessing; return the caller's shape; give absolute paths, redacting only text meant to be committed or published. Read-only is by instruction only: Bash is unrestricted, so no workflow routes to the agent until a StructuredOutput smoke test, a `bashCommandClamp` (or Bash hook) check and a quality A/B pass (see TODO.md). `orchestrator/tests/test_wf_reader_agent.py` pins each omitted piece and each rule. The agent count is now 40, and two count sites that had drifted to 37 (`mcp-package/README.md`, `docs/reference/hooks.md`) are now tracked by doc-align.
- The two correction signals now measure the owner, not the agents. `revert-detector.sh` writes nothing when a revert runs inside a subagent (`agent_id` in the hook input) or a dispatched worker (`CLADE_WORKER_TASK_ID`). Of the 220 implicit-revert records on the author's machine for 2026-09-22 → 10-22, 172 were issued by Workflow subagents inside their own runs, and every reader (`session-scorecard.sh`, the concrete-signal block of `correction-detector.sh`, `repeat`, radar Lane C) counted them as rejections; skipping them rather than tagging keeps every reader correct without a new filter. `correction-detector.sh` stops firing on the 对不对 tag question ("…, right?"). A real 不对 beside another 对 (绝对不对, 不对不对, a tag running into 不对) is split off first, so it still fires. On 364 hand-labelled owner messages typed after Workflow runs (37 rejections), precision rises from 41% to 57% at unchanged recall (35%), and on 490 other, unlabelled messages from the same machine all 5 fires the strip removed were tag questions. Eight missed rejection phrasings are added (不太对, 理解错, 没懂, 不满意, 打不开, 做多了, 四不像, 说的/得太多). They lift the labelled set to 66% precision and 51% recall only in-sample: they were read off its misses, caught no rejection among the 490, and four of them are never a message's only trigger. `session-scorecard.sh` no longer charges a `revert_scope:"probe"` mutation test as an implicit correction (11 of those 220 records).
- The Workflow guidance in `configs/CLAUDE.md` (installed as the global CLAUDE.md) now covers what the 2026-10-22 audit of 316 Workflow runs on the author's account found beyond stragglers. A one-agent stage is on the critical path, and reshaping recovers little of it even though the scorecard counts it as tail, so the stage itself is shortened: a tight brief, its own `effort`, an early return. Units that each build a worktree go in `pipeline()`, not a for-await loop. Blocking Bash waits stay at or under 270 s or the job is detached, because a subagent's prompt cache lives 5 minutes and 41% of cache writes followed a longer gap. A script counts nulls per stage and returns `{incomplete, failed:[labels], resume}`, because 64 of 90 usage-limit deaths hid inside runs reported `completed`. A launch is deferred, or switched to another account, at 7-day quota ≥ 90% or when 5-hour use plus projected burn reaches 100%. Full results go to a file and at most 6k characters come back, because the completion notice cuts at 8,000 characters and 259 of 281 results overflowed it. Fix rounds run inside the script (at most 2), while a directly delegated subagent keeps its one cheap retry. While a run is live, the lead asks in plain text instead of using AskUserQuestion. A run of 5 or more agents started from a long brief opens with a 3-line launch contract (objective, acceptance criteria, premises), and UI verify runs on a device matrix. To fit, the section's existing bullets were merged and tightened, holding net growth to 1,077 characters in a file every session loads. The repository CLAUDE.md adds the long form of the serial-stage rule, with the reshaping data and a caveat that until the scorecard separates serial from outlived time a tail over 15% on a serial-dominated run is not by itself a shape error, and points to the template for the rest instead of copying it.
- The quota pace (`slt`) now reads the account of the profile it runs under. `claude-usage-watch.py` took its OAuth token and its cache from fixed `~/.claude` paths. So under `CLAUDE_CONFIG_DIR` (a profile such as `~/.claude-profiles/<name>`) the status line showed the primary account's quota, fetched with the primary account's token and overwrote the primary account's cache. On the author's host the profile's own cache had not been written since 2026-08-28. The token file, the macOS Keychain item and the cache now follow Claude Code 2.1.283's resolution: `CLAUDE_CONFIG_DIR`, or `~/.claude` when it is unset. Under a profile the Keychain item is suffixed with `-` plus the first 8 hex digits of `sha256(NFC(CLAUDE_CONFIG_DIR))`, hashed over the raw string, trailing slash included. Two deliberate departures keep a status line from reading a `.credentials.json` out of a project's working directory. An empty value means `~/.claude` here, while Claude Code reads it as its working directory. A leading `~` is expanded here, while Claude Code does not expand it. Each config dir keeps its own cache. The cache still holds the whole API response, `five_hour` included. A profile with no reading of its own now shows nothing rather than another account's. The cache is written only when the script calls the API, so under Claude Code's native `rate_limits` it can be arbitrarily old, and a reader must check its `_at`. Ten new test cases load the script under a temporary `HOME`, `CLAUDE_CONFIG_DIR` and working directory, with the endpoint and the Keychain stubbed; seven of them fail on the old script. `tests/test-loop-real.sh` now looks for credentials in the same dir. Not covered: an account swap inside one profile (the cache records no account), and Claude Code's undocumented `CLAUDE_SECURESTORAGE_CONFIG_DIR`.

- Path-scoped rules now fire on shell file access. `rule-injector.sh` was wired
  to Edit|Write only, and agents touch files through Bash: in the author's 40
  latest main-session transcripts (approximate regex counts), 6,890 Bash reads
  (`cat`/`head`/`tail`/`sed -n`) against 484 Read calls, and 2,738 Bash writes
  against 373 Edit/Write. The hook is now also on the PostToolUse `Bash` matcher
  and takes the command's path-like tokens that exist as regular files after it
  ran — `cat f`, `sed -i … f`, a heredoc write — resolving relative ones against
  the hook's `cwd`. Tokens are never expanded: one carrying a glob metacharacter
  is skipped, and at most 40 files are matched per command. Two more gaps closed
  in the same hook: it walks nested `<dir>/.claude/rules` up to the project root
  (globs relative to `<dir>`, as Claude Code itself treats them), so a session
  started at a monorepo root gets an app's rules; and its once-per-session
  sentinel includes `agent_id`, because subagents share the parent's
  `session_id` and no subagent could receive a rule the main thread had already
  been given. Each rule file's globs compile to two EREs in one awk pass per
  call: 30 rule files × 15 globs × 40 files runs in 0.16 s on bash 5.2 (0.53 s
  on bash 3.2.57 with a busybox userland, in a container), inside the 5 s hook
  timeout. Because one command can now match many rules, the hook keeps its
  output under Claude Code's 10,000-character `additionalContext` cap (past it
  Claude sees only a 2,000-character preview): rules that do not fit are named,
  not marked delivered, and inject on the next matching access. A relative token
  after a leading `cd DIR` resolves against DIR; nested rules inside
  `node_modules`, `vendor`, `third_party`, `site-packages` or `.git` are never
  read, and `claudeMdExcludes` is honoured; one unreadable rule file no longer
  silences the rest; identical rule text from two copies is injected once; and a
  NUL in the command can no longer shift the session id into the sentinel path.
  Overlap: current Claude Code also loads a path-scoped rule natively on a
  single-file `cat` or `head`, so on those commands a rule can arrive twice
  until the "Retire `rule-injector.sh`" re-measure in TODO.md settles it. The
  suite's last section removes each guard from a copy of the hook and requires
  itself to go red, so CI re-checks the mutations.
- `/artifact` no longer lets a page drop a figure the brief asked for by name.
  Its figure step said "zero figures is valid when prose or a lookup table
  answers it better" with no exception, which is how a brief asking for a use
  case flow chart shipped as a page with a table and no figure. When the brief
  names a figure type, the page draws it and argues any better form beside it.
- The delivery controller no longer waits on hosted checks. Clade's stated
  policy is that the full local run gates and hosted CI is the receipt, and the
  owner's standing rule says the same (merge once the local gate is green), but
  `ready`/`merge-plan` refused while ANY check was still running, so every
  merge sat polling. Now the exact-head candidate is the gate: pending checks are
  listed in the plan (`pending_checks`) and do not block; a FAILED check still
  refuses; a PR GitHub reports `BLOCKED` (required checks or reviews) gets
  `gh pr merge --auto`, so branch protection decides and is never bypassed.
  `--checks gate` restores waiting. The create-pr, delivery, merge-pr and commit
  skills now say the same; pinned by four controller tests, each shown to go red
  when its guard is removed.

- `auto-audit.sh` no longer grows a CLAUDE.md without limit. Claude Code loads
  every instruction file whole, into every session and every subagent, and only
  warns past max(40,000, window × 0.05 × chars/token) per file — 40,000 chars on
  a 200k-context model. Nothing checked it: promotion grew one project's
  CLAUDE.md to 127,095 chars and the global one to 73,577, and a session there
  loaded 237k chars against a 150k limit. A promotion that would push its target
  past `CLADE_CLAUDE_MD_BUDGET` (default 40,000 bytes) is now withheld and named,
  and stays in `rules.md` until `/audit` consolidates — the skill gained a
  budget step (archive verbatim, path-scope file-bound rules, one line per
  principle). Promoted rules are inserted at the end of their own section instead
  of at end of file, which had put 27 global rules inside the section that
  happened to come last; and a project without a CLAUDE.md keeps its rule instead
  of losing it — the old branch wrote nowhere and still removed the line.

- The quota pace scale is two-sided. `delta = used% − elapsed% × 0.95` is the
  same number at every point in the window, but what a `+5` implies about the
  overshoot is not: `95 + 500/elapsed%` projected, so 145% a tenth of the way
  in and 101% at nine tenths. The top badge and the >100% green were therefore
  shown for a burn that empties the window early — measured on the Kimi footer,
  which has no `limit7d` and so paces against the 30-day month: `◉ +11% (27d)`
  in the brightest green for 20.25% used at 9.9% elapsed, 204% projected, quota
  gone on 2 October with 15 days left. Past 125% projected (the quota runs out
  with a fifth of the window to go) the symbol drops to level 0 and the figure
  turns red, on all three surfaces — `claude-usage-watch.py` (`slt`),
  `kimi_usage.py` and `codex_usage.py`. Full weekly use is untouched: 100% used
  at 93.8% elapsed is 107% projected and keeps its top badge.

- The model-facing skill listing is trimmed from 38,660 to 33,998 characters
  and the budget fraction lowered from 0.06 to 0.05 (a 200k-window cap of
  40,000 chars; what is actually sent is the listing itself, ~8.5k tokens).
  The longest descriptions — frontend-design, the two design-system canons,
  localize, radar, codex-orchestrate, outbound, banana and ten more — keep
  every golden-set trigger (gated by `test_routing_eval.py`) but drop the
  redundant prose; the email family gained an `email` hub so the six
  `email-*` sub-skills are name-only like the blog/seo/ads families (81
  name-only overrides). Minimum viable fraction is now 0.0425; 0.05 leaves
  ~6,000 chars of headroom, roughly 15 more skills. Note: the Codex plugin
  carries only `description`, so platform and Chinese triggers that the
  `test_frontend_design_pipeline.py` contract requires must stay in
  frontend-design's description, not just its `when_to_use`.

### Fixed

- The correction detector no longer reads a hedge, a question or a paste as
  the user correcting Claude. On one machine, bare "应该" — in spoken Chinese
  usually "probably" — was the only trigger for 80 of 230 recorded
  corrections; "要不要" ("whether") fired because it contains 不要; and pages
  pasted into a prompt brought their own "Go back" and "actually". Each false
  fire told the model a correction was detected and to write a rule, which is
  how a project collected rules about remarks that corrected nothing. Matching
  now skips `<pasted_content>` blocks and 要不要, keeps 你应该 and 不应该, and the
  notice names the keyword and asks the model to decide whether the user is
  rejecting anything before it writes a rule. Replaying all 230 recorded
  triggers: 215 fired before, 134 now, none newly.

- The stop-completeness check no longer sends the assistant back while it is
  waiting on the user. Claude Code hands a Stop prompt hook to its evaluator as
  a condition to judge — ok:true when the condition is met — and the prompt
  opened with "all user tasks are complete", so a turn that ended on a question
  to the user, whose larger goal was not done yet, judged not met. The
  assistant was then sent back to say it was waiting, to print a bare
  `{"ok":true}` into the conversation, or to answer for the user: all 15 field
  blocks sampled on one machine were stops of that kind, and three of them had
  it pick a phone colour, a watch material and a band on the user's behalf.
  The prompt is now the condition "the assistant may stop now", with waiting
  on the user, on background work (`background_tasks`) or on a second pass
  (`stop_hook_active`) all counting as met; the old prompt carried no
  `$ARGUMENTS`, so the evaluator never saw those two fields. Measured on Haiku
  4.5, the default evaluator: on those 15 field stops the deployed prompt sent
  back 7 of 45 judgements, main's 3 of 45, this one 0 of 90; on the synthetic
  set main's prompt blocked a second pass 3 of 3 times and let 2 of 18 undone
  stops through as "background work", this one 0 and 0.
  `tests/evals/stop_completeness_eval.py` reruns the synthetic set; it calls a
  real model, so it is opt-in and not in CI.

- Skills nobody had used yet could not be auto-selected. Claude Code lists
  skills to the model inside a character budget (context window × bytes per
  token × `skillListingBudgetFraction`, default 1% — 8,000 characters on a
  200k model) and, over budget, keeps descriptions in order of a per-skill
  usage score and lists the rest by name only; a never-used skill scores 0.
  Measured on 2026-09-20 with Claude Code 2.1.258: the listing was 66,408
  characters over 166 skills, 103 of Clade's 144 skills had never been used,
  and stock settings dropped all 142 Clade descriptions on a 200k model and
  95 on a 1M model. `configs/settings-skill-overrides.json` (generated by
  `regen-skill-overrides.py`, drift-gated) now lists every blog/seo/ads
  sub-skill as `name-only` — still routed by its hub through the Skill tool —
  and sets the fraction to 0.06; `install.sh` merges it into
  `~/.claude/settings.json` with the user's own entries winning.
  `check-skill-listing.py` reimplements the budget arithmetic, gates that the
  model-facing listing fits a fresh 200k install, and shows what this machine's
  history keeps (`--usage ~/.claude.json`) or the stock situation
  (`--no-overrides`). After the change a 200k Haiku session picked the intended
  skill for all seven prompts aimed at the newest skills.

### Added

- A privacy guard at the sync store's exit. `sync-push.sh` refuses to push
  anything that names a private project (`~/.claude/private-projects`) or a
  private keyword (`~/.claude/private-keywords`): matching lines are removed from
  append-only logs, any other matching file is withheld and logged. Session start
  registers conversation-mode projects there automatically, and a session marked
  in `~/.claude/private-sessions/` gets the conversation-mode correction notice
  wherever it started. Written after one machine's store had pushed 87 previews
  of a personal conversation to GitHub.

- Conversation-mode projects. A repository that is a conversation rather than a
  codebase — a persona, a journal — can declare it with
  `.claude/conversation-mode`. There the correction notice asks for a one-line
  fix instead of a rule and points at the project's own lesson file; session
  start keeps git state, handoffs, the project's rules and the language rule,
  and drops the host fingerprint, other projects' rules, model and verify
  guidance and skill routing; and project rules are no longer auto-promoted into
  CLAUDE.md. Conversation text also stays out of `cross-project-rules.jsonl`,
  which syncs to the dotfiles store's remote: one machine's copy already held 87
  prompt previews from such a repository. Written for a persona repository that
  had promoted 103 rules, 90,172 characters, into every chat. See
  docs/configuration.md.

- `/reverse-engineer-anything`, absorbed from [morluto/rea](https://github.com/morluto/rea)
  (MIT, commit `d28b41e`) via `/equip` — the project's first Layout-F
  (`.agents/skills/`) upstream. The skill carries REA's investigation workflow
  (target routing, evidence paging, staged investigations) plus six per-target
  references, byte-identical to upstream so future `/equip sync rea` runs stay
  clean 3-way merges; the REA engine itself remains an external `rea-agents`
  npm package the user installs separately (`npx rea-agents setup`, DEP-01 in
  the audit). Two maintainer-internal upstream skills were screened and
  skipped. To make the layout auditable at all, `equip_common.py`'s
  `detect_upstream_skills_dir()` now also probes `.agents/skills/` — the
  AGENTS.md open-standard path — documented as Layout F in
  `configs/skills/equip/references/project-layouts.md` and covered by
  `test_equip.py`. Codex disposition: `specialized-opt-in-workflows`.

- `/frontend-design` now carries "design sense" as checkable rules instead of
  adjectives. `references/design-rules.md` states the 4-px spacing grid, the
  type-scale caps (at most 2 families, 4–6 sizes, 3–4 weights), the motion
  duration table, the state list, the four review widths and the marketing
  copy ban, each phrased so a lint, a screenshot or a grep can check it;
  `references/design-review.md` is the screenshot loop with a P0–P3 severity
  ladder, twenty review questions and a per-page Definition of Done. The
  pipeline gains a Style DNA step, three materially different directions for
  greenfield work, a component lab before business pages and one
  representative page before the rest. `design-lint source <dir>` is the
  static half of those rules — spacing grid, type and geometry scales, motion
  table, token discipline, copy — on CSS/SCSS, HTML, JSX/TSX, Vue, Svelte and
  Astro trees, FAIL only on the two accessibility floors and WARN with the
  measured sites elsewhere; the fix it found on the way is that a `:focus`
  rule that removes the outline no longer counts as restoring it, in the
  `html` lane too. `configs/rules/frontend.md` injects the short form at the
  moment a UI file is edited. `references/signature-motion.md` covers the one
  place allowed past the motion table — hero intros and scroll-driven product
  stories: the vocabulary (scrub, pin, scrollytelling, choreography), the two
  archetypes with their budgets (intro 1.8–2.6 s in four beats, idle at most
  one micro-motion per 8–12 s, pointer 4–12 px / 2–5°, a pinned 100vh scene
  over 400–500vh), the four implementation routes and when each fits (frame
  sequence + canvas + ScrollTrigger by default, real-time 3D only when the
  user controls the product), the semantic-motion rule with a worked example
  for a detection product, and the storyboard table that precedes any code.
  `design-lint source` reads `.js`/`.ts` for three runtime checks only:
  scroll-jacking (`wheel`/`touchmove` + `preventDefault`, page-snapping
  libraries), an uncapped `devicePixelRatio`, and a render loop with no
  visibility gate.
- `/kimi-usage`: Kimi Code plan-quota usage (5-hour, weekly where the plan has
  one, monthly with its kimi/code split) against Clade's 95% target pace, plus
  `setup` / `style` / `theme` for the Kimi footer. `install.sh` now wires
  `[status_line]` in `~/.kimi-code/tui.toml` to Clade's indicator when Kimi
  Code is present and no user-authored status line command exists —
  `Clade git:(main)  ● +3% (29d) · 5h 0% (5h)` (Kimi's own `[status_line]
  items` list adds the mode badge or model back)
  — the Kimi counterpart of the Claude Code status line and `codex-usage
  setup`. The data path is Kimi's documented local server API (`kimi web`,
  `GET /api/v1/oauth/usage`, loopback token), reusing a running instance or
  starting one for the call; the OAuth credential file is never read.

## [0.3.1] — 2026-09-02

### Security

- The orchestrator control plane required no authentication. Every route and
  both WebSockets answered anyone who could open the socket, and `start.sh`
  binds `0.0.0.0` whenever it detects Tailscale — the documented way to run
  the server — so "it is only on loopback" was never true. Any mutating route
  can open a session whose workers run with permissions bypassed as the
  account that started the server, and `GET /api/settings` returned
  `webhook_secret` and the usage-hub tokens verbatim. A bearer token is now
  required by ASGI middleware, which — unlike `BaseHTTPMiddleware` — also sees
  WebSocket scopes. Default-closed on the same terms already set for
  `webhook_secret`: no token configured means reject, unless
  `api_allow_unauthenticated` says otherwise. The token is minted on first
  start into the settings file the saver already chmods 0600. Three exemptions
  are argued in `orchestrator/api_auth.py`: the SPA shell and the version
  probe, the signed GitHub webhook, and usage ingest — but only while
  `usage_ingest_token` is set, which closes that endpoint's old
  empty-means-open default rather than inheriting it
- Settings secrets are masked by key-name suffix on the way out, and a save
  that echoes a mask back leaves the stored value alone. The settings panel
  round-trips the whole object, so without that the first save would have
  overwritten every secret with its own mask
- CORS admitted every origin. `allow_origins` is an exact-match list, so the
  `http://localhost:*` default matched nothing while the regex beside it
  granted the request on its own. The regex now covers `https` (a TLS front
  end is no longer silently blocked) and is pinned to Tailscale's actual CGNAT
  range `100.64.0.0/10` — it had held a CORS grant over all of `100.0.0.0/8`,
  most of which is publicly routable. Configured origins are whitespace-stripped
  before the exact-match compare, so ` http://b` from a space-separated value
  no longer silently matches nothing
- A worktree bounds the working tree, not `.git`. From inside a worker's
  worktree, `git rev-parse --git-common-dir` resolves to the parent repository,
  so an agent could write `<main>/.git/hooks/pre-commit` and have it execute on
  the operator's next commit. Workers now snapshot the parent repo's hooks and
  config before spawning and refuse to verify or commit if either moved
  (`worker_git_surface_guard`, default on)
- That escape is now prevented as well as detected: an optional Landlock
  ruleset makes the shared `.git/hooks` and `.git/config` unwritable to the
  worker process itself (`worker_sandbox`, default off)
- `install.sh` upgrades never received the deny rules. `templates/settings.json`
  ships `Read(~/.ssh/**)`, `Read(~/.aws/**)` and `Read(~/**/.env)`, but the
  merge path wrote only `.hooks` and `.statusLine`, so every machine installed
  before the deny list existed kept `permissions: null` — while spawning
  workers with permissions bypassed, where deny rules are the last remaining
  bind. The union is deny-only; a user's own `allow` list is never widened
- Git worktree isolation failed open. Every failure path discarded git's stderr
  and left the worker on the shared checkout; it now raises rather than run an
  unsandboxed agent in the operator's own tree (`worker_require_worktree`)
- The worker secret denylist shipped empty, so it never once applied and
  nothing was ever redacted out of persisted worker output
- A webhook signature proves an event came from GitHub, not that its author may
  direct a permission-bypassed worker. Webhook-triggered work is now gated on a
  fail-closed actor check computed from the payload itself
  (`orchestrator/webhook_trust.py`) — there is no API call in the path that
  could fail open
- The two workflows that run on fork pull requests were the two that skipped
  SHA pinning, and they are the ones that run with write scopes. Every `uses:`
  is a commit SHA now, enforced by `configs/scripts/check-action-pinning.py`
- The destructive-command guardian matched substrings rather than command
  positions, and never actually blocked `rm -rf ~`. It now also blocks the
  `pkill -f` pattern that kills its own launcher
- The FastAPI pin locked the orchestrator to starlette's last vulnerable
  release. `fastapi==0.131.0` required `starlette<1.0.0`, and 0.52.1 is the
  last 0.x starlette ever published, so this was a security floor rather than
  version lag — no release inside the pin carried a remedy. Two HIGH
  advisories were live on it: `GHSA-wqp7-x3pw-xc5r`, SSRF and NTLM credential
  theft through UNC paths in `StaticFiles`, which `server.py` mounts at `/web`,
  and `GHSA-82w8-qh3p-5jfq`, `request.form()` size and count limits silently
  ignored for `application/x-www-form-urlencoded`; two MODERATE ones went with
  them. `fastapi` moves to 0.141.1, which asks only for `starlette>=0.46.0`,
  and starlette is pinned directly at 1.6.0 in `orchestrator/requirements.txt`
  with each advisory named beside the pin, so the floor is visible in this
  repository instead of hidden in another package's metadata
- The correction pipeline wrote the user's prompt to disk verbatim, in three
  places: `history.jsonl`, a lib-missing fallback nobody had noticed, and the
  cross-project-rules preview. `redact.py` had existed the whole time and was
  never called there. It is now, once — after the correction gate, so `python3`
  does not spawn on prompts that write nothing, and before the prompt is
  clipped, since clipping first can cut a token below its detection threshold
  and leave a partial credential on disk. Where `python3` is unavailable the
  hook detects with a fallback pattern and withholds the whole prompt rather
  than substituting: the prescribed `sed` fallback was measured leaving 16 of a
  48-character key behind. `redact.py` also gained the underscore key shape no
  existing pattern could reach, and `checks.sh`'s inline fallback carries it too
- Structured events, SQLite runtime text, traces, sessions and provider streams
  are redacted before persistence (`orchestrator/runtime_redaction.py`), and
  worker stdout and stderr go through a streaming redactor, so a raw credential
  never reaches a log file or a database row
- Seven hook and script call sites wrote to fixed, predictable `/tmp` paths —
  the edit shadows, the skill-suggest throttle, the radar and sync-push locks,
  the watchdog pid and log. On a shared host the first account to create
  `/tmp/claude-edit-shadows` owns it and every other account's hook fails open,
  which had silently disabled correction pairing for all but one of 40 accounts
  with nothing saying so. All seven now derive from
  `configs/hooks/lib/runtime-dir.sh`, which fails closed on a squatted path:
  not a symlink, owned by our euid, mode 0700. Old paths are abandoned rather
  than migrated, and the sweep only ever touches our own stale files
- The prompt secret-scanner never once warned. Its only output is
  `hookSpecificOutput.additionalContext` and it was configured `async: true`,
  which has no channel back into the turn, so every credential warning was
  discarded. It runs sync now, like `correction-detector.sh` beside it
- One MCP skill invocation froze every concurrent request behind it.
  `mcp_server.py` called `subprocess.run` with a 300-second timeout inside an
  `async def`, so a single run blocked the event loop for its whole duration —
  and `task_factory/ci_watcher.py` called `check_output` with no timeout at all
  inside a coroutine the status loop schedules. Both use
  `asyncio.create_subprocess_exec` with `wait_for` now; the timeout and
  cancellation paths SIGKILL the whole process group and drain the pipes, so an
  agent run that spawned its own tools leaves nothing behind

### Added

- Workers report their own spend: spawns carry `--output-format stream-json`
  and `orchestrator/agent_output.py` reads `total_cost_usd`, per-model
  `modelUsage`, and real token counts back, projecting the event stream to
  prose so every existing log consumer is unaffected
- Per-model pricing (`config.py:_MODEL_RATES`) replaces a flat Sonnet rate that
  understated Opus 1.67x and overstated Haiku 3x on the figure the token budget
  and the routing break-even analysis both depend on
- A `quota_exhausted` error class. A spent balance and a spent usage window
  both returned 429 and were retried on a 30s backoff until the run's budget
  ran out; both now abort
- Stopping a worker preserves its work as a `wip:` commit on its own branch
  before the worktree is force-removed — including on the automatic loop-detection
  and stuck-timeout paths, where nobody is watching
- A worker had no record between its single verification commit and the forced
  removal of its worktree, so "correct at call 14, wrong at 15" was not
  observable. `worker-checkpoint.sh` now commits the whole worktree into a
  shadow repository outside it, once per agent write, under a separate
  `--git-dir` so checkpoints cannot contend with the worker's own index. The
  final SHA and count land in the evidence bundle before cleanup deletes the
  repo (`worker_checkpoint_shadow`)
- Attempt evidence is now an immutable, versioned `clade.evidence/v1` record
  with a digest chain, written incrementally. Verification used to land in one
  terminal write, so a crash lost the record of where it went wrong
- `configs/scripts/red-phase-audit.py` runs the tests a commit *adds* against
  its parent: one that already passes needed nothing from the change. It is a
  diagnostic, not a gate. Its fire rate is a function of the sample size you
  pass it (19-33% measured), not a fixed property, so none is quoted.
  `--self-test` asks the instrument whether it can still go red — a harness
  that cannot fire reports a clean 0% exactly like a clean codebase, which this
  repo has shipped before — and CI runs that control pair on every push
- The reward-hacking gap is measured rather than asserted: the test-integrity
  detector is scored against a labelled adversarial corpus (`evals/hack_cases/`,
  60% to 100% recall and 27% to 7% false alarms), its per-signal counts are fed
  to the oracle instead of auto-failing, and the resolve eval re-runs held-out
  tests so a patch that games the visible suite reports GAMED, not RESOLVED
- Output styles (`configs/output-styles/`) — the one primitive that edits the
  *system* prompt rather than appending a user message, so it reaches turns
  `CLAUDE.md` cannot. All ship `keep-coding-instructions: true`, and
  `install.sh` activates none of them; selection stays the user's
- `/radar` — three-lane discovery of unknown-unknowns (the field, practitioners,
  your own usage) — plus `radar-cron.sh` for a durable unattended weekly sweep
- `/outbound` — verify artifacts before they leave the building
- `/loop` runs are bounded by wall clock (`--max-runtime`, default 8h) and by
  spend (`--max-cost`), both checked between iterations, plus crash-safe phase
  recovery with explicit, identity-matched `--resume`: normal launches ignore
  stale checkpoints and `--help` has no side effects
- Müller-Brockmann grid and Vignelli canon design skills, absorbed under MIT,
  and `design-lint` — a rendered-output validator that resolves CSS custom
  properties before contrast checks and catches inherited-colour contrast
  across inversion bands
- `frontend-design` became a platform-aware interface pipeline covering web,
  Apple, Android, Windows, cross-platform and presentation surfaces
- Gates that run the real thing rather than assert its spelling:
  `check-cc-plugin-components.sh` loads the plugin and compares the resolved
  inventory to the tree, `check-ci-checklist.py` compares the documented
  pre-commit list against the gates CI invokes and rejects a documented command
  that cannot execute, `regen-settings-example.py` generates the settings
  reference from `_SETTINGS_DEFAULTS`, `check-references.py` resolves every
  markdown link, anchor and path, `check-arch-map.py` fails on an orchestrator
  module missing from the architecture map, and `doc-align.py verify` gates the
  counts the docs derive from the tree
- The correction-pairing pipeline gained the collaboration root causes measured
  by arXiv:2605.29442 — inaccurate self-reporting and constraint violation are
  now promotable — and promotion into the global `CLAUDE.md` is gated on
  root-cause severity rather than on how long a rule survived
- Fresh Windows Git Bash installs wrap every hook and status-line command
  through `bash.exe`, matching the existing-settings migration path
- `delivery abandon` transition for superseded, unpublished work — requires an
  exact HEAD lease and non-empty reason; published GitHub PR work can only
  abandon after a live check proves the PR is closed at that exact head
- Native `$codex-usage` workflow with Clade's 95%-target pace view,
  credential-safe rate-limit reads through the authenticated Codex app-server,
  idempotent setup for Codex's native five-hour and weekly status-line fields,
  and minimal, optional-icon and detailed styles across ten themes plus JSON
  output

### Changed

- `opus` and `sonnet` aliases resolve to Opus 5 and Sonnet 5; superseded ids
  stay accepted so existing task rows and evidence bundles keep resolving.
  `configs/models.env` is now sourced by `loop-runner.sh` instead of being
  shadowed by a hardcoded `claude-sonnet-4-6`
- Orchestrator worktrees moved out of `.claude/worktrees/`, which Claude Code
  claims as its own managed pool and deletes along with a session
- `task_queue.py` and `worker.py` both sat on the 1500-line ceiling. The DDL
  moved to `task_schema.py` and worker scheduling to `worker_pool.py`, which
  `worker.py` subclasses to bind its own `Worker`. No behaviour change
- Automated commits carry the operator's own identity, and Claude co-author
  attribution is off
- The README moved its reference material into `docs/` and now stays inside its
  own 300-line rule
- Generated MCP skill catalogs match the manifest, and the Codex plugin cache
  version refreshes whenever generated plugin content changes
- One version now spans every surface. The Codex plugin manifest is canonical,
  `.claude-plugin/plugin.json` is generated from it, and `clade-mcp` reports
  0.3.1 from `pyproject.toml`, `server.json` and `__version__` alike — the
  package had been pinned at 0.2.0 for 241 commits while both plugin manifests
  advertised 0.3.1

### Fixed

- The Claude Code plugin advertised 37 agents and 14 hooks and loaded none of
  them: `agents` as an array of file paths is schema-valid and resolves
  nothing, and `plugin validate --strict` exits 0 on it
- The memory watchdog matched none of the commands the orchestrator builds —
  its pattern required a token between `claude` and `-p` — so it freed nothing
  under memory pressure. It also signalled the `sh -c` wrapper rather than the
  agent, and ordered by pid rather than age
- The worker activity heuristic read a transcript path Claude Code has never
  written, and its test built that same wrong layout, so it stayed green while
  always returning "unknown"
- A GitHub issue-create timeout forked one task into a growing pair of
  duplicates; `task_id` was stamped into every issue body and never read back
- `/brief` probed `localhost:4000`; the orchestrator binds 8765
- Two consumers parsed `.claude/loop-state` as KEY=VALUE while `loop-runner.sh`
  writes JSON to `.claude/loop-state.json`, so the session-start loop banner
  was silently empty. `converged` is now persisted rather than left a shell local
- Every session start injected model guidance naming a superseded generation
- Reinstalling now mirrors each repo-managed skill subtree exactly, removing
  stale or accidentally nested content while preserving unrelated user-owned
  skill directories
- Loop completion is now coordinator-owned and fail-closed: exact task-to-goal
  evidence is reconciled only after worker, syntax, test, and final verification
  gates pass; worker-created commits count even when the leftover sweep is empty,
  and serial/parallel worker failures propagate as non-zero exits
- Loop supervisor CLI failures now preserve the raw provider response and stop
  once with a distinct resumable `supervisor_failed` outcome instead of being
  retried as empty plans and mislabeled `max_iterations`; the runner exits
  non-zero for this and other terminal execution failures
- Loop planning now keeps raw supervisor output, extracts nested JSON safely,
  bounds planner tools, initializes custom log directories before checkpoint
  work, verifies only current-iteration changes, shares one task JSON parser,
  and dispatches recovery tasks in the worker format
- A `/loop` run that gave up reported success. Convergence is checked before the
  ceilings now, and the runner exits 2 when goal items remain
- Routing settings reject `NaN` and infinite thresholds instead of persisting
  values that cannot round-trip through JSON
- `delivery abandon` now discovers PRs by branch instead of trusting a
  possibly stale `published` flag — an unrecorded open PR blocks abandonment,
  and a merged PR at the recorded head is reconciled rather than mislabeled
  abandoned
- Task updates revalidate the effective persisted connection against the
  effective runtime before mutation, instead of only failing at execution time
- The correction-history append was not atomic: concurrent writers spliced
  records into each other and truncated every reader
- The PreCompact prompt hook dumped its entire prompt into the UI for want of a
  `statusMessage`, and auto-audit promoted raw prompt excerpts into the global
  `CLAUDE.md`
- Three verification paths silently measured nothing off Linux, and the
  PID-reuse safety net never existed on macOS at all
- pytest output is read through one colour-proof contract
  (`orchestrator/pytest_report.py`); the resolve eval and the regression
  detector had both been structurally blind to coloured output
- The settings reference promised every supported key and shipped 33 of 75, one
  of which was no longer a setting
- The CI checklist gate passed a documented command that exits 126, and a
  syntax-check gate imported `aiosqlite` in a job that installs no dependencies
- 135 dead cross-references left by the flow-skill absorption, 18 links to
  upstream files the sync never fetched, and skill descriptions truncated at
  the 1024-character limit on absorption
- The oracle was handed a review rule that could not apply to 86% of test
  traffic
- Users were instructed to run a flow-skill sync script that never existed

### Compatibility

- The control plane is default-closed from this release. A deployment that
  relied on an unauthenticated socket must either send the bearer token minted
  into `~/.claude/orchestrator-settings.json` on first start, or set
  `api_allow_unauthenticated` deliberately
- `usage_ingest_token` no longer means "open" when empty. A node posting usage
  to a hub needs the token configured on both ends
- Superseded model ids are still accepted, so existing task rows and evidence
  bundles keep resolving
- `worker_sandbox` (Landlock) ships default off; `worker_checkpoint_shadow` ships ON;
  `worker_git_surface_guard` and `worker_require_worktree` are on
- `/web` answers 503 until the UI is built. `web/dist` is the only servable
  root and is gitignored, so a fresh checkout has no UI: `orchestrator/start.sh`
  builds it on first run, or build it by hand with `cd orchestrator/web && npm
  ci && npm run build`. The previous fallback mounted the Vite *source* tree,
  whose `index.html` loads `/src/main.tsx` — a page no browser can execute
- The `reaction_configs` and `patrol_auto_ideas` settings are removed. Both were
  published in the settings reference and read by nothing; wiring
  `reaction_configs` as published would have been worse than deleting it, since
  `config.py`'s copy carried three of the five rules in
  `reactions.DEFAULT_CONFIGS` and `ReactionExecutor` replaces rather than
  merges, so copying the generated reference file would silently drop two
  reaction rules. `reactions_enabled` and `min_workers` are now real instead
- The FastAPI multi-worker orchestrator remains Claude-specific

### Upgrade

```bash
pip install --upgrade clade-mcp
./install.sh          # refreshes skills, hooks, scripts — and the deny rules
```

For native Codex use:

```bash
codex plugin marketplace add shenxingy/Clade
codex plugin add clade@clade
```

## [0.2.0] — 2026-07-13

### Added

- Native Codex plugin with 20 generated core workflows
- Codex `SessionStart` context hook and destructive-command `PreToolUse` guard
- Provider-neutral MCP runtime adapter selected with
  `CLADE_RUNTIME=claude|codex|auto`
- Configurable Codex sandbox and an explicit permission-bypass escape hatch
- Deterministic Codex skill generator plus CI drift protection
- English and Chinese documentation for Codex and `clade-mcp` 0.2.0

### Changed

- `clade-mcp` now bundles 32 workflows, up from 29 in 0.1.0
- MCP server and package metadata now report version 0.2.0 consistently
- `clade_list_skills` reports the selected execution runtime
- Root documentation presents Claude Code, Codex plugin, and MCP as separate
  product surfaces

### Compatibility

- Existing MCP installations remain on the Claude runtime by default
- Native Codex users should install the plugin instead of mounting `clade-mcp`
  inside Codex
- The FastAPI multi-worker orchestrator remains Claude-specific in this release

### Upgrade

```bash
pip install --upgrade clade-mcp
```

For native Codex use:

```bash
codex plugin marketplace add shenxingy/Clade
codex plugin add clade@clade
```

## [0.1.0] — 2026-04-02

### Added

- First public Clade release
- Initial `clade-mcp` package with 29 coding workflows and Claude execution
- Claude Code skills, hooks, agents, scripts, and the FastAPI orchestrator

<!-- 0.3.1 shipped untagged: the release commit says tagging and publishing
     stay an operator decision, so this compare link names that commit
     rather than a v0.3.1 tag that does not exist. -->
[0.3.1]: https://github.com/shenxingy/Clade/compare/v0.2.0...32961e4
[0.2.0]: https://github.com/shenxingy/Clade/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/shenxingy/Clade/releases/tag/v0.1.0
