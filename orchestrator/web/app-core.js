// ─── State ──────────────────────────────────────────────────────────────────
let activeWorkerId = null;
let workers = [];
let queue = [];
let sessions = [];
let activeSessionId = null;

// Per-session state: each session gets its own status WebSocket
const sessionStates = new Map();
// sessionId → { statusWs }

// ─── Per-session state ──────────────────────────────────────────────────────

function createSessionState(sessionId) {
  const state = { statusWs: null };
  sessionStates.set(sessionId, state);
  return state;
}

function destroySessionState(sessionId) {
  const state = sessionStates.get(sessionId);
  if (!state) return;
  if (state.statusWs) { state.statusWs.onclose = null; state.statusWs.close(); }
  sessionStates.delete(sessionId);
}

// ─── WebSocket: Status (per session) ─────────────────────────────────────────
function connectStatus(sessionId) {
  const state = sessionStates.get(sessionId);
  if (!state) return;
  const wsProto = location.protocol === 'https:' ? 'wss' : 'ws';
  const url = `${wsProto}://${location.host}/ws/status?session=${sessionId}`;
  const ws = new WebSocket(url);
  state.statusWs = ws;

  ws.onmessage = (e) => {
    let msg;
    try { msg = JSON.parse(e.data); } catch { return; }
    if (msg.type === 'status') updateDashboard(msg);
    else if ((msg.type === 'idea_update' || msg.type === 'idea_message') && window._ideaWsHandler) {
      window._ideaWsHandler(msg);
    }
    else if (msg.type === 'proposed_tasks') {
      if (msg.content && msg.content.includes('===TASK===')) {
        window._lastProposedContent = msg.content;
        const autoStart = document.getElementById('settingAutoStart')?.checked;
        if (autoStart) {
          fetch(`/api/tasks/import-proposed?session=${sessionId}`, { method: 'POST',
            headers: {'Content-Type':'application/json'},
            body: JSON.stringify({ content: msg.content })
          }).then(r => { if (!r.ok) throw new Error(`Import failed: ${r.status}`); })
            .then(() => fetch(`/api/tasks/start-all?session=${sessionId}`, { method: 'POST' }))
            .then(r => { if (!r.ok) throw new Error(`Start-all failed: ${r.status}`); return r.json(); })
            .then(d => {
              showToast(`Auto-started ${d.started} worker${d.started !== 1 ? 's' : ''}`);
            })
            .catch(err => showToast(`Auto-start failed: ${err.message}`, true));
        } else {
          showProposedOverlay(msg.content);
        }
      }
    }
  };
  ws.onopen = () => {
    if (sessionId === activeSessionId) {
      setOrchStatus('connected', 'Orchestrator active');
    }
  };
  ws.onclose = () => setTimeout(() => {
    if (sessionStates.has(sessionId)) connectStatus(sessionId);
  }, 2000);
  ws.onerror = () => {
    ws.onclose = null;
    if (sessionId === activeSessionId) setOrchStatus('disconnected', 'Connection error');
    setTimeout(() => {
      if (sessionStates.has(sessionId)) connectStatus(sessionId);
    }, 3000);
  };
}

// Keep-alive ping for all sessions
setInterval(() => {
  for (const state of sessionStates.values()) {
    if (state.statusWs && state.statusWs.readyState === WebSocket.OPEN) state.statusWs.send('ping');
  }
}, 20000);

// ─── Tab management ──────────────────────────────────────────────────────────
async function loadSessions() {
  try {
    const res = await fetch('/api/sessions');
    if (!res.ok) return;
    sessions = await res.json();
    if (sessions.length > 0 && !activeSessionId) {
      activeSessionId = sessions[0].session_id;
    }
    for (const s of sessions) {
      if (!sessionStates.has(s.session_id)) {
        createSessionState(s.session_id);
        connectStatus(s.session_id);
        if (s.session_id === activeSessionId) {
          setOrchStatus('connecting', 'Connecting...');
        }
      }
    }
    for (const [sid] of sessionStates) {
      if (!sessions.find(s => s.session_id === sid)) destroySessionState(sid);
    }
    renderTabs();
  } catch(e) { console.warn(e); }
}

function renderTabs() {
  const bar = document.getElementById('tabBar');
  const addBtn = bar.querySelector('.tab-add');
  bar.querySelectorAll('.tab').forEach(t => t.remove());
  sessions.forEach(s => {
    const isActive = s.session_id === activeSessionId;
    const badge = s.running_count > 0
      ? `<span class="tab-badge">${s.running_count}</span>`
      : (s.worker_count > 0 ? `<span class="tab-badge idle">${s.worker_count}</span>` : '');
    const showClose = sessions.length > 1;
    const div = document.createElement('div');
    div.className = 'tab' + (isActive ? ' active' : '');
    div.innerHTML = `<span class="tab-name">${esc(s.name)}</span>${badge}${showClose ? `<span class="tab-close" data-sid="${esc(s.session_id)}">×</span>` : ''}`;
    div.querySelector('.tab-close')?.addEventListener('click', e => { e.stopPropagation(); closeTab(s.session_id); });
    div.addEventListener('click', () => switchTab(s.session_id));
    bar.insertBefore(div, addBtn);
  });
}

async function switchTab(sessionId) {
  if (sessionId === activeSessionId) return;

  if (_logRefreshInterval) {
    clearInterval(_logRefreshInterval);
    _logRefreshInterval = null;
  }
  _historyExpanded = false;

  activeSessionId = sessionId;
  renderTabs();

  // Update connection status
  const newState = sessionStates.get(sessionId);
  if (newState?.statusWs?.readyState === WebSocket.OPEN) {
    setOrchStatus('connected', 'Orchestrator active');
  } else {
    setOrchStatus('connecting', 'Connecting...');
  }
  refreshProjectBadge();
  loadIdeas();
}

async function closeTab(sessionId) {
  if (!confirm('Close this project tab?')) return;
  try {
    const res = await fetch(`/api/sessions/${sessionId}`, { method: 'DELETE' });
    if (!res.ok) { showToast('Failed to close tab', true); return; }
  } catch (e) { showToast('Error closing tab: ' + e.message, true); return; }
  destroySessionState(sessionId);
  if (activeSessionId === sessionId) activeSessionId = null;
  await loadSessions();
}

function openNewTabPicker() { openProjectPicker(); }
