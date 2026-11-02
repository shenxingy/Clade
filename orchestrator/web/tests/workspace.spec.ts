import { test, expect, type Page, type WebSocketRoute } from '@playwright/test';

// Browser tests exercise the UI/API boundary with deterministic server replies.
// No real repository, agent, provider credentials or paid calls are used.
const project = (id: string) => ({ session_id: id, name: id, path: `/projects/${id}`, alive: true, worker_count: 0, running_count: 0, schedule: null });
const task = (id: string, status = 'pending') => ({ id, description: `Verify the ${id} workflow and its test results`, status, model: 'configured-model', agent_runtime: 'codex', elapsed_s: 0, failed_reason: null, last_commit: null });

async function fixture(page: Page, options: { empty?: boolean; auth?: boolean; auto?: boolean } = {}) {
  let sessions = options.empty ? [] : [project('alpha'), project('beta')];
  const queues: Record<string, ReturnType<typeof task>[]> = { alpha: [], beta: [task('beta-task')] };
  const sockets: { id: string; ws: WebSocketRoute }[] = [];
  const requests: string[] = [];
  let rejectRun = false;
  let rejectCreate = false;
  let rejectTask = false;
  const snapshot = (id: string) => ({ type: 'status', session_id: id, queue: queues[id] ?? [], workers: [], budget_limit: 0 });
  const broadcast = (id: string) => sockets.filter(s => s.id === id).forEach(s => { try { s.ws.send(JSON.stringify(snapshot(id))); } catch { /* Closed by navigation. */ } });
  await page.routeWebSocket('**/ws/status?**', ws => {
    const id = new URL(ws.url()).searchParams.get('session')!;
    sockets.push({ id, ws });
    ws.send(JSON.stringify(snapshot(id)));
  });
  await page.route('**/api/**', async route => {
    const request = route.request();
    const url = new URL(request.url());
    const id = url.searchParams.get('session') ?? 'alpha';
    const path = url.pathname;
    const method = request.method();
    requests.push(`${method} ${path}?session=${id}`);
    if (options.auth && request.headers().authorization !== 'Bearer test-key') return route.fulfill({ status: 401, json: { detail: 'Access token required' } });
    if (path === '/api/settings') return route.fulfill({ json: { agent_runtime: 'codex', default_model: 'configured-model', auto_start: options.auto ?? false, connections: {}, runtime_connections: {} } });
    if (path === '/api/sessions' && method === 'GET') return route.fulfill({ json: sessions });
    if (path === '/api/sessions') {
      if (rejectCreate) return route.fulfill({ status: 400, json: { detail: 'Directory not found' } });
      const name = request.postDataJSON().path.split('/').pop();
      const created = project(name);
      sessions = [...sessions, created]; queues[name] = [];
      return route.fulfill({ json: created });
    }
    if (path === '/api/tasks' && method === 'GET') return route.fulfill({ json: queues[id] ?? [] });
    if (path === '/api/tasks' && method === 'POST') {
      if (rejectTask) return route.fulfill({ status: 500, json: { detail: 'Task could not be saved' } });
      const created = { ...task('new-task'), description: request.postDataJSON().description };
      queues[id].push(created);
      return route.fulfill({ json: created });
    }
    if (path.endsWith('/run')) {
      if (rejectRun) return route.fulfill({ json: { error: 'Blocked by unfinished dependencies' } });
      const current = queues[id].find(t => path.includes(t.id))!;
      current.status = 'running';
      await route.fulfill({ json: { worker_id: 'worker-1' } }); broadcast(id); return;
    }
    if (path.endsWith('/retry')) {
      queues[id].find(t => path.includes(t.id))!.status = 'pending';
      return route.fulfill({ json: { ok: true } });
    }
    if (path.endsWith('/evidence')) return route.fulfill({ json: { attempts: [{ attempt_id: 'a1', attempt_index: 1, lifecycle_state: 'delivered', evidence: { verification: 'tests passed' } }] } });
    if (path.endsWith('/log')) return route.fulfill({ json: { log: 'Verification completed: 4 tests passed' } });
    return route.fulfill({ status: 404, json: { detail: `Unexpected request ${path}` } });
  });
  return { queues, sockets, requests, broadcast, rejectRun: () => { rejectRun = true; }, rejectCreate: (value: boolean) => { rejectCreate = value; }, rejectTask: (value: boolean) => { rejectTask = value; } };
}

test('fresh workspace → project → task → run → persisted result', async ({ page }) => {
  const f = await fixture(page, { empty: true });
  await page.goto('/web/');
  await expect(page.getByRole('heading', { level: 1 })).toContainText('work you can review');
  await page.getByRole('button', { name: 'Open project', exact: true }).click();
  await page.getByLabel('Project folder').fill('/projects/alpha');
  await page.getByRole('dialog').getByRole('button', { name: 'Open project', exact: true }).click();
  await page.getByRole('button', { name: 'New task', exact: true }).click();
  await page.getByLabel('What should the agent do?').fill('Add a keyboard-accessible search field and verify it');
  await page.getByRole('button', { name: 'Add to queue' }).click();
  const card = page.getByRole('button', { name: /Add a keyboard-accessible/ });
  await card.click();
  await page.getByRole('button', { name: 'Run task', exact: true }).click();
  await expect(page.getByRole('dialog')).toContainText('running');
  f.queues.alpha[0].status = 'done'; f.broadcast('alpha');
  await expect(page.getByRole('dialog')).toContainText('Execution is complete');
  await expect(page.getByRole('dialog')).toContainText('4 tests passed');
  await page.getByText('Attempt 1 · delivered', { exact: true }).click();
  await expect(page.getByRole('dialog')).toContainText('tests passed');
  await page.getByRole('button', { name: 'Close dialog' }).click();
  await page.reload();
  await expect(page.getByRole('region', { name: 'Completed', exact: true })).toContainText('keyboard-accessible');
  expect(f.requests.filter(r => r.startsWith('POST /api/tasks?'))).toHaveLength(1);
});

test('authentication and invalid project errors have recoverable forms', async ({ page }) => {
  const f = await fixture(page, { empty: true, auth: true });
  await page.goto('/web/');
  await page.getByLabel('Access token').fill('test-key');
  await page.getByRole('button', { name: 'Connect', exact: true }).click();
  await page.getByRole('button', { name: 'Open project', exact: true }).click();
  f.rejectCreate(true);
  await page.getByLabel('Project folder').fill('/missing');
  await page.getByRole('dialog').getByRole('button', { name: 'Open project', exact: true }).click();
  await expect(page.getByRole('alert')).toContainText('Directory not found');
  await expect(page.getByLabel('Project folder')).toHaveValue('/missing');
  f.rejectCreate(false);
  await page.getByLabel('Project folder').fill('/projects/alpha');
  await page.getByRole('dialog').getByRole('button', { name: 'Open project', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'alpha', exact: true })).toBeVisible();
});

test('task submission keeps a failed draft and states automatic execution', async ({ page }) => {
  const f = await fixture(page, { auto: true });
  await page.goto('/web/');
  await page.getByRole('button', { name: 'New task', exact: true }).click();
  await expect(page.getByRole('dialog')).toContainText('Automatic execution is on');
  await page.getByLabel('What should the agent do?').fill('short');
  await expect(page.getByRole('button', { name: 'Add to queue' })).toBeDisabled();
  await page.getByLabel('What should the agent do?').fill('Preserve this task draft when saving fails');
  f.rejectTask(true);
  await page.getByRole('button', { name: 'Add to queue' }).click();
  await expect(page.getByRole('alert')).toContainText('Task could not be saved');
  await expect(page.getByLabel('What should the agent do?')).toHaveValue('Preserve this task draft when saving fails');
  f.rejectTask(false);
  await page.getByRole('button', { name: 'Add to queue' }).click();
  await expect(page.getByRole('button', { name: /Preserve this task draft/ })).toBeVisible();
});

test('HTTP 200 action refusals stay visible; interrupted tasks can be retried', async ({ page }) => {
  const f = await fixture(page);
  f.queues.alpha = [task('blocked-by-deps'), task('interrupted-task', 'interrupted')];
  f.rejectRun();
  await page.goto('/web/');
  await page.getByRole('button', { name: /Verify the blocked-by-deps/ }).click();
  await page.getByRole('button', { name: 'Run task' }).click();
  await expect(page.getByRole('alert')).toContainText('Blocked by unfinished dependencies');
  await page.keyboard.press('Escape');
  await page.getByRole('button', { name: /Verify the interrupted-task/ }).click();
  await page.getByRole('button', { name: 'Retry task' }).click();
  await expect(page.getByRole('button', { name: 'Run task' })).toBeVisible();
});

test('switching projects ignores late snapshots and remembers selection', async ({ page }) => {
  const f = await fixture(page);
  f.queues.alpha = [task('alpha-task')];
  await page.goto('/web/');
  await expect(page.getByRole('button', { name: /Verify the alpha-task/ })).toBeVisible();
  await page.getByLabel('Active project').selectOption('beta');
  await expect(page.getByRole('button', { name: /Verify the beta-task/ })).toBeVisible();
  f.broadcast('alpha');
  await expect(page.getByRole('button', { name: /Verify the alpha-task/ })).toHaveCount(0);
  await page.reload();
  await expect(page.getByLabel('Active project')).toHaveValue('beta');
  await expect(page.getByRole('button', { name: /Verify the beta-task/ })).toBeVisible();
});

test('reconnecting the live stream preserves an unsent draft', async ({ page }) => {
  const f = await fixture(page);
  await page.goto('/web/');
  await page.getByRole('button', { name: 'New task', exact: true }).click();
  await page.getByLabel('What should the agent do?').fill('Keep this draft through a connection loss');
  const previousCount = f.sockets.length;
  f.sockets[f.sockets.length - 1].ws.close();
  await expect.poll(() => f.sockets.length, { timeout: 7000 }).toBeGreaterThan(previousCount);
  await expect(page.getByLabel('What should the agent do?')).toHaveValue('Keep this draft through a connection loss');
});

for (const width of [390, 768, 1280, 1440]) {
  test(`keyboard forms and responsive layout at ${width}px`, async ({ page }) => {
    const f = await fixture(page);
    f.queues.alpha = [task('keyboard-task', 'blocked')];
    await page.setViewportSize({ width, height: 900 });
    await page.emulateMedia({ reducedMotion: 'reduce' });
    await page.goto('/web/');
    const create = page.getByRole('button', { name: 'New task', exact: true });
    await create.focus(); await page.keyboard.press('Enter');
    await expect(page.getByRole('dialog')).toBeVisible();
    await page.getByLabel('What should the agent do?').focus();
    await page.keyboard.type('Check the keyboard-only project workflow');
    await page.keyboard.press('Shift+Tab');
    await expect(page.getByRole('button', { name: 'Close dialog' })).toBeFocused();
    await page.keyboard.press('Shift+Tab');
    await expect(page.getByRole('button', { name: 'Add to queue' })).toBeFocused();
    await page.keyboard.press('Escape');
    await expect(create).toBeFocused();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
    if (process.env.CLADE_SCREENSHOTS) await page.screenshot({ path: `${process.env.CLADE_SCREENSHOTS}/workspace-${width}.png`, fullPage: true });
    await page.getByRole('button', { name: /Verify the keyboard-task/ }).focus();
    await page.keyboard.press('Enter');
    await expect(page.getByRole('dialog')).toContainText('Task details');
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
    if (process.env.CLADE_SCREENSHOTS) await page.screenshot({ path: `${process.env.CLADE_SCREENSHOTS}/detail-${width}.png`, fullPage: true });
  });
}
