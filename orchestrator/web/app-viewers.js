// ─── Worker Log viewer ────────────────────────────────────────────────────────
let activeLogWorkerId = null;
let _logRefreshInterval = null;

async function openWorkerLog(id, name) {
  activeLogWorkerId = id;
  const displayName = decodeHtml(name);
  document.getElementById('workerLogTitle').textContent = `#${id} — ${displayName}`;
  document.getElementById('workerLogModal').classList.remove('hidden');
  await refreshWorkerLog();
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
    if (!res.ok) { el.textContent = 'Error loading log.'; return; }
    const data = await res.json();
    el.textContent = data.log || '(empty log)';
    el.scrollTop = el.scrollHeight;
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
    if (!res.ok) { document.getElementById('workerLogContent').textContent = 'Error loading TLDR.'; return; }
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
    if (!res.ok) { document.getElementById('workerLogContent').textContent = 'Error loading interventions.'; return; }
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

document.getElementById('workerChatInput')?.addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && e.metaKey) sendWorkerMessage();
  if (e.key === 'Escape') closeWorkerChat();
});

// ─── Proposed Tasks Overlay ──────────────────────────────────────────────────
function showProposedOverlay(content) {
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
    if (!res.ok) { showToast('Retry request failed', true); return; }
    const data = await res.json();
    if (data.ok) showToast('Task reset to pending — will auto-start');
    else showToast(data.error || 'Retry failed');
  } catch(e) { showToast('Error: ' + e.message); }
}

// ─── Task History (done/failed) ───────────────────────────────────────────────
let _lastSuccessRate;
let _historyExpanded = false;

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

  if (!section.open) return;

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
    if (!res.ok) throw new Error('API error');
    const d = await res.json();
    const paceEl = document.getElementById('usagePace');
    const detailEl = document.getElementById('usageDetail');
    if (d.pace) {
      const sign = d.pace.delta >= 0 ? '+' : '';
      paceEl.textContent = `${d.pace.symbol} ${sign}${d.pace.delta}% (${d.pace.remaining})`;
    } else {
      paceEl.textContent = '';
    }
    const today = d.today || {};
    const week = d.this_week || {};
    detailEl.textContent = `Today: ${today.messages||0} msgs · Week: ${week.messages||0} msgs`;
  } catch(e) {
    const detailEl = document.getElementById('usageDetail');
    if (detailEl) detailEl.textContent = 'Usage unavailable';
  }
}

// ─── Boot ────────────────────────────────────────────────────────────────────
loadSessions();
refreshUsage();
loadIdeas();
setInterval(refreshUsage, 60000);

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
    if (!res.ok) throw new Error('API error');
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
  try {
    const res = await fetch('/api/sessions', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path }),
    });
    if (!res.ok) { showToast('Failed to create session', true); return; }
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

// ─── Keyboard shortcuts ──────────────────────────────────────────────────────
document.addEventListener('keydown', (e) => {
  if (['INPUT', 'TEXTAREA'].includes(e.target.tagName)) return;
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

// ─── Init ────────────────────────────────────────────────────────────────────
let _lastSchedule = null;

// ─── Merge All Done → AI PR Pipeline ─────────────────────────────────────────
async function mergeAllDone() {
  const btn = document.getElementById('mergeAllBtn');
  if (btn) { btn.disabled = true; btn.textContent = '⏳ Creating PRs…'; }
  try {
    const r = await fetch(`/api/tasks/merge-all-done?session=${activeSessionId}`, { method: 'POST' });
    if (!r.ok) { showToast('PR creation failed', true); return; }
    const d = await r.json();
    if (d.created === 0) {
      showToast('No eligible workers (need: done + pushed + no PR yet)');
    } else {
      const autoMsg = d.merged > 0 ? `, ${d.merged} auto-merged` : '';
      showToast(`Created ${d.created} PR${d.created !== 1 ? 's' : ''}${autoMsg}`);
    }
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

async function generateAgentsMd() {
  const sid = activeSessionId;
  if (!sid) { showToast('No active session'); return; }
  try {
    const r = await fetch(`/api/sessions/${sid}/agents-md`);
    if (!r.ok) { showToast('Error generating AGENTS.md', true); return; }
    const d = await r.json();
    if (d.agents_md) {
      try { await navigator.clipboard.writeText(d.agents_md); showToast('AGENTS.md copied to clipboard'); }
      catch { console.log('AGENTS.md:\n', d.agents_md); showToast('AGENTS.md generated (see console)'); }
    }
  } catch { showToast('Error generating AGENTS.md'); }
}

// ─── Settings ─────────────────────────────────────────────────────────────────

async function loadSettings() {
  try {
    const r = await fetch('/api/settings');
    if (!r.ok) throw new Error('API error');
    const s = await r.json();
    const elAutoStart = document.getElementById('settingAutoStart');
    const elAutoPush = document.getElementById('settingAutoPush');
    const elAutoMerge = document.getElementById('settingAutoMerge');
    const elAutoReview = document.getElementById('settingAutoReview');
    const elModel = document.getElementById('settingModel');
    const elMaxW = document.getElementById('settingMaxWorkers');
    if (elAutoStart) elAutoStart.checked = s.auto_start ?? true;
    if (elAutoPush) elAutoPush.checked = s.auto_push ?? true;
    if (elAutoMerge) elAutoMerge.checked = s.auto_merge ?? true;
    if (elAutoReview) elAutoReview.checked = s.auto_review ?? true;
    if (elModel) elModel.value = s.default_model ?? 'sonnet';
    if (elMaxW) elMaxW.value = s.max_workers ?? 0;
    const elAutoScale = document.getElementById('settingAutoScale');
    const elMinW = document.getElementById('settingMinWorkers');
    if (elAutoScale) elAutoScale.checked = s.auto_scale ?? false;
    if (elMinW) elMinW.value = s.min_workers ?? 1;
    const elLoopModel = document.getElementById('settingLoopModel');
    const elLoopK = document.getElementById('settingLoopK');
    const elLoopN = document.getElementById('settingLoopN');
    const elLoopMax = document.getElementById('settingLoopMax');
    if (elLoopModel) elLoopModel.value = s.loop_supervisor_model ?? 'sonnet';
    if (elLoopK) elLoopK.value = s.loop_convergence_k ?? 2;
    if (elLoopN) elLoopN.value = s.loop_convergence_n ?? 3;
    if (elLoopMax) elLoopMax.value = s.loop_max_iterations ?? 20;
    const elAutoOracle = document.getElementById('settingAutoOracle');
    const elAutoMR = document.getElementById('settingAutoModelRouting');
    const elCtxBudget = document.getElementById('settingContextBudget');
    if (elAutoOracle) elAutoOracle.checked = s.auto_oracle ?? false;
    if (elAutoMR) elAutoMR.checked = s.auto_model_routing ?? false;
    if (elCtxBudget) elCtxBudget.checked = s.context_budget_warning ?? true;
    const elStuck = document.getElementById('settingStuckTimeout');
    if (elStuck) elStuck.value = s.stuck_timeout_minutes ?? 15;
    const elBudget = document.getElementById('settingCostBudget');
    if (elBudget) elBudget.value = s.cost_budget ?? 0;
    const elAgentTeams = document.getElementById('settingAgentTeams');
    if (elAgentTeams) elAgentTeams.checked = s.agent_teams ?? false;
    const elGhSync = document.getElementById('settingGhSync');
    const elGhLabel = document.getElementById('settingGhLabel');
    if (elGhSync) elGhSync.checked = s.github_issues_sync ?? false;
    if (elGhLabel) elGhLabel.value = s.github_issues_label ?? 'orchestrator';
    const elWebhook = document.getElementById('settingWebhook');
    if (elWebhook) elWebhook.value = s.notification_webhook ?? '';
    const elPatrolSched = document.getElementById('settingPatrolSchedule');
    const elResearchSched = document.getElementById('settingResearchSchedule');
    if (elPatrolSched) elPatrolSched.value = s.patrol_schedule ?? '';
    if (elResearchSched) elResearchSched.value = s.research_schedule ?? '';
    const syncBtn = document.getElementById('ghSyncBtn');
    if (syncBtn) syncBtn.style.display = s.github_issues_sync ? '' : 'none';
    // Load intervention count
    try {
      const ivRes = await fetch(`/api/interventions?session=${activeSessionId}`);
      if (!ivRes.ok) throw new Error('API error');
      const ivData = await ivRes.json();
      const ivBadge = document.getElementById('interventionCount');
      if (ivBadge && ivData.length > 0) {
        ivBadge.textContent = ivData.length;
        ivBadge.style.display = '';
      }
    } catch(e) { console.warn(e); }
  } catch(e) { console.warn(e); }
}

let _saveSettingsTimer = null;
function saveSettings() {
  clearTimeout(_saveSettingsTimer);
  _saveSettingsTimer = setTimeout(async () => {
    try {
      await fetch('/api/settings', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
          auto_start: document.getElementById('settingAutoStart')?.checked ?? true,
          auto_push: document.getElementById('settingAutoPush')?.checked ?? true,
          auto_merge: document.getElementById('settingAutoMerge')?.checked ?? true,
          auto_review: document.getElementById('settingAutoReview')?.checked ?? true,
          default_model: document.getElementById('settingModel')?.value ?? 'sonnet',
          max_workers: parseInt(document.getElementById('settingMaxWorkers')?.value) || 0,
          auto_scale: document.getElementById('settingAutoScale')?.checked ?? false,
          min_workers: parseInt(document.getElementById('settingMinWorkers')?.value) || 1,
          loop_supervisor_model: document.getElementById('settingLoopModel')?.value ?? 'sonnet',
          loop_convergence_k: parseInt(document.getElementById('settingLoopK')?.value) || 2,
          loop_convergence_n: parseInt(document.getElementById('settingLoopN')?.value) || 3,
          loop_max_iterations: parseInt(document.getElementById('settingLoopMax')?.value) || 20,
          auto_oracle: document.getElementById('settingAutoOracle')?.checked ?? false,
          auto_model_routing: document.getElementById('settingAutoModelRouting')?.checked ?? false,
          context_budget_warning: document.getElementById('settingContextBudget')?.checked ?? true,
          stuck_timeout_minutes: parseInt(document.getElementById('settingStuckTimeout')?.value) || 0,
          cost_budget: parseFloat(document.getElementById('settingCostBudget')?.value) || 0,
          agent_teams: document.getElementById('settingAgentTeams')?.checked ?? false,
          github_issues_sync: document.getElementById('settingGhSync')?.checked ?? false,
          github_issues_label: document.getElementById('settingGhLabel')?.value || 'orchestrator',
          notification_webhook: document.getElementById('settingWebhook')?.value || '',
          patrol_schedule: document.getElementById('settingPatrolSchedule')?.value || '',
          research_schedule: document.getElementById('settingResearchSchedule')?.value || '',
        }),
      });
      const syncBtn = document.getElementById('ghSyncBtn');
      if (syncBtn) syncBtn.style.display = document.getElementById('settingGhSync')?.checked ? '' : 'none';
    } catch(e) { console.warn(e); }
  }, 400);
}

function toggleSettings() {
  const panel = document.getElementById('settingsPanel');
  if (!panel) return;
  const isOpen = panel.style.display !== 'none';
  panel.style.display = isOpen ? 'none' : '';
  if (!isOpen) loadSettings();
}

// ─── GitHub Issues Sync ───────────────────────────────────────────────────────

async function ghSync() {
  const btn = document.getElementById('ghSyncBtn');
  if (btn) { btn.disabled = true; btn.textContent = '⇅ Syncing...'; }
  try {
    const pullR = await fetch(`/api/issues/sync-pull?session=${activeSessionId}`, { method: 'POST' });
    if (!pullR.ok) { showToast('Sync pull failed', true); return; }
    const pull = await pullR.json();
    const pushR = await fetch(`/api/issues/sync-push?session=${activeSessionId}`, { method: 'POST' });
    if (!pushR.ok) { showToast('Sync push failed', true); return; }
    const push = await pushR.json();
    const parts = [];
    if (pull.created) parts.push(`+${pull.created} from GitHub`);
    if (pull.updated) parts.push(`${pull.updated} updated`);
    if (pull.deleted) parts.push(`${pull.deleted} removed`);
    if (push.created) parts.push(`${push.created} pushed`);
    if (push.updated) parts.push(`${push.updated} synced`);
    showToast(parts.length ? 'Sync: ' + parts.join(', ') : 'Sync complete — no changes');
  } catch (e) {
    showToast('Sync failed: ' + e.message);
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = '⇅ Sync'; }
  }
}

// ─── Portfolio Panel ──────────────────────────────────────────────────────────

let portfolioInterval = null;

function togglePortfolio() {
  const panel = document.getElementById('portfolioPanel');
  if (!panel) return;
  const visible = panel.style.display !== 'none';
  panel.style.display = visible ? 'none' : 'block';
  if (!visible) {
    updatePortfolio();
    portfolioInterval = setInterval(updatePortfolio, 5000);
  } else {
    clearInterval(portfolioInterval);
    portfolioInterval = null;
  }
}

async function updatePortfolio() {
  try {
    const resp = await fetch('/api/sessions/overview');
    if (!resp.ok) return;
    const sessionsData = await resp.json();
    if (sessionsData.length < 2) {
      const btnContainer = document.getElementById('portfolioBtnContainer');
      if (btnContainer) btnContainer.style.display = 'none';
      return;
    }
    const btnContainer = document.getElementById('portfolioBtnContainer');
    if (btnContainer) btnContainer.style.display = '';
  } catch (e) { /* fail silently */ }
}

// Load settings on boot
loadSettings();
