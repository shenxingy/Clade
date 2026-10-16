# Artifact review — latest learning, 2026-09-30

Pre-draft reader contract:
- Audience: a technically literate Clade maintainer asking to learn current developments across authors and products.
- Question: What did this broader current-news learning loop teach, what was actually tested, and what remains worth trying?
- Type/container: finding / standalone local HTML, reusing the repository's gray-green report tokens.
- Expected first-screen answers: 24 selected current-source topics across AI and engineering, with explicit older/undated exceptions; primary-source reading is complete for the selected set, browser behavior has a bounded local experiment, model performance remains unmeasured; reader can reuse the methods and choose a dataset-backed experiment.
- Scope of stopping: this selected batch closes; neither the Internet nor all fields of knowledge are exhausted.

Initial status before drafting: UNVERIFIED; render and fresh-reader evidence were pending.

## Final artifact and static checks

- File: `index.html`, SHA256 `3367b0de0fdcc5489981b40c277df6b9cb9f6f7e20dab62fe7c96edc80432c11`.
- Review date: 2026-09-30. Container: local file, no hosted publication requested.
- `python3 configs/scripts/artifact-lint.py --strict docs/artifacts/latest-learning-20260930/index.html`: PASS, 0 FAIL, 0 WARN; 2,040 lint word units. INFO retained: heuristic abstract detection, section-headline ratio, and no figure. Actual deck includes the 24-topic scope; a two-row numeric table answers the comparison without a chart. All seven percentages have denominators. Long-page pinned navigation threshold does not apply.
- `python3 configs/scripts/design-lint.py html docs/artifacts/latest-learning-20260930/index.html`: 4 PASS. Its CSS parser notes one unsupported selector; computed browser checks cover the real media-query themes.
- `bash .claude/pre-commit.sh`: exit 0, all five generated-surface drift checks; silent on success by design.
- Source IDs unique (24), Python source parses, browser script SHA matches saved result, eight browser checks true, synthetic metrics recomputed from all outcomes.
- Full repository CI and hosted checks: not run; local research checkpoint only, no publication. Model/API/audio/production trials: not performed, explicitly labeled.

## Rendered evidence

Evidence directory: `~/.clade/research-learning-20260930/latest/`.
The committed `render-summary.json` ties computed paint, errors and resource settings to the exact page hash. Full text captures remain in that directory's `render.json`.

- Light and dark × 1280×900 and 390×844: `{theme}-{width}-first.png`, `-full.png`, `-table.png`, `-sources.png`, `-zoom200.png`, `-zoom200-first.png`; mobile also `-table-right.png`.
- Actual `prefers-color-scheme` changed; no horizontal document overflow or browser/request errors. No missing glyphs or disappeared source entries observed. Table scroll stays inside its labeled region.
- Essential text identical with JavaScript disabled. All local links exist and same-page anchors resolve. Keyboard Tab reaches the first navigation link; Enter activates it. Table region is focusable and scrollable.
- 200% text: no document overflow; title wraps on the phone but stays legible. No interactive theme control or application controls: N/A, static report follows OS theme.
- Table takeaway: average 6/12 for both groups conceals all-three success of 2/4 vs 0/4; observed labels, denominators and values agree. Mobile caption now states that comparison without requiring horizontal movement. No charts or images: figure-specific checks N/A.
- Minimum computed contrast: light muted/background 5.9767:1; dark muted/surface 7.8111:1. All text token/background combinations exceed 4.5:1.
- Final render: 4 bounded workers, native thread limits 1, 4.32 seconds (about 0.93 viewport/theme states per second, including all captures and interaction checks). GPU not used. Pre-batch CPU affinity 32, load 5.63/6.06/6.02, available RAM 68,918,384 KiB; GPU 0%, 18,822 MiB free. Other workloads observed and preserved. No batch-size increase was needed for four independent states.
- Author inspected first screens in both widths/themes, whole-page layout, displayed-size table left/right and source crops, and 200% text captures. Independent reviewer also inspected the matrix. Full-page thumbnails were not used to certify small-label readability.

## Independent fresh-reader review and repairs

Reviewer: `/root/latest_artifact_reader`, independent model with no chat history, given artifact/screenshots, reader audience and question only. This is a comprehension proxy, not a human usability study.

Initial verdict: NEEDS_REVISION. Verbatim account excerpts:

> The page’s subject and current state are understandable: this was a 2026-09-15–30 scan of 24 AI/tooling/infrastructure topics, yielding reusable evaluation methods and one locally tested browser slice.
>
> What was actually tested is appropriately narrow and traceable: Chrome 154 on Linux, two local HTTP services, 8/8 assertions, 0.808 seconds, with linked `browser-result.json` and `browser_probe.py`.
>
> The stability table is interpretable. Each row contains four task outcomes, each represented by a three-run bit string: A = `111`, `111`, `000`, `000`; B = `110`, `101`, `010`, `001`.
>
> The page says it “保留日期和证据等级” (line 29), but no evidence-grade field or legend appears anywhere.
>
> Required revisions are small but material: add a visible evidence-grade legend/labels tied to claims; qualify the opening “一手材料” status with the later reading-depth distinction; and either narrow the headline or explicitly label the interface conclusion as source-derived except for the Chrome experiment.

Repairs applied to the page, then entire matrix recaptured:
- Explicit opening distinguishes 22 related-text/document readings from two abstract-only screenings.
- Evidence legend defines source-checked, recommendation/inference, synthetic arithmetic and local observation; relevant sections name their level.
- Headline narrows the execution claim to the locally tested browser slice.
- Mobile comparison caption repeats the two all-run fractions and common denominator.
- Earlier browser probe review also caught insufficient per-mode redirect evidence: target paths are now mode-specific and the enforced target must have zero hits. Final probe rerun passed 8/8 in 0.808 seconds; review accepted its bounded claims. It does not prove report delivery or general security conformance.

Final independent verdict: PASS at 2026-09-30 19:26 UTC. Verbatim revised-reader account excerpts:

> 复审结论：**PASS（有一处措辞级建议）**。
>
> 证据术语现在足够清楚。`index.html:31` 定义了“原文核对、方法建议、算术示例、本地观察”，并明确六项方法是“原文核对 + 方法建议”，不代表 Clade 已取得成效；新方向和本地实验也分别标注证据等级。
>
> 合成表及其解释也已闭合：四个任务、每任务三次运行、总计 12 次由 `index.html:34-37` 给出；`Pass^3` 和 `Pass@3` 通过列名与正文解释可理解。
>
> 浅色/深色及 200% 首屏截图均保持可读，无明显主题或缩放破坏。
>
> 唯一建议是把标题“平均成功率不能代表稳定性”改成“平均成功率不能单独代表稳定性”（`index.html:22`），避免读者按字面理解为平均成功率完全无用；正文实际表达的是“平均值单独不足以区分稳定性”（`index.html:38`）。这不阻塞通过。

Optional wording retained: the headline rejects treating mean success as a proxy for stability; the adjacent table and caption explicitly preserve the usefulness and denominator of the mean. No inaccurate completion or model-performance takeaway remained in the independent account.

**Final verdict: PASS for the local HTML artifact and its stated experiment scope.** No hosted wrapper was requested or tested. No claim of human usability, general browser conformance, model-performance gain or exhaustive learning follows.
