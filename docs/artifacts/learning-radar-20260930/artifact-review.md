# Artifact review — 2026-09-30

The initial review below is retained as history. The follow-up review at the end
records the current revisions of both pages.

- Artifact: `index.html`, SHA256 `c4e0a3984140f5ce28219e650ac995588a84e7aff3bc7d8436af340f81c56238`.
- Reader: Chinese-speaking Clade maintainer familiar with coding agents.
- Question: What recent work is worth learning from, and what comes first?
- Type/container: decision / local HTML, using the repository's existing gray-green palette and local fonts.
- Expected answers: start with controlled delegation comparisons; sources are verified but Clade gains remain unmeasured; next action is to write a reproducible terminal-task evaluation plan, not to adopt a product or change runtime policy.

## Static and browser evidence

Commands from the worktree root:

```sh
python3 configs/scripts/artifact-lint.py docs/artifacts/learning-radar-20260930/index.html --strict
python3 configs/scripts/design-lint.py html docs/artifacts/learning-radar-20260930/index.html
git diff --check
```

Artifact lint: 0 FAIL, 0 WARN, 2 INFO (qualitative deck; 7/10 claim headings).
Design lint: 4 PASS. Its inherited-color resolver conflates some media selectors;
actual browser-computed token pairs were also measured independently: minimum
5.9767:1 in light, 7.8111:1 in dark, over all four text colors on both surfaces.

Local execution evidence is preserved in the operator's Clade state directory,
under `research-learning-20260930/`: `render.py`, `render.json`, and captures
named `{light,dark}-{1280,390}-{first,full,table,sources,zoom200,zoom200-first}.png`.
Additional `*-390-table-right.png` captures show the evidence grades after scroll.
Run the saved script with `OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 uv run --offline --with playwright python <evidence-dir>/render.py`.
Raw screenshots are local evidence, not bundled into this Git checkpoint.

| Viewport | Themes | Checks and inspection |
|---|---|---|
| 1280×900 | light, dark | First/full page and table captured and inspected; changed source section recaptured; legible headings and body. |
| 390×844 | light, dark | First/full page and table captured and inspected; explicit horizontal-scroll instruction and rightmost evidence column reviewed. |
| Both sizes | light, dark | 200% text enlargement: first/full captures, no document overflow; enlarged first screens inspected. |

Reading: each size was run in both actual browser color schemes; `matchMedia`
and computed background verified theme activation. There are no figures or
theme controls. JavaScript-off text is identical; local links and anchors exist;
keyboard Tab/Enter navigates to the first recommendation; the table scrolls.
No page errors or failed requests. No hosted wrapper is in scope.

## Fresh-reader review and repair

Independent model reviewer received only the page, screenshots, audience and
reader question, with no expected answers. It correctly identified the learning
order, unmeasured Clade effects and proposed next action. Initial verdict was
NEEDS_REVISION: the mobile table hid grades without a visible scroll instruction,
and four recommendations versus six evidence rows needed explanation.

Repair: added a visible mobile scroll instruction and explained that four rows
cover external learning directions and two cover existing repository foundations.
Re-rendered the full matrix and inspected the affected area in both themes.
Reviewer re-review: **“PASS (bounded re-review of the updated mobile evidence area)”**.
Its remaining observation was nonblocking: horizontal scrolling separates the
leftmost claim from the rightmost grade. Body text independently states the limits.
Earlier static repair removed a redundant print-only paint override that the
static resolver combined with dark styles; browser paint remained legible.

This is a model comprehension proxy, not a human usability study. The reviewer
did not verify external sources; the lead read primary sources separately.

## Execution and delivery boundary

Resource probe: affinity 32 CPUs; load average 3.92 / 3.72 / 3.72; available RAM
66 GiB; GPU 0% utilization and 18,822 MiB free. Other users' workloads were
observed and preserved. Four bounded browser contexts shared one browser;
native-library thread caps were 1. Final capture/check batch took 3.21 seconds
(about 1.25 viewport/theme lanes per second). No GPU inference was applicable.

Verdict: **PASS for this local research artifact**. No benchmark reproduction,
paid inference, vendor product trial, deployment or runtime modification was
performed. Full application CI is not claimed; this is a documentation-only
checkpoint with artifact verification and the repository's pre-commit drift gates.

## Follow-up: NanoHarness learning and verifier calibration

Current artifact revisions:

- `index.html`: SHA256 `c324254d5f1c2a0eb64912645038d33cdc0062ccd11302ce7f7268f646b05212`.
- `nanoharness.html`: SHA256 `5c5d5fde331a439af9a566cd9783e84bd1344cfb4f6ab2269a811dcbcff80bae`.

The new page is a finding report for the same reader. Its question is: what did
we learn from NanoHarness, what has Clade actually verified, and what comes next?
The intended answer is to calibrate the final verifier before comparing delegation;
two historical local-fix verifiers are now calibrated, while model effects remain
unmeasured. The original page links this work and updates its next-action status.

### Reproducible local evidence

```sh
python3 docs/artifacts/learning-radar-20260930/preflight.py --output /tmp/clade-nanoharness-preflight
python3 -m py_compile docs/artifacts/learning-radar-20260930/preflight.py
```

The actual output directory was the operator's Clade state directory under
`research-learning-20260930/deep-dive/`. All four full logs were inspected;
`preflight-result.json` preserves commit/test/log hashes, exit codes, exact
failures, skip checks, timings and the resource probe. Fixed tests were held
constant, and only the implementation file changed between red and green:

- Corrupt statistics recovery: old implementation 43/46 passes with exactly
  three expected failures; fixed implementation 46/46, exit 0.
- Prompt noise filtering: old implementation 137/138 passes with exactly one
  expected failure; fixed implementation 138/138, exit 0.

All four suites had no skips. An independent read-only reviewer checked the
runner, result JSON and four full logs and accepted only the verifier-readiness
claim. This is not a full current-repository test run or a model A/B experiment.
Agent trial count is zero. Compilation of the Python helper passed.

### Current rendered review

Both pages passed strict artifact lint: 0 FAIL, 0 WARN, 2 INFO each. The original
has 8/10 claim headings; the new page has 5/8. Design lint passed four checks for
each page. Browser-computed contrast again measured at least 5.9767:1 in light
and 7.8111:1 in dark, across four text colors and two surfaces.

The existing `render.py` now accepts `CLADE_REVIEW_PAGE` and
`CLADE_REVIEW_OUTPUT`. The original page's current captures and `render.json`
replace the earlier batch under `research-learning-20260930/`; the new page's
are under `deep-dive/render/`. Each JSON records its exact artifact hash.
Both pages were captured at 1280×900 and 390×844 in light and dark, including
first/full/table/source views, 200% text enlargement, and scrolled mobile tables.
The lead inspected the new page's first/full matrix, table detail and enlarged
mobile views, plus the original page's changed first-screen/next-action regions.
The independent readers inspected the supplied full matrices as well.

There was no document overflow at either text size, page error or failed request.
Actual color-scheme activation, JavaScript-off text equality, keyboard navigation,
local links/anchors and mobile table scrolling passed. The render helper was
corrected to strip URL fragments before checking local-file existence and rerun
successfully; the report link itself was valid. No figures or hosted wrapper
are in scope.

Fresh-reader review of the new page received the page, captures, audience and
question, without expected answers. It correctly distinguished local verifier
calibration, paper results, unmeasured agent performance and the proposed
controlled comparison. It read the red/green table correctly, including mobile
scrolling and 200% text, and returned **PASS** with no material issue.
The original reader separately returned **PASS (bounded re-review)** for the
updated original page: progress and next-action claims are consistent, and the
unperformed model experiment remains explicit. These are model comprehension
proxies; source verification was performed separately by the lead.

### Resources and scope

Before execution: CPU affinity 32; load 5.08 / 6.73 / 6.45; available RAM 64 GiB;
GPU utilization 0%, free VRAM 18,822 MiB. Other users' processes were preserved.
Four verifier workers with native-library threads capped at 1 finished four
suites in 16.669 seconds (about 0.24 suites/second). Rendering used four bounded
contexts per page; capture/check batches took 3.18 seconds for the original and
3.30 seconds for the new page. These workloads did not need GPU inference.

Verdict: **PASS for the local learning report and historical verifier calibration**.
Paper benchmark reproduction, model A/B, production traffic, external product
trials and full application CI remain unperformed and are not claimed. The two
historical tasks cover local shell-hook repairs only. No production policy,
model route or compression setting changed.

Final local checkpoint gates: `bash .claude/pre-commit.sh` passed all five
repository drift checks (exit 0), and `git diff --check` passed. These gates do
not substitute for the full CI required before any later publication.
