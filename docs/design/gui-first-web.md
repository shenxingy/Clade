# GUI-first local workspace

## Design Decisions

- **Scope lane:** Standard: connect the existing project/task workflow. This is
  one entry flow, not a replacement execution engine or a marketing site.
- **Platform:** local browser app, mouse, keyboard and touch. Keep React/Vite,
  FastAPI and local agent execution. A desktop shell adds packaging/update work;
  a hosted executor would need repository and credential access. Neither is
  necessary to make the current GUI usable.
- **Design system:** evolve the existing dark palette in `web/src/index.css`.
  System sans for instructions; existing mono stack for IDs, logs and evidence.
  Shared controls use 44px minimum height, 8/12/16px padding, 6px radius and a
  visible focus ring; modal radius 8px. One primary action per screen.
- **Design direction:** read this as a local workbench for people who prefer a
  GUI, optimizing project selection, task submission and outcome review.
  `clade.design-direction/v1`: V1, evolve, product-quiet, project-design-system,
  composition 2 / motion 1 / density 3, dark, no signature animation.
- **Style DNA / three directions:** N/A; preserve the shipped palette and
  structure. Brand-site differentiation and signature motion are also N/A.
- **Benchmark:** Mrrlin's [execution workflow](https://mrrlin.com/ai-coding-agent-orchestrator)
  provides the task-to-evidence framing; Vibe Kanban's
  [task creation flow](https://www.vibekanban.com/docs/core-features/creating-tasks)
  distinguishes queueing from execution. These are documented patterns, not
  personally tested competitor deployments. [Primer buttons](https://primer.style/product/components/button/)
  guide action hierarchy; [ARIA dialogs](https://www.w3.org/WAI/ARIA/apg/patterns/dialog-modal/)
  guide focus containment, Escape and return focus. Counterexample: the old
  empty board had no project/task creation control and no visible recovery
  after its initial API request failed.
- **Native vs custom:** native form labels, selects, buttons and scrolling;
  installed Radix dialog for focus/keyboard behavior; Clade owns task grouping,
  execution state and evidence. Do not infer completion from a green card.
- **Core components / visual checkpoint:** shared `Modal`, `.ui-button`,
  `.ui-input`, native select and task rows in the real Vite app. Browser fixtures
  exercise their empty, populated, disabled, error, pending and focus states.
  No separate permanent component-lab route was added to this bounded flow.
- **Screens in scope:** connection recovery, empty workspace, project picker,
  task board, task composer and task details. Existing Agents, Evidence,
  Terminal and Settings remain available; their internal layouts are not a
  redesign deliverable of this change.
- **State and motion:** 150ms control color feedback only; reduced motion
  removes transitions. Retryable errors preserve form inputs. A disconnected
  live stream falls back to queue reads; switching projects clears old data
  and discards old socket callbacks. The selected project survives reload.
- **Behavior:** adding a task follows the existing `auto_start` policy. The
  composer displays automatic execution, push and merge settings before the
  submission. Manual run and retry remain explicit actions; HTTP-200 action
  refusals are errors. Reopening a resolved project path reuses its session
  only when the caller requests it; separate sessions remain supported by API.
- **Responsive:** 390px stacks the project selector, task rows and metadata;
  768/1280/1440 keep the same reading order with a bounded content width.
- **Verification:** `npm run build`, `npm run test:e2e`, focused backend tests,
  and repository CI gates. Browser tests use deterministic HTTP/WebSocket
  fixtures, not real agents. See the PR for exact final command results.
- **Review loop:** baseline had two P0 entry blockers (no project/task creation)
  and one P1 recovery gap. First implementation capture had zero observed
  P0/P1 on the scoped board/dialog; P2 unknown-state icons were corrected and
  recaptured. Check all four widths, keyboard focus/return, long copy, reduced
  motion and 200% text size. Runtime and user evidence below remains unclaimed.
- **Lint boundary:** source lint is run over the full existing frontend. Its
  warnings for old compact settings spacing, additional legacy type sizes,
  terminal colors/render loop and UsageBar/EvalDashboard transitions are
  outside this flow. No suppression or gate weakening is used. New workflow
  type sizes are 12/14/16/18/28/40px, with inherited status badges at 12px.
- **Measured contrast:** Chromium computed-color samples on the rendered
  welcome screen: muted text 7.86:1, heading 16.19:1, primary button 17.08:1.
  These sample pairs do not establish whole-app WCAG compliance. Human
  screen-reader and physical-device testing are unavailable.

## Running and verifying

From the repository root, run `./orchestrator/start.sh`, then open the printed
sign-in URL. In the browser: Open project → New task → Add to queue → open the
task → Run task (if automatic execution is off) → inspect results. The folder
is on the machine running Clade. Native CLI tools continue to work independently.

For frontend checks:

```bash
cd orchestrator/web
npm ci
npm run build
npx playwright install chromium
npm run test:e2e
```

An installed browser can be selected with `CLADE_BROWSER_PATH`; screenshots
can be retained outside the checkout with `CLADE_SCREENSHOTS`.

## Decision log — 2026-11-02

The owner requested a usable graphical alternative while retaining their TUI
workflow, and delegated the desktop-versus-web choice. Choose the existing
local web app. A native-session observer, public sharing, hosted execution and
an installer are separate product decisions, not prerequisites for this flow.
No Mrrlin dependency or upstream code was imported.

This work does not demonstrate real-provider delivery, browser compatibility
beyond Chromium, physical mobile behavior, representative-user success, or
public acquisition. Those observations require a separate trial; it would be
incorrect to infer them from screenshots or mocked browser tests.
