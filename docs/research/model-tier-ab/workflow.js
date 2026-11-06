export const meta = {
  name: 'model-tier-ab-implement',
  description: 'Paired A/B: replayed fix tasks x 3 arms (Opus 5.5 xhigh, Sonnet 5 medium, Opus 5.5 medium) x reps; graded afterwards in the shell',
  phases: [{ title: 'Implement', detail: 'one agent per prepared cell' }],
}
// Protocol: docs/research/2026-10-23-workflow-effort-and-reader-ab.md
// § "Queued: model tier for implement stages". Launch with args = the JSON
// object prep.sh writes to $AB/args.json, passed as a JSON value, not a string.
const { root, py, reps, tasks } = args
if (!Array.isArray(tasks) || !tasks.length) throw new Error('args.tasks is empty; pass $AB/args.json as a JSON value')
// Every arm names its model: a run that inherits the session's model is how the
// 2026-10-23 reader A/B came back on the wrong one.
const ARMS = [
  { id: 'A', model: 'opus', effort: 'xhigh' },
  { id: 'B', model: 'sonnet', effort: 'medium' },
  { id: 'C', model: 'opus', effort: 'medium' },
]
const SCHEMA = {
  type: 'object',
  properties: {
    changed: { type: 'array', items: { type: 'string' } },
    verifier_exit: { type: 'integer' },
  },
  required: ['changed', 'verifier_exit'],
}
// The arm order rotates with task and repetition, so no arm always queues first
// on a loaded host.
const cells = []
for (let r = 1; r <= reps; r++)
  tasks.forEach((t, i) => ARMS.forEach((_, k) => cells.push({ t, r, arm: ARMS[(i + r + k) % ARMS.length] })))
const label = (c) => `tier:${c.t.id}:${c.arm.id}:${c.r}`
const brief = (c) => {
  const cell = `${root}/${c.t.id}/${c.arm.id}-${c.r}`
  return [
    `Checkout: ${cell}. It is a git repository with one commit. Work only inside it and read nothing outside it.`,
    // Every Bash call starts in the lead's working directory, not the cell, and
    // leaks.py flags a command that does not begin with this cd.
    `Every shell command starts outside the checkout, so begin each one with: cd ${cell} &&`,
    'Give Read, Edit, Write, Grep and Glob absolute paths inside the checkout.',
    `Defect: ${c.t.statement}.`,
    `You own: ${c.t.owned.join(', ')}.`,
    // The same empty HOME the grader uses, inside the cell and excluded from git.
    `Verifier, failing now: cd ${cell} && export PY=${py} HOME=${cell}/.ab-home && ${c.t.verifier}`,
    'The verifier, the tests it runs and their fixtures are read-only.',
    'Fix the defect in the files you own so that the verifier passes.',
  ].join('\n')
}
// One stage, so pipeline() and parallel() behave alike here.
const out = await pipeline(cells, (c) =>
  agent(brief(c), { label: label(c), phase: 'Implement', schema: SCHEMA, model: c.arm.model, effort: c.arm.effort }))
const failed = cells.filter((_, i) => !out[i]).map(label)
log(`${cells.length - failed.length}/${cells.length} cells returned; grade.sh decides pass or fail, not these self-reports`)
return {
  incomplete: failed.length > 0,
  failed,
  resume: 'relaunch with resumeFromRunId and the same args; finished cells come back from cache',
  self_reported_exit: cells.map((c, i) => [label(c), out[i] ? out[i].verifier_exit : null]),
}
