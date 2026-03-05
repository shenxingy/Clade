// ─── Dashboard update ────────────────────────────────────────────────────────
function updateDashboard(data) {
  // Run-complete notification (one-shot per session per batch)
  if (!window._runCompleteToasted) window._runCompleteToasted = {};
  const _sid = data.session_id;
  if (data.run_complete && !window._runCompleteToasted[_sid]) {
    window._runCompleteToasted[_sid] = true;
    const _sname = sessions.find(s => s.session_id === _sid)?.name || 'session';
    showToast(`✓ All tasks complete — ${_sname}`);
  }
  if (!data.run_complete) delete window._runCompleteToasted[_sid];

  // Always update badge count for whichever session sent this status
  const s = sessions.find(s => s.session_id === data.session_id);
  if (s) {
    s.running_count = (data.workers || []).filter(w => w.status === 'running').length;
    s.worker_count = (data.workers || []).length;
    renderTabs();
  }

  // Only render the full dashboard for the active session
  if (data.session_id && data.session_id !== activeSessionId) return;

  workers = data.workers || [];
  queue = data.queue || [];
  renderQueue();
  renderWorkers();
  renderHistory(data.success_rate);
  updateProgress(data.progress_pct || 0, data.eta_seconds || 0);
  updateSchedulerDisplay(data.schedule);
  updateLoopUI(data.loop_state || null);
  updateSwarmUI(data.swarm_state || null);

  // Total session cost: DB tasks + live workers
  const dbCost = queue.reduce((s, t) => s + (t.estimated_cost || 0), 0);
  const liveCost = workers.filter(w => w.status === 'running').reduce((s, w) => s + (w.estimated_cost || 0), 0);
  const totalCost = dbCost + liveCost;
  const costEl = document.getElementById('footerCost');
  if (costEl) {
    if (data.budget_exceeded) {
      costEl.textContent = `$${totalCost.toFixed(4)} BUDGET`;
      costEl.style.color = 'var(--red)';
    } else {
      costEl.textContent = totalCost > 0 ? `$${totalCost.toFixed(4)}` : '';
      costEl.style.color = 'var(--text2)';
    }
    costEl.dataset.totalCost = totalCost;
  }
  // Budget exceeded toast (one-shot)
  if (!window._budgetToasted) window._budgetToasted = {};
  if (data.budget_exceeded && !window._budgetToasted[data.session_id]) {
    window._budgetToasted[data.session_id] = true;
    showToast(`Cost budget exceeded ($${data.budget_limit}) — auto-start paused`);
  }
  if (!data.budget_exceeded) delete window._budgetToasted[data.session_id];

  // Render start.sh process cards (Phase 13)
  renderProcessCards(data.processes || []);
}

// ─── Process Cards (start.sh) ────────────────────────────────────────────────
function renderProcessCards(processes) {
  let section = document.getElementById('processSection');
  if (processes.length === 0) {
    if (section) section.style.display = 'none';
    return;
  }
  // Create section if it doesn't exist
  if (!section) {
    section = document.createElement('div');
    section.id = 'processSection';
    section.className = 'dashboard-section process-section';
    section.innerHTML = `
      <div class="section-header">
        <span>Running Processes <span id="processCount" style="font-weight:400;color:var(--text2)"></span></span>
        <button class="btn small secondary" onclick="openStartProcessModal()">+ Start Process</button>
      </div>
      <div class="process-cards" id="processCards"></div>
    `;
    // Insert before queue section
    const queue = document.querySelector('.dashboard-section.queue');
    if (queue) queue.parentElement.insertBefore(section, queue);
  }
  section.style.display = '';
  const running = processes.filter(p => p.status === 'running');
  document.getElementById('processCount').textContent = `(${running.length}/${processes.length})`;
  document.getElementById('processCards').innerHTML = processes.map(p => {
    const statusIcon = { running: '▶', converged: '✓', stopped: '■', failed: '✗', blocked: '⏳' }[p.status] || '?';
    return `
      <div class="process-card ${esc(p.status)}">
        <div class="process-card-top">
          <span class="process-name">📁 ${esc(p.project_name)}</span>
          <span class="badge ${esc(p.status)}">${statusIcon} ${esc(p.status)}</span>
          ${p.cost > 0 ? `<span style="font-size:11px;color:var(--text2)">$${p.cost.toFixed(2)}</span>` : ''}
        </div>
        <div class="process-detail">${esc(p.mode)} · ${esc(formatElapsed(p.elapsed_s))}</div>
        <div class="process-actions">
          ${p.status === 'running'
            ? `<button class="btn small danger" onclick="stopProcess('${esc(p.project_dir)}')">Stop</button>`
            : `<button class="btn small" onclick="restartProcess('${esc(p.project_dir)}', '${esc(p.mode)}')">Restart</button>`}
          <button class="btn small secondary" onclick="viewProcessReport('${esc(p.project_dir)}')">Report</button>
        </div>
      </div>`;
  }).join('');
}

async function stopProcess(projectDir) {
  try {
    await fetch(`/api/processes/${encodeURIComponent(projectDir)}`, { method: 'DELETE' });
    showToast('Process stopped');
  } catch (e) { showToast('Failed to stop: ' + e.message, true); }
}

async function restartProcess(projectDir, mode) {
  try {
    await fetch('/api/processes', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ project_dir: projectDir, mode }),
    });
    showToast('Process restarted');
  } catch (e) { showToast('Failed to restart: ' + e.message, true); }
}

async function viewProcessReport(projectDir) {
  try {
    const res = await fetch(`/api/processes/${encodeURIComponent(projectDir)}/report`);
    if (!res.ok) { showToast('No report available', true); return; }
    const data = await res.json();
    // Reuse worker log modal for display
    document.getElementById('workerLogTitle').textContent = `Process Report — ${projectDir.split('/').pop()}`;
    document.getElementById('workerLogContent').textContent = data.report || 'No report available';
    document.getElementById('workerLogModal').classList.remove('hidden');
  } catch (e) { showToast('Failed to load report', true); }
}

function openStartProcessModal() {
  // Simple prompt-based start for now
  const projectDir = prompt('Project directory path:');
  if (!projectDir) return;
  const mode = prompt('Mode (--run, --morning, --patrol, --goal <file>):', '--run');
  if (!mode) return;
  fetch('/api/processes', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ project_dir: projectDir, mode }),
  }).then(r => {
    if (r.ok) showToast('Process started');
    else r.json().then(d => showToast(d.detail || 'Failed', true));
  }).catch(e => showToast('Error: ' + e.message, true));
}

function renderQueue() {
  const list = document.getElementById('queueList');
  const pending = queue.filter(t => ['pending','queued'].includes(t.status));

  document.getElementById('queueCount').textContent = `(${pending.length})`;

  const runAllBtn = document.getElementById('runAllBtn');
  if (runAllBtn) runAllBtn.style.display = pending.length > 0 ? '' : 'none';

  if (pending.length === 0) {
    list.innerHTML = '<div class="empty">No pending tasks</div>';
    renderDag();
    return;
  }

  const doneIds = new Set(queue.filter(t => t.status === 'done').map(t => t.id));

  list.innerHTML = pending.map(task => {
    const deps = task.depends_on || [];
    const blockedBy = deps.filter(dep => !doneIds.has(dep));
    const isBlocked = blockedBy.length > 0;
    const blockedHtml = isBlocked
      ? `<span class="blocked-badge" title="Waiting for: ${esc(blockedBy.join(', '))}">⏳ blocked</span>`
      : '';
    // Score badge
    let scoreBadge = '';
    if (task.score !== null && task.score !== undefined) {
      const cls = task.score >= 80 ? 'ready' : task.score >= 50 ? 'ok' : 'low';
      scoreBadge = `<span class="score-badge ${cls}" title="${esc(task.score_note || '')}">${task.score}</span>`;
    } else {
      scoreBadge = `<span class="score-badge pending" title="Scoring...">…</span>`;
    }
    const critBadge = task.is_critical_path ? '<span style="color:var(--red);font-weight:700;margin-right:2px" title="Critical path — model tier boosted">⚡</span>' : '';
    return `
    <div class="queue-item${isBlocked ? ' blocked' : ''}">
      ${scoreBadge}
      ${critBadge}
      <span class="task-name" title="${esc(task.description)}">${esc(firstLine(task.description))}</span>
      ${blockedHtml}
      <span class="task-model">${esc(task.model)}</span>
      ${task.task_type === 'HORIZONTAL' ? '<span class="badge-h">H</span>' : task.task_type === 'VERTICAL' ? '<span class="badge-v">V</span>' : ''}
      ${task.gh_issue_number ? `<span class="gh-issue-badge" title="GitHub Issue #${task.gh_issue_number}">#${task.gh_issue_number}</span>` : ''}
      <div class="queue-actions">
        <button class="btn small secondary" onclick="sendTaskMessage('${esc(task.id)}')" title="Send message to this task">✉</button>
        <button class="btn small success" onclick="runTask('${esc(task.id)}')">Run</button>
        <button class="btn small danger" onclick="deleteTask('${esc(task.id)}')">×</button>
      </div>
    </div>`;
  }).join('');

  renderDag();
}

function renderWorkers() {
  const list = document.getElementById('workersList');
  document.getElementById('workerCount').textContent = `(${workers.length})`;

  const mergeable = workers.filter(w => w.status === 'done' && w.auto_pushed && !w.pr_url);
  const mergeBtn = document.getElementById('mergeAllBtn');
  if (mergeBtn) {
    mergeBtn.style.display = mergeable.length > 0 ? '' : 'none';
    mergeBtn.textContent = `⬇ Create PRs (${mergeable.length})`;
  }

  // Show/hide Retry Failed button based on whether there are failed workers
  const failedCount = workers.filter(w => w.status === 'failed').length;
  const retryBtn = document.getElementById('retryFailedBtn');
  if (retryBtn) retryBtn.style.display = failedCount > 0 ? '' : 'none';

  if (workers.length === 0) {
    list.innerHTML = '<div class="empty">No active workers<br><span style="font-size:11px;opacity:0.6">Start tasks from the queue above</span></div>';
    return;
  }

  // Preserve focused element so re-render doesn't steal focus from inputs
  const focusedId = document.activeElement && list.contains(document.activeElement)
    ? document.activeElement.id : null;

  list.innerHTML = workers.map(w => {
    let commitDisplay;
    if (w.pr_merged) {
      commitDisplay = `<span style="color:var(--green);font-weight:600">✓ merged</span>`;
    } else if (w.pr_url) {
      const safeUrl = /^https?:\/\//i.test(w.pr_url) ? w.pr_url : '#';
      commitDisplay = `<span style="color:var(--green);font-weight:600">✓ committed · <a href="${esc(safeUrl)}" target="_blank" rel="noopener" style="color:var(--accent)">PR ↗</a></span>`;
    } else if (w.auto_committed) {
      commitDisplay = `<span style="color:var(--green);font-weight:600">✓ committed${w.auto_pushed ? ' · ✓ pushed' : ''}</span>`;
    } else if (w.last_commit) {
      commitDisplay = `<span class="hash">${esc(w.last_commit.slice(0,7))}</span> ${esc(w.last_commit.slice(8,60))}`;
    } else {
      commitDisplay = '<span style="opacity:0.5">no commits yet</span>';
    }

    const canPause = w.status === 'running';
    const canResume = w.status === 'paused';
    const canChat = ['running','paused','blocked'].includes(w.status);

    // Show last log line as a live progress hint when running
    const lastLogLine = w.log_tail
      ? w.log_tail.split('\n').filter(Boolean).pop() || ''
      : '';
    const logTailHtml = (w.status === 'running' || w.status === 'starting') && lastLogLine
      ? `<div class="worker-log-tail" title="${esc(lastLogLine)}">${esc(lastLogLine)}</div>`
      : '';

    const oracleBadge = w.oracle_result === 'approved'
      ? `<span class="badge oracle-ok" title="${esc(w.oracle_reason||'')}">✓ oracle</span>`
      : w.oracle_result === 'rejected'
      ? `<span class="badge oracle-rejected" title="${esc(w.oracle_reason||'')}">✗ oracle</span>`
      : '';
    const modelInfo = `<span style="font-size:10px;opacity:0.5;margin-left:4px">${esc(String(w.model||''))}${w.model_score!=null?' · '+esc(String(w.model_score)):''}</span>`;
    const tokenPct = w.estimated_tokens ? Math.min(100, w.estimated_tokens / 200000 * 100) : 0;
    const tokenColor = w.estimated_tokens > 160000 ? 'var(--red)' : w.estimated_tokens > 120000 ? 'var(--yellow)' : 'var(--green)';
    const tokenBar = w.estimated_tokens > 0
      ? `<div class="token-bar" title="~${(w.estimated_tokens||0).toLocaleString()} tokens"><div class="token-bar-fill" style="width:${tokenPct}%;background:${tokenColor}"></div></div>`
      : '';

    return `
      <div class="worker-card ${esc(w.status)}" id="wcard-${esc(String(w.id))}">
        <div class="worker-top">
          <span class="worker-name" title="${esc(w.description)}">${esc(firstLine(w.description))}</span>
          <span style="font-size:10px;opacity:0.35;font-family:var(--font-mono);flex-shrink:0">#${esc(String(w.id))}</span>
          <span class="badge ${esc(w.status)}">${esc(w.status)}</span>${oracleBadge}${modelInfo}
          ${w.task_type === 'HORIZONTAL' ? '<span class="badge-h">H</span>' : w.task_type === 'VERTICAL' ? '<span class="badge-v">V</span>' : ''}
        </div>
        ${logTailHtml}
        <div class="worker-commit">${commitDisplay}</div>
        ${tokenBar}
        <div class="worker-footer">
          <span class="elapsed" id="elapsed-${esc(String(w.id))}">${formatElapsed(w.elapsed_s)}</span>
          ${w.estimated_cost > 0 ? `<span style="font-size:10px;color:var(--text2);margin-left:4px">$${w.estimated_cost.toFixed(4)}</span>` : ''}
          ${canPause ? `<button class="btn small secondary" id="btn-pause-${esc(String(w.id))}" data-wid="${esc(String(w.id))}" onclick="pauseWorker(this.dataset.wid)">Pause</button>` : ''}
          ${canResume ? `<button class="btn small" id="btn-resume-${esc(String(w.id))}" data-wid="${esc(String(w.id))}" onclick="resumeWorker(this.dataset.wid)">Resume</button>` : ''}
          ${canChat ? `<button class="btn small secondary" id="btn-chat-${esc(String(w.id))}" data-wid="${esc(String(w.id))}" data-name="${esc(firstLine(w.description))}" onclick="openWorkerChat(this.dataset.wid, this.dataset.name)">Chat</button>` : ''}
          <button class="btn small secondary" id="btn-log-${esc(String(w.id))}" data-wid="${esc(String(w.id))}" data-name="${esc(firstLine(w.description))}" onclick="openWorkerLog(this.dataset.wid, this.dataset.name)">Log</button>
        </div>
      </div>`;
  }).join('');

  // Restore focus if a button/element inside the list had focus before re-render
  if (focusedId) {
    const el = document.getElementById(focusedId);
    if (el) el.focus();
  }

  // Tick elapsed timers locally so they update without full re-render
  startElapsedTickers();
}

function startElapsedTickers() {
  clearInterval(window._elapsedInterval);
  window._elapsedInterval = setInterval(() => {
    workers.forEach(w => {
      // Only tick for actively running workers; done/paused/blocked stay frozen
      if (w.status === 'running') {
        const el = document.getElementById(`elapsed-${w.id}`);
        if (el) {
          w.elapsed_s++;
          el.textContent = formatElapsed(w.elapsed_s);
        }
      }
    });
  }, 1000);
}

function updateProgress(pct, eta) {
  document.getElementById('progressFill').style.width = pct + '%';
  document.getElementById('progressLabel').textContent = pct + '%';
  document.getElementById('etaLabel').textContent = eta > 0 ? `ETA ${formatElapsed(eta)}` : '';
}

// ─── Task actions ────────────────────────────────────────────────────────────
async function runTask(id) {
  try {
    const res = await fetch(`/api/tasks/${id}/run?session=${activeSessionId}`, { method: 'POST' });
    if (!res.ok) showToast('Failed to start task', true);
  } catch(e) { showToast('Error: ' + e.message, true); }
}

async function deleteTask(id) {
  try {
    const res = await fetch(`/api/tasks/${id}?session=${activeSessionId}`, { method: 'DELETE' });
    if (!res.ok) showToast('Failed to delete task', true);
  } catch(e) { showToast('Error: ' + e.message, true); }
}

async function sendTaskMessage(taskId) {
  const content = prompt('Message to send to this task (will be injected when worker starts):');
  if (!content || !content.trim()) return;
  try {
    await fetch(`/api/tasks/${taskId}/messages?session=${activeSessionId}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ content: content.trim() }),
    });
    showToast('Message sent');
  } catch(e) {
    showToast('Error sending message: ' + e.message);
  }
}

async function addTask() {
  const desc = document.getElementById('newTaskDesc').value.trim();
  const model = document.getElementById('newTaskModel').value;
  if (!desc) return;

  try {
    // If it's ===TASK=== format, send content to server then import
    if (desc.includes('===TASK===')) {
      await fetch(`/api/tasks/import-proposed?session=${activeSessionId}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content: desc }),
      });
    } else {
      const isCritical = document.getElementById('newTaskCritical')?.checked ? 1 : 0;
      await fetch(`/api/tasks?session=${activeSessionId}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ description: desc, model, is_critical_path: isCritical }),
      });
    }
    document.getElementById('newTaskDesc').value = '';
    const critEl = document.getElementById('newTaskCritical');
    if (critEl) critEl.checked = false;
  } catch(e) {
    showToast('Error adding task: ' + e.message);
    // textarea value is preserved (not cleared)
  }
}

async function importProposedToQueue() {
  try {
    const res = await fetch(`/api/tasks/import-proposed?session=${activeSessionId}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: '{}',
    });
    const data = await res.json();
    if (!res.ok) { showToast(`Import failed: ${data.detail || res.status}`, true); return; }
    const skipped = data.skipped || {};
    const skipTotal = Object.values(skipped).reduce((a, b) => a + b, 0);
    if (data.imported === 0 && skipTotal > 0) {
      const skipParts = Object.entries(skipped).map(([s, n]) => `${n} ${s}`).join(', ');
      showToast(`Imported 0 tasks — ${skipTotal} already in queue (${skipParts})`, true);
    } else {
      const suffix = skipTotal > 0 ? `, ${skipTotal} skipped (already in queue)` : '';
      showToast(`Imported ${data.imported} tasks${suffix}`);
    }
  } catch (e) {
    showToast('Error importing tasks: ' + e.message, true);
  }
}

function toggleAddTask() {
  const row = document.getElementById('addTaskRow');
  const presets = document.getElementById('presetCardsRow');
  const show = row.style.display === 'none';
  row.style.display = show ? 'block' : 'none';
  if (presets) presets.style.display = show ? 'block' : 'none';
}

function applyPreset(type) {
  const presets = {
    'test-writer': {
      text: "Scan the codebase for untested functions and modules. Write comprehensive unit tests using the project's existing test framework. Focus on edge cases, error paths, and boundary conditions. Commit tests with meaningful names.",
      model: 'sonnet',
      taskType: 'HORIZONTAL'
    },
    'refactor-bot': {
      text: 'Identify code smells: duplicated logic, overly long functions (>50 lines), magic numbers, unclear naming, deeply nested conditionals. Refactor for readability and maintainability. No behavior changes — tests must still pass.',
      model: 'sonnet',
      taskType: 'HORIZONTAL'
    },
    'docs-bot': {
      text: 'Review the codebase for missing or outdated documentation. Write or update: module-level docstrings, README sections, inline comments for non-obvious logic. Focus on public APIs and key algorithms.',
      model: 'haiku',
      taskType: 'VERTICAL'
    },
    'security-scan': {
      text: 'Audit the codebase for security vulnerabilities: SQL injection, XSS, hardcoded secrets, insecure deserialization, missing input validation, overly permissive CORS, exposed error details in API responses. Fix any issues found.',
      model: 'sonnet',
      taskType: 'VERTICAL'
    }
  };
  const p = presets[type];
  if (!p) return;
  const textarea = document.getElementById('newTaskDesc');
  if (textarea) textarea.value = p.text;
  const modelSel = document.getElementById('newTaskModel');
  if (modelSel) modelSel.value = p.model;
  const typeSel = document.getElementById('taskType');
  if (typeSel) typeSel.value = p.taskType;
}

// ─── Worker actions ──────────────────────────────────────────────────────────
async function pauseWorker(id) {
  try {
    const res = await fetch(`/api/workers/${id}/pause?session=${activeSessionId}`, { method: 'POST' });
    if (!res.ok) showToast('Failed to pause worker', true);
  } catch(e) { showToast('Error: ' + e.message, true); }
}

async function resumeWorker(id) {
  try {
    const res = await fetch(`/api/workers/${id}/resume?session=${activeSessionId}`, { method: 'POST' });
    if (!res.ok) showToast('Failed to resume worker', true);
  } catch(e) { showToast('Error: ' + e.message, true); }
}

function openWorkerChat(id, name) {
  activeWorkerId = id;
  const displayName = decodeHtml(name);
  document.getElementById('workerChatSub').textContent =
    `Worker: ${displayName}\nStops the worker, injects your message as context, and restarts it.`;
  document.getElementById('workerChatInput').value = '';
  document.getElementById('workerChatModal').classList.remove('hidden');
  document.getElementById('workerChatInput').focus();
}

function closeWorkerChat() {
  document.getElementById('workerChatModal').classList.add('hidden');
  activeWorkerId = null;
}

