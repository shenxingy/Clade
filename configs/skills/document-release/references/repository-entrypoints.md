# Repository entry-point standard

Use this standard for every new repository, substantial README/setup change,
and documentation release review. A repository is a product entry point: a
person finds it, decides whether it fits, looks for proof, and tries one task.
The README and repository organization must support that whole journey.

## 1. Study the right references

Choose a small relevant set for the product's own category. Inspect the actual
rendered README and the path from its opening to a demo, installation and help.
Study imagery, hierarchy, navigation and disclosure as well as wording. A
desktop application, coding workflow and document-processing library need
different evidence; do not give unrelated projects the same decorative layout.

For each borrowed pattern record its source URL, observation date, the reader
question it answers and why it fits. Include a counterexample or rejected
pattern. Stars help select references; they do not demonstrate causation,
usability or conversion. Do not copy another project's artwork or claims.

Use a research sample sized to the decision, not a fixed project quota. Separate
direct alternatives from adjacent tools and engines when their audiences differ.
Record observed patterns separately from proposed changes and measured outcomes.

## 2. Answer the first visitor's questions

| Reader question | Required answer |
| --- | --- |
| What is this, and is it for me? | A concrete outcome and intended audience in the opening. |
| What does it look like or produce? | Credible visual or executable product evidence, near the opening. |
| Can I use it now? | Current maturity, supported platforms, prerequisites and significant limits. |
| What should I do next? | One primary route to a first useful task; alternate routes clearly labeled. |
| How do I know it worked? | Expected result, where the output appears and how to inspect it. |
| Where do I go if it fails? | Troubleshooting, support and security-reporting paths appropriate to the project. |
| Can I understand or contribute to it? | A compact map of real responsibilities, architecture/docs and contribution steps. |

Keep the opening readable without scrolling through a catalog, internal
history or a long badge row. Preserve selectable text for the core promise,
commands and links; an image must not be the only way to learn essential facts.
Use descriptive headings, whitespace, short comparisons and progressive
disclosure. Move reference detail into reachable docs instead of creating a
wall of text. A line-count target is a guardrail, not the quality verdict.

## 3. Choose a medium that proves something

| Product | Useful evidence | What it must not imply |
| --- | --- | --- |
| Desktop/web application | Current UI screenshot, short task recording, or labeled fixture render. | A fixture render does not prove live permissions, data persistence or device behavior. |
| CLI or coding workflow | Recorded terminal output or a short task sequence, with copyable commands nearby. | An illustrative transcript is not an executed agent run or a measured speedup. |
| Data/document tool | Input and actual output side by side, with a reproducible synthetic sample. | One example does not establish accuracy, completeness, privacy or compliance. |
| Library/infrastructure | A legible architecture/data-flow diagram plus the smallest runnable input/output example. | The diagram must not present planned components as implemented. |

Logos, mascots, badge rows and star-history charts are not product proof.
Do not add images merely to satisfy a quota. Use the simplest medium that
answers the reader's question. Explain an exceptional text-only decision with
its task evidence; do not silently omit visual consideration.

Prefer a static image plus a click-to-play recording when animation adds
explanation. Keep an equivalent static/text path. Avoid endlessly autoplaying
ornament, unreadably small terminal text, giant blank screenshots and a hero
that hides the next action.

## 4. Keep assets truthful and maintainable

- Use current product code and fictional/sanitized examples. Do not publish
  credentials, private paths, customer records or personal application state.
- Label real capture, fixture render and illustrative diagram accurately.
  Never fabricate UI, execution results, review approvals, testimonials,
  benchmark numbers or status badges. Do not infer privacy from a screenshot.
- Record the source revision, reproduction command and relevant environment
  with the media, using public-safe provenance. Keep raw/private evidence out
  of the outgoing repository. Preserve applicable licenses and attribution.
- Store stable project-owned assets in a documented location. Check their
  load size, dimensions, meaningful alt text, contrast, dark-mode behavior and
  mobile legibility. Avoid remote image dependencies when ownership permits
  a small local asset. Do not ship broken placeholder media links.
- Keep versions, badges, screenshots, commands and stated platform support in
  agreement. Refresh or remove evidence when the demonstrated behavior changes.
- If development and distribution use different trees, inspect both revisions.
  Each README and image must describe its own obtainable version. A docs-only
  integration does not ship internal features, validate a binary or open a
  private repository; retain separate delivery and runtime evidence.

## 5. Make the repository navigable

Inventory each customer entry point: root and localized READMEs, separately
published packages, examples and setup guides. Explain which route a new user
should take. Keep equivalent variants accurate; do not force identical prose
where a package serves a different audience.

Describe the responsibilities of the few directories a user or contributor
needs, using real paths. Link the deeper architecture and development material.
A directory tree without responsibilities is not an architecture explanation.
Make release/license information, contribution rules, support and private
security reporting discoverable where applicable. Do not invent a community
channel, release, maintainer response time or support promise.

For open-source onboarding, follow the community routes as the intended reader.
Check repository visibility, enabled channels, category/form destinations and
whether contributions are accepted. Authenticated maintainer access does not
prove public access. Distinguish questions, feature ideas, reproducible failures,
private security reports and code contributions using existing channels where
they serve the need. Explain review, sign-off and how a contribution lands.

Give non-code contributors a small useful action too. If starter issues are
advertised, inspect the actual issues: an empty label is not a task queue. A
starter brief needs a bounded problem, relevant files or reproduction steps,
an observable acceptance check and a reviewer or triage destination. Prepare
missing briefs locally within scope; posting, channel creation, visibility
changes and operating commitments require the corresponding authority.

Keep proposed community operations separate from observed activity. Do not
equate enabled Discussions, labels or stars with a healthy community. When
measurement is requested, use observed first-use success, unanswered questions
or contribution outcomes with dates and denominators; do not invent growth or
add telemetry merely to improve a README.

## 6. Verify the journey, then report its limits

1. Check commands, supported options, links, anchors, assets, licenses and
   feature claims against the current source and distribution.
2. Exercise the smallest first-use path in an isolated environment with
   synthetic input. Check the resulting artifact, not just an exit code. Name
   dependencies, network/model downloads and lanes that could not run.
3. Inspect actual rendered README output at desktop and phone widths, in light
   and dark, including image loading and enlarged text. Use the target forge
   when accessible; a local approximation leaves forge-specific behavior
   unverified. GitHub strips unsupported HTML/CSS/scripts: do not depend on them.
4. Follow the primary action, setup, output and help links. Fix broken paths,
   unclear next steps, unreadable media, overflow and misleading hierarchy.
   Re-capture the affected views after fixes.
5. Have a fresh reader or independent reviewer answer the first-visitor
   questions without the original brief. Distinguish agent review from human
   usability testing. Record defects, repairs and remaining uncertainties.

Completion evidence identifies the exact revision and entry points inspected,
the rendered views, commands/results and remaining limits. Source correctness,
rendered quality and human outcomes are different claims. Do not report user
testing, accessibility coverage or increased conversion without measuring them.
