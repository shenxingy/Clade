# Review the delivered artifact, as a reader

Read this before drafting and apply it after rendering. A lint pass checks
structure; a screenshot file proves capture. Neither proves comprehension or
legibility. The author owns the fix → render → inspect loop before handoff.

## 1. Set the reader test before writing

Record the intended audience, assumed knowledge, one reader question, chosen
type/container, and the action or understanding the page should enable. Use
the routing table in `spines.md`. Pick a primary question for a mixed topic;
put supporting detail behind links or in an appendix, with sources intact.

Set three acceptance answers from the evidence, without inventing facts:

- What is this about, and why does it matter to this reader?
- What is the current state or conclusion, as of when, and what remains unknown?
- What happens next, or what can the reader now decide/do?

Use only the selected type's applicable checks. Reference/worklog pages do not
need argued-page why/method sections; mark these N/A by type in the review.
For a reference page, substitute what can be looked up and where; for a
worklog, include the blocker and human action, including an explicit “none”.
“Thirty seconds” is a design target for the first screen, not a measured
reading time unless a reader was actually timed. A newcomer should not need
the originating chat, internal nicknames, source code or an author's narration
to understand the answer.

## 2. Edit for meaning before layout

Check every headline, summary, caption and action against the facts table:

- Give the subject a plain-language name and purpose on first mention; explain
  an acronym where it first matters, even if a glossary also exists.
- Name the actor, action and consequence. Replace “alignment is complete”
  with what was aligned and how that changes the reader's situation.
- Explain comparison direction and baseline: “better” at which task, against
  what, over which population and period? Do not turn an association into a cause.
- Distinguish unknown, measured zero, not applicable, planned and completed.
  Status wording, verdict chips, prose and figures must agree.
- Keep one main point per paragraph; put supporting evidence beside the claim.
  Split a sentence when understanding it requires holding several conditions.
  Keep needed technical detail reachable rather than deleting it for brevity.
- Read the headline, deck and captions alone. They must tell the same story
  as the body, in natural language, without unsupported certainty.

Example (illustrative, not project data): “The ingestion path is converged”
becomes “New files now reach the index. Older files have not been reprocessed,
so search still misses them. Next, the ingestion owner will run the backfill.”
Add the actual date, evidence and owner before using this on a real page.

## 3. Capture a complete rendering matrix

Use the actual output container: browser for HTML, rendered slides/PDF pages
for those formats. For a published artifact, repeat the essential checks at
the served URL in its real wrapper, with the user's access path. A local file
cannot prove that a publisher preserved CSS, SVG, images or relative links.

For HTML, minimum matrix: **light and dark × desktop and narrow phone**, e.g.
1280×900 and 390×844 CSS pixels. Capture the first viewport separately from
the full page. Confirm the browser's `prefers-color-scheme` value (or the
page's explicit theme control) actually changed; a filename is not evidence
of a theme. Exercise explicit theme toggles against the opposite OS setting
if provided. A deliberately single-theme page must remain readable under
both OS settings; record the design choice, not a pretend dark-mode pass.

Wait for fonts and images, reveal lazy content by scrolling, and record failed
requests and page errors. Then inspect **every figure at its displayed size**:
use per-figure crops or section screenshots if a full-page image is downscaled.
Inspect raster pictures, external SVGs and canvas output as well as inline SVG.
A thumbnail of a long page cannot establish that its smallest label is readable.

For HTML these are required where applicable: essential text with JavaScript
off, 200% text/zoom, keyboard links
and any controls the page actually uses. Test only relevant states, but name
unavailable lanes as UNVERIFIED; absence of controls is N/A with a reason. Reflow a complex figure for a phone, split it, or provide
a legible summary and clearly reachable detailed view; do not simply shrink
a desktop drawing until its labels disappear.

## 4. Review the pictures, not the markup

For each figure, record its intended takeaway and whether the rendered marks
actually communicate it. Check:

| Check | Reject when |
|---|---|
| Visibility | Blank/solid image, missing asset, missing glyphs, foreground merging into background, or an opaque layer hiding the data |
| Alignment | Labels clipped or colliding, connectors entering the wrong box, inconsistent shared baselines, or a legend detached from what it explains |
| Colour | Entity colours change meaning, colour is the only encoding, or text/essential marks fail contrast against their actual backdrop |
| Data meaning | Wrong axes/units/denominators, misleading scale, caption contradicting marks, or a diagram mixing planned and live components |
| Density | Reader cannot trace the main flow or compare the important quantities at the delivered size |

Use the contrast floors in `figures.md`. Record measured pairs and ratios
where measurable; gradients, transparency, raster images and overlays require
inspection of the real composite, not just CSS hex values. Pixel heuristics
are diagnostics, not an accessibility verdict. A dark background by itself is
not a failure: disappearing content is. Do not “fix” a black figure by blindly
brightening the whole image.

For a black/blank image, inspect the actual asset and browser computed paint:
CSS-variable scope/fallbacks, inherited `color`, SVG `fill`/`stroke`, alpha,
stacking/overlays, load failures, canvas initialization and exporter background.
External SVG/raster assets do not inherit the page's tokens. Establish the
cause before patching; then recapture the affected figure in both themes and
widths and check the whole page for collateral changes. If the original image
is unavailable, label the cause unknown; a synthetic reproduction is not its RCA.

## 5. Perform a fresh-reader review

After the author's checks, use one independent reviewer when delegation is
available. Supply only the rendered artifact/URL, its visible text, intended
audience and the reader's question — no chat history, expected answers or
author explanation. This is an artifact-specific review, not a repository
security review. Without delegation, do a separate cold-reading pass and label
it self-review; do not claim an independent or human test.

Ask the reviewer to:

1. Explain in their own words the subject, current state, main uncertainty and
   next action (or lookup path for a reference page), citing visible locations.
2. Explain each main figure from its marks, labels and caption; identify any
   term or comparison whose meaning required guessing.
3. Identify contradictions, unreadable areas and missing context; state the
   consequence for the reader rather than only calling the design “busy”.

Only then compare that account with the acceptance answers and facts table.
A wrong takeaway is a content/layout defect even when all lint checks pass.
Revise and repeat the affected reader questions and rendering checks. Do not
resolve a failure by sending the reviewer the answer: put the missing meaning
on the page. Model review is a comprehension proxy, not evidence of usability
for actual people; reserve that claim for observed representative readers.

## 6. Save the verdict and close the loop

Keep a compact `artifact-review.md` beside the task's evidence (not in the
reader's main flow). Record:

```text
Artifact: exact file/URL, revision or SHA256, review time
Reader / question / type / container:
Expected first-screen answers:
Static: commands, FAIL/WARN, retained warnings and reasons
Rendered: viewport × theme × state -> screenshot paths, observed result
Figures: each figure -> intended takeaway, observed defect or pass
Contrast: measured worst pair/ratio per theme, or unmeasured + reason
Reader review: independent model / self / human; verbatim account, mismatches
Repairs: defect -> change -> fresh evidence, with unresolved items separate
Delivery: served URL/wrapper checked, or local-only scope
Verdict: PASS / NEEDS_REVISION / UNVERIFIED, with remaining limitations
```

**NEEDS_REVISION** blocks ready/publish claims for wrong takeaways, important
unexplained terms, invisible content, misleading charts, clipped labels or
broken essential controls/assets. Fix before publishing; visual failure is
not a lint warning that can be waived with a footnote. **UNVERIFIED** means a
required render/review lane could not run: preserve the draft and name the
missing evidence, never present it as passed. Optional polish can remain with
a reason. PASS requires all applicable checks, not a high average score.

Any content/style/asset edit invalidates the affected screenshots and review;
capture again after the final change. After authorized publication, a failure
at the served URL reopens the loop. Report the URL/file, verdict, important
repairs and actual remaining limits; do not bury the reader in QA logs.
