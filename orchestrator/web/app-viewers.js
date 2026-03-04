// ─── Worker Log viewer ────────────────────────────────────────────────────────
let activeLogWorkerId = null;
let _logRefreshInterval = null;

async function openWorkerLog(id, name) {
  activeLogWorkerId = id;
  const displayName = decodeHtml(name);
  document.getElementById('workerLogTitle').textContent = `#${id} — ${displayName}`;
  document.getElementById('workerLogModal').classList.remove('hidden');
  await refreshWorkerLog();
  // Auto-refresh every 2s while the worker is still active
  clearInterval(_logRefreshInterval);
  _logRefreshInterval = setInterval(async () => {
    const w = workers.find(w => String(w.id) === String(activeLogWorkerId));
    if (!w || !['running', 'starting'].includes(w.status)) {
      clearInterval(_logRefreshInterval);
      _logRefreshInterval = null;
      return;
    }
    await refreshWorkerLog();
  }, 2000);
}

async function refreshWorkerLog() {
  if (!activeLogWorkerId) return;
  const el = document.getElementById('workerLogContent');
  try {
    const res = await fetch(`/api/workers/${activeLogWorkerId}/log?lines=300&session=${activeSessionId}`);
    const data = await res.json();
    el.textContent = data.log || '(empty log)';
    el.scrollTop = el.scrollHeight;  // always follow latest output
  } catch(e) {
    el.textContent = 'Error loading log.';
  }
}

function closeWorkerLog() {
  clearInterval(_logRefreshInterval);
  _logRefreshInterval = null;
  document.getElementById('workerLogModal').classList.add('hidden');
  activeLogWorkerId = null;
}

// ─── Code TLDR viewer ───────────────────────────────────────────────────────

async function showCodeTldr() {
  if (!activeSessionId) return;
  if (_logRefreshInterval) { clearInterval(_logRefreshInterval); _logRefreshInterval = null; }
  document.getElementById('workerLogTitle').textContent = 'Code TLDR';
  document.getElementById('workerLogContent').textContent = 'Loading...';
  document.getElementById('workerLogModal').classList.remove('hidden');
  try {
    const res = await fetch(`/api/sessions/${activeSessionId}/code-tldr`);
    const data = await res.json();
    document.getElementById('workerLogContent').textContent = data.tldr || '(empty)';
  } catch(e) {
    document.getElementById('workerLogContent').textContent = 'Error loading TLDR.';
  }
}

// ─── Interventions viewer ───────────────────────────────────────────────────

async function showInterventions() {
  if (!activeSessionId) return;
  if (_logRefreshInterval) { clearInterval(_logRefreshInterval); _logRefreshInterval = null; }
  document.getElementById('workerLogTitle').textContent = 'Recorded Interventions';
  document.getElementById('workerLogContent').textContent = 'Loading...';
  document.getElementById('workerLogModal').classList.remove('hidden');
  try {
    const res = await fetch(`/api/interventions?session=${activeSessionId}`);
    const data = await res.json();
    if (!data.length) {
      document.getElementById('workerLogContent').textContent = '(no interventions recorded yet)';
      return;
    }
    const text = data.map(iv => {
      const status = iv.success ? '[SUCCESS]' : '[pending]';
      const ts = iv.created_at ? new Date(iv.created_at * 1000).toLocaleString() : '';
      return `${status} ${ts}\nPattern: ${iv.failure_pattern}\nCorrection: ${iv.correction}\nTask hint: ${iv.task_description_hint || '(none)'}\n`;
    }).join('\n---\n\n');
    document.getElementById('workerLogContent').textContent = text;
  } catch(e) {
    document.getElementById('workerLogContent').textContent = 'Error loading interventions.';
  }
}

async function sendWorkerMessage() {
  if (!activeWorkerId) return;
  const msg = document.getElementById('workerChatInput').value.trim();
  if (!msg) return;
  try {
    const res = await fetch(`/api/workers/${activeWorkerId}/message?session=${activeSessionId}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: msg }),
    });
    if (!res.ok) { showToast('Failed to send message', true); return; }
    closeWorkerChat();
    showToast('Message sent — worker restarted with new context');
  } catch(e) {
    showToast('Error: ' + e.message, true);
  }
}

document.getElementById('workerChatInput').addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && e.metaKey) sendWorkerMessage();
  if (e.key === 'Escape') closeWorkerChat();
});

// ─── Proposed Tasks Overlay ──────────────────────────────────────────────────
function showProposedOverlay(content) {
  // Render a simplified preview
  const blocks = content.split('===TASK===').filter(b => b.trim());
  const preview = blocks.map((b, i) => {
    const lines = b.trim().split('\n');
    const headerEnd = lines.findIndex(l => l.trim() === '---');
    const title = headerEnd >= 0
      ? lines.slice(headerEnd + 1).find(l => l.trim()) || `Task ${i+1}`
      : `Task ${i+1}`;
    return `<div class="task-title">Task ${i+1}: ${esc(title.trim())}</div>`;
  }).join('\n');

  document.getElementById('proposedPreview').innerHTML =
    `<div style="margin-bottom:8px;color:var(--text2)">${blocks.length} task${blocks.length !== 1 ? 's' : ''} proposed</div>` + preview;
  document.getElementById('proposedOverlay').classList.remove('hidden');
}

function skipProposed() {
  document.getElementById('proposedOverlay').classList.add('hidden');
}

async function editProposed() {
  document.getElementById('proposedOverlay').classList.add('hidden');
  document.getElementById('addTaskRow').style.display = 'block';
  // Populate textarea with the last proposed-tasks content so user can edit inline
  if (window._lastProposedContent) {
    document.getElementById('newTaskDesc').value = window._lastProposedContent;
    showToast('Edit the ===TASK=== blocks, then click Add Task');
  } else {
    showToast('Edit .claude/proposed-tasks.md directly, then click "Import Proposed"');
  }
}

async function confirmProposed() {
  document.getElementById('proposedOverlay').classList.add('hidden');
  try {
    // Import then start all
    const importRes = await fetch(`/api/tasks/import-proposed?session=${activeSessionId}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ content: window._lastProposedContent || '' }),
    });
    if (!importRes.ok) { showToast('Failed to import tasks', true); return; }
    const res = await fetch(`/api/tasks/start-all?session=${activeSessionId}`, { method: 'POST' });
    if (!res.ok) { showToast('Failed to start workers', true); return; }
    const data = await res.json();
    showToast(`Started ${data.started} workers`);
  } catch(e) {
    showToast('Error importing tasks: ' + e.message, true);
  }
}

async function runAllTasks() {
  const btn = document.getElementById('runAllBtn');
  if (btn) btn.disabled = true;
  try {
    const res = await fetch(`/api/tasks/start-all?session=${activeSessionId}`, { method: 'POST' });
    if (!res.ok) { showToast('Failed to start workers', true); return; }
    const data = await res.json();
    showToast(`Started ${data.started} worker${data.started !== 1 ? 's' : ''}`);
  } catch(e) { showToast('Error: ' + e.message, true); }
  finally { if (btn) btn.disabled = false; }
}

async function retryAllFailed() {
  const btn = document.getElementById('retryFailedBtn');
  if (btn) btn.disabled = true;
  try {
    const res = await fetch(`/api/tasks/retry-failed?session=${activeSessionId}`, { method: 'POST' });
    if (!res.ok) { showToast('Failed to retry tasks', true); return; }
    const data = await res.json();
    showToast(`Requeued ${data.retried} failed task${data.retried !== 1 ? 's' : ''} with error context`);
  } catch(e) { showToast('Error: ' + e.message); }
  finally { if (btn) btn.disabled = false; }
}

async function retryInterrupted(taskId) {
  try {
    const res = await fetch(`/api/tasks/${taskId}/retry?session=${activeSessionId}`, { method: 'POST' });
    const data = await res.json();
    if (data.ok) showToast('Task reset to pending — will auto-start');
    else showToast(data.error || 'Retry failed');
  } catch(e) { showToast('Error: ' + e.message); }
}

// ─── Task History (done/failed) ───────────────────────────────────────────────
let _historyExpanded = false;
let _lastSuccessRate;

function renderHistory(successRate) {
  if (successRate !== undefined) _lastSuccessRate = successRate;
  else successRate = _lastSuccessRate;
  const history = queue.filter(t => ['done', 'failed', 'interrupted'].includes(t.status));
  const section = document.getElementById('historySection');
  const listEl = document.getElementById('historyList');
  const countEl = document.getElementById('historyCount');
  const rateEl = document.getElementById('successRateLabel');

  if (history.length === 0) {
    section.style.display = 'none';
    return;
  }
  section.style.display = '';
  countEl.textContent = `(${history.length})`;
  if (successRate !== undefined) {
    rateEl.textContent = `${successRate}% success`;
    rateEl.style.color = successRate >= 80 ? 'var(--green)' : successRate >= 50 ? 'var(--yellow)' : 'var(--red)';
    const footerRate = document.getElementById('footerSuccessRate');
    if (footerRate) {
      footerRate.textContent = `${successRate}% success`;
      footerRate.style.color = successRate >= 80 ? 'var(--green)' : successRate >= 50 ? 'var(--yellow)' : 'var(--red)';
    }
  }

  if (!_historyExpanded) return; // collapsed — only update counts

  listEl.innerHTML = history.map(t => {
    const badge = `<span class="badge ${esc(t.status)}" style="font-size:10px">${esc(t.status)}</span>`;
    const hash = t.last_commit ? `<span class="hash" style="font-size:10px">${esc(t.last_commit.slice(0,8))}</span>` : '';
    const retryBtn = (t.status === 'interrupted' || t.status === 'failed')
      ? `<button class="btn small secondary" onclick="retryInterrupted('${esc(t.id)}')" style="padding:1px 6px;font-size:10px;margin-left:auto;flex-shrink:0">↺ Retry</button>`
      : '';
    return `<div class="queue-item" style="opacity:${t.status==='done'?'1':'0.65'}">
      ${badge}
      <span class="task-name" title="${esc(t.description)}">${esc(firstLine(t.description))}</span>
      ${hash}
      ${retryBtn}
    </div>`;
  }).join('');
}

function toggleHistoryList() {
  _historyExpanded = !_historyExpanded;
  const listEl = document.getElementById('historyList');
  const chevron = document.getElementById('historyChevron');
  listEl.style.display = _historyExpanded ? '' : 'none';
  chevron.textContent = _historyExpanded ? '▼' : '▶';
  if (_historyExpanded) renderHistory(undefined); // re-render with content
}

// ─── Scheduler ────────────────────────────────────────────────────────────────
function updateSchedulerDisplay(schedule) {
  _lastSchedule = schedule;
  const bar = document.getElementById('schedulerBar');
  const countdown = document.getElementById('scheduleCountdown');
  const cancelBtn = document.getElementById('cancelScheduleBtn');
  if (!bar) return;
  // Show scheduler bar only in execute mode
  bar.style.display = currentMode === 'execute' ? 'flex' : 'none';
  if (!schedule || !schedule.at) {
    countdown.textContent = '';
    cancelBtn.style.display = 'none';
    return;
  }
  cancelBtn.style.display = '';
  if (schedule.triggered) {
    countdown.textContent = '🚀 Started!';
  } else if (schedule.in_seconds > 0) {
    countdown.textContent = `Starting in ${formatElapsed(schedule.in_seconds)}`;
  } else {
    countdown.textContent = '⏳ Starting...';
  }
}

async function setSchedule() {
  const t = document.getElementById('scheduleTime').value;
  if (!t || !activeSessionId) return;
  const r = await fetch(`/api/sessions/${activeSessionId}/schedule`, {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({ time: t }),
  });
  if (!r.ok) { showToast('Failed to set schedule', true); return; }
  const d = await r.json();
  if (d.in_seconds) {
    showToast(`Scheduled to auto-start in ${formatElapsed(d.in_seconds)}`);
  }
}

async function cancelSchedule() {
  if (!activeSessionId) return;
  try {
    const res = await fetch(`/api/sessions/${activeSessionId}/schedule`, { method: 'DELETE' });
    if (!res.ok) { showToast('Failed to cancel schedule', true); return; }
    document.getElementById('scheduleCountdown').textContent = '';
    document.getElementById('cancelScheduleBtn').style.display = 'none';
    showToast('Schedule cancelled');
  } catch (e) { showToast('Error: ' + e.message, true); }
}

// ─── Header status ───────────────────────────────────────────────────────────
function setOrchStatus(state, text) {
  const dot = document.getElementById('orchDot');
  const label = document.getElementById('orchStatus');
  dot.className = 'dot ' + (state === 'connected' ? 'green' : state === 'connecting' ? 'yellow' : 'red');
  label.textContent = text;
}

// ─── Toast ───────────────────────────────────────────────────────────────────
function showToast(msg, isError = false) {
  const el = document.createElement('div');
  el.textContent = msg;
  Object.assign(el.style, {
    position: 'fixed', bottom: '24px', left: '50%', transform: 'translateX(-50%)',
    background: isError ? 'rgba(192,83,74,0.08)' : 'var(--bg2)',
    border: `1px solid ${isError ? 'var(--red)' : 'var(--border)'}`,
    borderRadius: '12px', boxShadow: 'var(--shadow-md)',
    padding: '10px 18px', fontSize: '13px', color: 'var(--text)',
    zIndex: '999', transition: 'opacity 0.3s',
  });
  document.body.appendChild(el);
  setTimeout(() => { el.style.opacity = '0'; setTimeout(() => el.remove(), 300); }, 3000);
}

// ─── Utilities ───────────────────────────────────────────────────────────────
function cssVar(name) { return getComputedStyle(document.documentElement).getPropertyValue(name).trim(); }

function esc(s) {
  return String(s || '')
    .replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')
    .replace(/"/g,'&quot;').replace(/'/g,'&#39;');
}

function decodeHtml(str) {
  const txt = document.createElement('textarea');
  txt.innerHTML = str;
  return txt.value;
}

function firstLine(s) {
  return String(s || '').split('\n')[0].trim();
}

function formatElapsed(s) {
  s = Math.max(0, Math.round(s));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  if (h > 0) return `${h}h${m.toString().padStart(2,'0')}m`;
  if (m === 0) return `${sec}s`;
  return `${m}m${sec.toString().padStart(2,'0')}s`;
}

// ─── Usage ───────────────────────────────────────────────────────────────────
async function refreshUsage() {
  try {
    const res = await fetch('/api/usage');
    const d = await res.json();
    const today = d.today || {};
    const week = d.this_week || {};
    document.getElementById('usageText').textContent =
      `Today: ${today.messages||0} msgs · ${today.sessions||0} sessions  |  Week: ${week.messages||0} msgs`;
    document.getElementById('usageUpdated').textContent = `stats as of ${d.last_updated||'?'}`;
  } catch(e) {
    document.getElementById('usageText').textContent = 'Usage unavailable';
  }
}

// ─── Boot ────────────────────────────────────────────────────────────────────
// loadSessions() creates session states + connects WS for all sessions
loadSessions();
refreshUsage();
setInterval(refreshUsage, 60000);
// Check on load whether to show the portfolio button (≥2 sessions)
updatePortfolio();
// Restore suggested goals from sessionStorage for current session
(function restoreSuggestedGoals() {
  if (!activeSessionId) return;
  const saved = sessionStorage.getItem('suggestedGoals_' + activeSessionId);
  if (saved) showSuggestedGoals(saved, null);
})();

// ─── Project switcher ────────────────────────────────────────────────────────
function refreshProjectBadge() {
  const capturedSid = activeSessionId;
  const active = sessions.find(s => s.session_id === capturedSid);
  const btn = document.getElementById('projectBadge');
  if (active) {
    btn.textContent = '📁 ' + active.name;
    btn.title = (active.path || active.name) + '\n(click to add another project)';
  } else {
    fetch('/api/project').then(r => r.json()).then(d => {
      if (activeSessionId !== capturedSid) return;
      btn.textContent = '📁 ' + d.name;
      btn.title = d.path + '\n(click to add another project)';
    }).catch(e => { console.warn(e); });
  }
}

function openProjectPicker() {
  document.getElementById('projectPickerModal').classList.remove('hidden');
  document.getElementById('projectPathInput').focus();
  loadProjects();
}

function closeProjectPicker() {
  document.getElementById('projectPickerModal').classList.add('hidden');
}

async function loadProjects() {
  const list = document.getElementById('projectList');
  list.innerHTML = '<div class="empty">Scanning...</div>';
  try {
    const res = await fetch('/api/projects');
    const projects = await res.json();
    if (!projects.length) {
      list.innerHTML = '<div class="empty">No git repos found under home dir</div>';
      return;
    }
    list.innerHTML = '';
    projects.forEach(p => {
      const div = document.createElement('div');
      div.dataset.path = p.path;
      div.style.cssText = 'padding:8px 14px;border-bottom:1px solid var(--border);cursor:pointer;display:flex;align-items:center;gap:10px;';
      div.addEventListener('mouseover', () => { div.style.background = 'var(--bg2)'; });
      div.addEventListener('mouseout', () => { div.style.background = ''; });
      div.addEventListener('click', () => selectProject(p.path));
      const name = document.createElement('span');
      name.style.cssText = 'font-weight:500;font-size:13px';
      name.textContent = p.name;
      const path = document.createElement('span');
      path.style.cssText = 'font-size:11px;color:var(--text2);font-family:var(--font-mono)';
      path.textContent = p.path;
      div.appendChild(name);
      div.appendChild(path);
      list.appendChild(div);
    });
  } catch(e) {
    list.innerHTML = '<div class="empty">Error scanning projects</div>';
  }
}

function selectProject(path) {
  document.getElementById('projectPathInput').value = path;
}

async function confirmProjectSwitch() {
  const path = document.getElementById('projectPathInput').value.trim();
  if (!path) return;
  closeProjectPicker();
  showToast('Opening new tab...');
  // Pass current terminal dimensions so the new PTY starts at the correct size
  const activeState = sessionStates.get(activeSessionId);
  let rows = 24, cols = 80;
  if (activeState?.activePaneId) {
    const p = activeState.panes.get(activeState.activePaneId);
    if (p) { rows = p.term.rows || 24; cols = p.term.cols || 80; }
  }
  try {
    const res = await fetch('/api/sessions', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path, rows, cols }),
    });
    const data = await res.json();
    if (data.error) { showToast('Error: ' + data.error); return; }
    await loadSessions();
    if (!sessionStates.has(data.session_id)) {
      showToast('Failed to register new session', true);
      return;
    }
    switchTab(data.session_id);
  } catch(e) {
    showToast('Failed to open new tab');
  }
}

document.getElementById('projectPathInput').addEventListener('keydown', e => {
  if (e.key === 'Enter') confirmProjectSwitch();
  if (e.key === 'Escape') closeProjectPicker();
});

// ─── Pane keyboard shortcuts ─────────────────────────────────────────────────
// Ctrl+\          → split active pane right
// Ctrl+|          → split active pane down  (Ctrl+Shift+\)
// Ctrl+Shift+X    → close active pane
// Ctrl+Shift+←/→/↑/↓ → navigate panes
document.addEventListener('keydown', (e) => {
  // Don't fire shortcuts when typing in input/textarea
  if (['INPUT', 'TEXTAREA'].includes(e.target.tagName)) return;

  // Skip if xterm terminal has focus (canvas inside .xterm container)
  const xtermEl = document.querySelector('.xterm-helper-textarea');
  if (xtermEl && (document.activeElement === xtermEl || xtermEl.contains(document.activeElement))) return;

  // Ctrl+\ → split active pane right
  if (e.ctrlKey && !e.shiftKey && e.key === '\\') {
    e.preventDefault();
    if (typeof PaneManager !== 'undefined') PaneManager.splitActive('h');
    return;
  }

  // Ctrl+| (Ctrl+Shift+\) → split active pane down
  // NOTE: Ctrl+- was avoided because it conflicts with browser zoom-out
  if (e.ctrlKey && e.shiftKey && e.key === '|') {
    e.preventDefault();
    if (typeof PaneManager !== 'undefined') PaneManager.splitActive('v');
    return;
  }

  // Ctrl+Shift+X → close active pane (only when more than 1 pane exists)
  // NOTE: Ctrl+Shift+W was avoided because it closes the browser window
  if (e.ctrlKey && e.shiftKey && e.key === 'X') {
    e.preventDefault();
    if (typeof PaneManager !== 'undefined' && PaneManager.panes.size > 1) {
      PaneManager.removePane(PaneManager.activePaneId);
    }
    return;
  }

  // Ctrl+Shift+Arrow → navigate between panes
  if (e.ctrlKey && e.shiftKey) {
    const dirMap = { ArrowLeft: 'left', ArrowRight: 'right', ArrowUp: 'up', ArrowDown: 'down' };
    const dir = dirMap[e.key];
    if (dir) {
      e.preventDefault();
      if (typeof PaneManager !== 'undefined') PaneManager.focusNeighbor(dir);
    }
  }

  // Escape → close settings panel if open
  if (e.key === 'Escape') {
    const panel = document.getElementById('settingsPanel');
    if (panel && panel.style.display !== 'none') toggleSettings();
  }
});

// Close settings panel on click outside
document.addEventListener('click', (e) => {
  const panel = document.getElementById('settingsPanel');
  if (!panel || panel.style.display === 'none') return;
  const btn = document.querySelector('[onclick="toggleSettings()"]');
  if (!panel.contains(e.target) && (!btn || !btn.contains(e.target))) toggleSettings();
});

// Show which project is loaded
refreshProjectBadge();

// Poll sessions list every 5 seconds to keep badges current
setInterval(() => loadSessions(), 5000);

// ─── Mode switching ───────────────────────────────────────────────────────────
let currentMode = 'plan';
let _lastSchedule = null;  // cache for scheduler display on mode switch
let _overviewInterval = null;

function setMode(mode) {
  currentMode = mode;
  const main = document.querySelector('.main');
  main.classList.toggle('plan-mode', mode === 'plan');
  main.classList.toggle('execute-mode', mode === 'execute');
  main.classList.toggle('ideas-mode', mode === 'ideas');
  document.getElementById('modePlanBtn').classList.toggle('active', mode === 'plan');
  document.getElementById('modeExecBtn').classList.toggle('active', mode === 'execute');
  document.getElementById('modeIdeasBtn').classList.toggle('active', mode === 'ideas');
  // Ideas panel visibility
  const ideasPanel = document.getElementById('ideasPanel');
  if (ideasPanel) ideasPanel.style.display = mode === 'ideas' ? 'flex' : 'none';
  const intervBtn = document.getElementById('interveneBtn');
  if (intervBtn) intervBtn.style.display = mode === 'execute' ? '' : 'none';
  if (mode === 'plan') {
    closeIntervene();
    requestAnimationFrame(() => PaneManager.fitAll());
    clearInterval(_overviewInterval);
    _overviewInterval = null;
  }
  if (mode === 'execute') {
    document.getElementById('proposedOverlay')?.classList.add('hidden');
    renderOverview();
    if (!_overviewInterval) _overviewInterval = setInterval(renderOverview, 8000);
  }
  if (mode === 'ideas' && typeof loadIdeas === 'function') {
    loadIdeas();
  }
  // Sync scheduler bar + loop bar visibility with mode
  updateSchedulerDisplay(_lastSchedule);
  const loopBar = document.getElementById('loopBar');
  if (loopBar) loopBar.style.display = mode === 'execute' ? '' : 'none';
  if (mode === 'execute') { applyLoopPrefs(); loadLoopSources(); }
  const swarmBar = document.getElementById('swarmBar');
  if (swarmBar) swarmBar.style.display = mode === 'execute' ? '' : 'none';
  const bb = document.getElementById('broadcastBar');
  if (bb) bb.style.display = mode === 'execute' ? 'flex' : 'none';
  // Deferred section: only visible in execute mode when there are items
  if (mode !== 'execute') {
    const deferredSection = document.getElementById('deferredSection');
    if (deferredSection) deferredSection.style.display = 'none';
  }
  localStorage.setItem('orchestrator_mode', mode);
}
// Restore mode on load (or default to plan)
setMode(localStorage.getItem('orchestrator_mode') || 'plan');

// ─── Orchestrate button ───────────────────────────────────────────────────────
async function sendOrchestrate() {
  const goal = document.getElementById('goalInput').value.trim();
  const st = sessionStates.get(activeSessionId);
  if (!st || !st.activePaneId) return;
  const pane = st.panes.get(st.activePaneId);
  if (!pane || !pane.ws || pane.ws.readyState !== WebSocket.OPEN) return;
  if (!goal) return;

  // Save goal + PROGRESS.md context to file first, then send a single /orchestrate\r.
  // Previously two rapid PTY sends (goal text + /orchestrate) caused a race:
  // Claude started responding to the goal message before /orchestrate arrived,
  // leaving /orchestrate queued and requiring a second manual Enter.
  try {
    const resp = await fetch(`/api/sessions/${activeSessionId}/set-orchestrate-goal`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ goal })
    });
    if (!resp.ok) {
      console.warn(`set-orchestrate-goal failed (${resp.status}): falling back to direct goal input`);
      // Fallback: type goal + /orchestrate directly (pre-file-bridge approach)
      pane.ws.send(JSON.stringify({ type: 'input', data: goal + '\r' }));
      pane.ws.send(JSON.stringify({ type: 'input', data: '/orchestrate\r' }));
      pane.term.scrollToBottom();
      document.getElementById('goalInput').value = '';
      return;
    }
  } catch (_) { /* non-fatal: skill will ask for goal interactively */ }

  // Single PTY send — no race condition, no second Enter needed
  pane.ws.send(JSON.stringify({ type: 'input', data: '/orchestrate\r' }));
  pane.term.scrollToBottom();
  document.getElementById('goalInput').value = '';
}
document.getElementById('goalInput')?.addEventListener('keydown', e => {
  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendOrchestrate(); }
});

// ─── Intervene panel ──────────────────────────────────────────────────────────
let _intervenedSessionId = null;
function openIntervene() {
  if (_intervenedSessionId != null && _intervenedSessionId !== activeSessionId) closeIntervene();
  _intervenedSessionId = activeSessionId;
  document.getElementById('intervenePanel').classList.add('open');
  const st = sessionStates.get(activeSessionId);
  if (st) {
    const interveneTerm = document.getElementById('interveneTerminal');
    interveneTerm.appendChild(st.el);
    st.el.style.display = 'flex';
    requestAnimationFrame(() => PaneManager.fitSession(activeSessionId));
  }
}
function closeIntervene() {
  const sid = _intervenedSessionId || activeSessionId;
  document.getElementById('intervenePanel').classList.remove('open');
  const st = sessionStates.get(sid);
  if (!st || !st.el) { _intervenedSessionId = null; return; }
  const container = document.getElementById('terminalContainer');
  if (st && container) {
    container.appendChild(st.el);
    if (currentMode === 'plan') st.el.style.display = 'flex';
    requestAnimationFrame(() => PaneManager.fitSession(sid));
  }
  _intervenedSessionId = null;
}

// ─── Merge All Done → AI PR Pipeline ─────────────────────────────────────────
async function mergeAllDone() {
  const btn = document.getElementById('mergeAllBtn');
  if (btn) { btn.disabled = true; btn.textContent = '⏳ Creating PRs…'; }
  try {
    const r = await fetch(`/api/tasks/merge-all-done?session=${activeSessionId}`, { method: 'POST' });
    const d = await r.json();
    if (d.created === 0) {
      showToast('No eligible workers (need: done + pushed + no PR yet)');
    } else {
      const autoMsg = d.merged > 0 ? `, ${d.merged} auto-merged` : '';
      showToast(`Created ${d.created} PR${d.created !== 1 ? 's' : ''}${autoMsg}`);
    }
    // Surface any per-worker errors
    (d.results || []).filter(r => r.error).forEach(r => {
      console.warn(`Worker ${r.worker_id} PR error:`, r.error);
    });
  } catch (e) {
    showToast('PR creation failed — check console');
    console.error(e);
  } finally {
    if (btn) btn.disabled = false;
  }
}

// ─── Broadcast / Agents.md ────────────────────────────────────────────────────

async function broadcastAll() {
  const msg = document.getElementById('broadcastInput')?.value?.trim();
  if (!msg) return;
  const sid = activeSessionId;
  const btn = document.getElementById('broadcastBtn');
  if (btn) btn.disabled = true;
  try {
    const r = await fetch(`/api/sessions/${sid}/workers/broadcast`, {
      method: 'POST', headers: {'Content-Type':'application/json'},
      body: JSON.stringify({ message: msg }),
    });
    const d = await r.json();
    showToast(d.count > 0 ? `Broadcast sent to ${d.count} worker${d.count!==1?'s':''}` : 'No running workers');
    if (d.count > 0) document.getElementById('broadcastInput').value = '';
  } catch(e) { showToast('Error: ' + e.message); }
  finally { if (btn) btn.disabled = false; }
}

async function generateAgentsMd() {
  const sid = activeSessionId;
  if (!sid) { showToast('No active session'); return; }
  try {
    const r = await fetch(`/api/sessions/${sid}/agents-md`);
    const d = await r.json();
    if (d.agents_md) {
      try { await navigator.clipboard.writeText(d.agents_md); showToast('AGENTS.md copied to clipboard'); }
      catch { console.log('AGENTS.md:\n', d.agents_md); showToast('AGENTS.md generated (see console)'); }
    }
  } catch { showToast('Error generating AGENTS.md'); }
}

