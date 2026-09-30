# Artifact review — 2026-09-30

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
