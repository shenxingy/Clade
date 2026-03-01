// ─── State ──────────────────────────────────────────────────────────────────
let activeWorkerId = null;
let workers = [];
let queue = [];
let sessions = [];
let activeSessionId = null;

// Per-session state: each session gets its own terminal + WebSocket pair
// so switching tabs only hides/shows — nothing is ever disconnected.
const sessionStates = new Map();
// sessionId → { statusWs, el, panes: Map, activePaneId, opened }

// ─── Per-session terminal helpers ────────────────────────────────────────────
const TERM_THEME = {
  background: '#1E1B16', foreground: '#E8E0D4',
  cursor: '#C15F3C', selectionBackground: 'rgba(193,95,60,0.3)',
  black: '#1E1B16', brightBlack: '#5C554A',
  red: '#C0534A',   brightRed: '#D4756D',
  green: '#5A9A4F', brightGreen: '#7AB86E',
  yellow: '#C49A3C', brightYellow: '#D4B35C',
  blue: '#7A9EC2',  brightBlue: '#9BB8D4',
  magenta: '#9B7EC8', brightMagenta: '#B89FD8',
  cyan: '#5BA8A8',  brightCyan: '#7AC0C0',
  white: '#B5ADA3', brightWhite: '#F0EDE8',
};

// ─── PaneManager ─────────────────────────────────────────────────────────────
// Manages split panes within the active session's terminal container.
// Each session (in sessionStates) owns a panes Map; PaneManager operates
// on whichever session is currently active.
const PaneManager = {
  // Proxy to active session's pane map
  get panes() {
    const st = sessionStates.get(activeSessionId);
    return st ? st.panes : new Map();
  },
  get activePaneId() {
    const st = sessionStates.get(activeSessionId);
    return st ? st.activePaneId : null;
  },

  _nextId() { return 'pane-' + Math.random().toString(36).slice(2, 7); },

  // Create a new pane inside `container`, belonging to `sessionId`.
  createPane(container, sessionId) {
    const sid = sessionId || activeSessionId;
    const st = sessionStates.get(sid);
    if (!st) return null;

    const id = this._nextId();

    const wrapper = document.createElement('div');
    wrapper.className = 'pane-wrapper';
    wrapper.style.cssText = 'flex:1;display:flex;flex-direction:column;min-width:0;min-height:0;overflow:hidden;position:relative;';
    wrapper.dataset.paneId = id;
    wrapper.addEventListener('click', () => {
      if (activeSessionId === sid) this.setActive(id);
    });

    const term = new Terminal({
      theme: TERM_THEME,
      fontFamily: "'SF Mono', 'Fira Code', 'Cascadia Code', monospace",
      fontSize: 13, lineHeight: 1.4, cursorBlink: true,
      scrollback: 5000, allowTransparency: false,
    });
    const fitAddon = new FitAddon.FitAddon();
    term.loadAddon(fitAddon);
    term.open(wrapper);

    const pane = { id, term, fitAddon, ws: null, element: wrapper, sessionId: sid };
    st.panes.set(id, pane);

    term.onData(data => {
      const activeSt = sessionStates.get(activeSessionId);
      if (activeSt && activeSt.activePaneId === id &&
          pane.ws && pane.ws.readyState === WebSocket.OPEN) {
        pane.ws.send(JSON.stringify({ type: 'input', data }));
      }
    });

    container.appendChild(wrapper);
    setTimeout(() => { try { fitAddon.fit(); } catch(e) { console.warn(e); } }, 50);
    this.connectPaneWs(sid, id);
    return id;
  },

  connectPaneWs(sessionId, paneId) {
    const st = sessionStates.get(sessionId);
    if (!st) return;
    const pane = st.panes.get(paneId);
    if (!pane) return;

    // Close any existing connection cleanly before replacing
    if (pane.ws) { pane.ws.onclose = null; pane.ws.close(); }

    const wsProto = location.protocol === 'https:' ? 'wss' : 'ws';
    const url = `${wsProto}://${location.host}/ws/chat?session=${sessionId}`;
    const ws = new WebSocket(url);
    pane.ws = ws;

    ws.onopen = () => {
      const isActive = sessionId === activeSessionId;
      const st2 = sessionStates.get(sessionId);
      if (isActive && st2 && st2.activePaneId === paneId) {
        setOrchStatus('connected', 'Orchestrator active');
      }
      ws.send(JSON.stringify({ type: 'resize', rows: pane.term.rows, cols: pane.term.cols }));
    };
    ws.onmessage = (e) => {
      try {
        const msg = JSON.parse(e.data);
        if (msg.type === 'output') { pane.term.write(msg.data); pane.term.scrollToBottom(); }
      } catch(e) { console.warn(e); }
    };
    ws.onclose = () => {
      if (pane._reconnecting) return;
      pane._reconnecting = true;
      const isActive = sessionId === activeSessionId;
      const st2 = sessionStates.get(sessionId);
      if (isActive && st2 && st2.activePaneId === paneId) {
        setOrchStatus('disconnected', 'Disconnected');
        pane.term.write('\r\n\x1b[33m[Reconnecting...]\x1b[0m\r\n');
      }
      setTimeout(() => {
        pane._reconnecting = false;
        const curr = sessionStates.get(sessionId);
        if (curr && curr.panes.has(paneId)) {
          this.connectPaneWs(sessionId, paneId);
        }
      }, 2000);
    };
    ws.onerror = () => {
      if (sessionId === activeSessionId) setOrchStatus('disconnected', 'Connection error');
    };
  },

  setActive(paneId) {
    const st = sessionStates.get(activeSessionId);
    if (!st) return;
    st.activePaneId = paneId;
    st.panes.forEach((p, pid) => {
      p.element.style.outline = pid === paneId
        ? '2px solid var(--accent)'
        : '1px solid transparent';
    });
    const pane = st.panes.get(paneId);
    if (pane && pane.ws && pane.ws.readyState === WebSocket.OPEN) {
      setOrchStatus('connected', 'Orchestrator active');
    }
  },

  splitActive(direction) {
    const st = sessionStates.get(activeSessionId);
    if (!st || !st.activePaneId) return;
    const pane = st.panes.get(st.activePaneId);
    if (!pane) return;

    const oldWrapper = pane.element;
    const parent = oldWrapper.parentElement;

    const splitContainer = document.createElement('div');
    splitContainer.style.cssText = [
      'flex:1;display:flex;min-width:0;min-height:0;overflow:hidden;gap:2px;',
      direction === 'h' ? 'flex-direction:row;' : 'flex-direction:column;',
    ].join('');

    parent.replaceChild(splitContainer, oldWrapper);
    splitContainer.appendChild(oldWrapper);
    oldWrapper.style.flex = '1';

    const newId = this.createPane(splitContainer, activeSessionId);
    setTimeout(() => {
      this.fitSession(activeSessionId);
      if (newId) this.setActive(newId);
    }, 100);
  },

  removePane(paneId) {
    const st = sessionStates.get(activeSessionId);
    if (!st || st.panes.size <= 1) return;
    const pane = st.panes.get(paneId);
    if (!pane) return;

    if (pane.ws) { pane.ws.onclose = null; pane.ws.close(); }
    pane.term.dispose();

    const wrapper = pane.element;
    const splitContainer = wrapper.parentElement;
    st.panes.delete(paneId);

    if (splitContainer && splitContainer !== st.el) {
      const sibling = [...splitContainer.children].find(c => c !== wrapper);
      if (sibling) {
        const grandParent = splitContainer.parentElement;
        sibling.style.flex = splitContainer.style.flex || '1';
        grandParent.replaceChild(sibling, splitContainer);
      }
    } else {
      wrapper.remove();
    }

    const firstId = [...st.panes.keys()][0];
    if (firstId) this.setActive(firstId);
    if (st.panes.size > 0) this.fitSession(activeSessionId);
  },

  focusNeighbor(dir) {
    const st = sessionStates.get(activeSessionId);
    if (!st) return;
    const ids = [...st.panes.keys()];
    const idx = ids.indexOf(st.activePaneId);
    if (idx === -1) return;
    const next = (dir === 'right' || dir === 'down')
      ? ids[(idx + 1) % ids.length]
      : ids[(idx - 1 + ids.length) % ids.length];
    this.setActive(next);
  },

  fitSession(sessionId) {
    const st = sessionStates.get(sessionId);
    if (!st || !st.opened) return;
    st.panes.forEach(p => {
      try { p.fitAddon.fit(); } catch(e) { console.warn(e); }
      if (p.ws && p.ws.readyState === WebSocket.OPEN) {
        p.ws.send(JSON.stringify({ type: 'resize', rows: p.term.rows, cols: p.term.cols }));
      }
    });
  },

  fitAll() { this.fitSession(activeSessionId); },
};

function createSessionState(sessionId) {
  // Each session gets its own absolutely-positioned flex container for its panes
  const el = document.createElement('div');
  el.id = `term-${sessionId}`;
  el.style.cssText = 'position:absolute;inset:0;display:none;flex-direction:row;';
  document.getElementById('terminalContainer').appendChild(el);

  const state = {
    statusWs: null,
    el,
    panes: new Map(),      // paneId → pane object (managed by PaneManager)
    activePaneId: null,
    opened: false,         // true after first pane created
  };
  sessionStates.set(sessionId, state);
  return state;
}

function showSessionTerminal(sessionId) {
  const state = sessionStates.get(sessionId);
  if (!state) return;
  state.el.style.display = 'flex';
  // Create the first pane on first show (element must be visible for correct sizing)
  if (!state.opened) {
    state.opened = true;
    const firstId = PaneManager.createPane(state.el, sessionId);
    if (firstId) PaneManager.setActive(firstId);
  }
  // Use rAF to let the DOM settle before fitting
  requestAnimationFrame(() => PaneManager.fitSession(sessionId));
}

function destroySessionState(sessionId) {
  const state = sessionStates.get(sessionId);
  if (!state) return;
  // Dispose all panes for this session
  state.panes.forEach(pane => {
    if (pane.ws) { pane.ws.onclose = null; pane.ws.close(); }
    pane.term.dispose();
  });
  state.panes.clear();
  if (state.statusWs) { state.statusWs.onclose = null; state.statusWs.close(); }
  state.el.remove();
  sessionStates.delete(sessionId);
}

// ─── WebSocket: Chat ──────────────────────────────────────────────────────────
// Per-pane connections are managed by PaneManager.connectPaneWs().
// connectChat() is kept as a no-op so loadSessions() callers don't break.
function connectChat(sessionId) { /* handled by PaneManager per pane */ }

function sendChat() {
  const input = document.getElementById('chatInput');
  const text = input.value;
  if (!text.trim()) return;
  const st = sessionStates.get(activeSessionId);
  if (!st || !st.activePaneId) return;
  const pane = st.panes.get(st.activePaneId);
  if (!pane || !pane.ws || pane.ws.readyState !== WebSocket.OPEN) return;
  pane.ws.send(JSON.stringify({ type: 'input', data: text + '\r' }));
  pane.term.scrollToBottom();
  input.value = '';
}

document.getElementById('chatInput').addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendChat(); }
});

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
    else if (msg.type === 'proposed_tasks') {
      if (msg.content && msg.content.includes('===TASK===')) {
        window._lastProposedContent = msg.content;
        const autoStart = document.getElementById('autoStartToggle')?.checked;
        if (autoStart) {
          // Auto-mode: import + start immediately, no overlay
          fetch(`/api/tasks/import-proposed?session=${sessionId}`, { method: 'POST',
            headers: {'Content-Type':'application/json'},
            body: JSON.stringify({ content: msg.content })
          }).then(r => { if (!r.ok) throw new Error(`Import failed: ${r.status}`); })
            .then(() => fetch(`/api/tasks/start-all?session=${sessionId}`, { method: 'POST' }))
            .then(r => { if (!r.ok) throw new Error(`Start-all failed: ${r.status}`); return r.json(); })
            .then(d => {
              if (sessionId === activeSessionId) setMode('execute');
              showToast(`Auto-started ${d.started} worker${d.started !== 1 ? 's' : ''}`);
            })
            .catch(err => showToast(`Auto-start failed: ${err.message}`, true));
        } else {
          showProposedOverlay(msg.content);
        }
      }
    }
  };
  ws.onclose = () => setTimeout(() => {
    if (sessionStates.has(sessionId)) connectStatus(sessionId);
  }, 2000);
  ws.onerror = () => {
    // Prevent double reconnect (onerror + onclose both fire)
    ws.onclose = null;
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

// ─── Window resize — fit all panes in the active session ─────────────────────
function fitAndSync() { PaneManager.fitAll(); }
window.addEventListener('resize', fitAndSync);

// ─── Tab management ──────────────────────────────────────────────────────────
async function loadSessions() {
  try {
    const res = await fetch('/api/sessions');
    if (!res.ok) return;
    sessions = await res.json();
    if (sessions.length > 0 && !activeSessionId) {
      activeSessionId = sessions[0].session_id;
    }
    // Create state + connect WS for any session we don't know about yet
    for (const s of sessions) {
      if (!sessionStates.has(s.session_id)) {
        createSessionState(s.session_id);
        connectChat(s.session_id);
        connectStatus(s.session_id);
        if (s.session_id === activeSessionId) {
          showSessionTerminal(s.session_id);
          setOrchStatus('connecting', 'Connecting...');
        }
      }
    }
    // Clean up states for sessions deleted on the server
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

  // Hide current session's terminal — keep its WS alive
  const oldState = sessionStates.get(activeSessionId);
  if (oldState) oldState.el.style.display = 'none';

  activeSessionId = sessionId;
  renderTabs();

  // Reload loop prefs/sources for the new session (execute mode only)
  if (currentMode === 'execute') { applyLoopPrefs(); loadLoopSources(); }

  // Show (lazily open if first visit) the new session's terminal
  showSessionTerminal(sessionId);

  // Update connection status dot from active pane
  const newState = sessionStates.get(sessionId);
  const activePaneId = newState?.activePaneId;
  const activePane = activePaneId ? newState.panes.get(activePaneId) : null;
  if (activePane?.ws?.readyState === WebSocket.OPEN) {
    setOrchStatus('connected', 'Orchestrator active');
  } else {
    setOrchStatus('connecting', 'Connecting...');
  }
  refreshProjectBadge();
  renderOverview();
}

async function closeTab(sessionId) {
  if (!confirm('Close this project tab?')) return;
  await fetch(`/api/sessions/${sessionId}`, { method: 'DELETE' });
  destroySessionState(sessionId);
  if (activeSessionId === sessionId) activeSessionId = null;
  await loadSessions();
  if (activeSessionId) showSessionTerminal(activeSessionId);
}

function openNewTabPicker() { openProjectPicker(); }

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
    mergeBtn.style.display = mergeable.length > 0 && currentMode === 'execute' ? '' : 'none';
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
  document.getElementById('modePlanBtn').classList.toggle('active', mode === 'plan');
  document.getElementById('modeExecBtn').classList.toggle('active', mode === 'execute');
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

// ─── Iteration Loop ───────────────────────────────────────────────────────────

let _loopConvergedToasted = false;
let _loopPreset = 'review'; // active preset key

const LOOP_PRESETS = {
  review: { mode: 'review',      k: 3, n: 6,  label: 'Review Fix' },
  build:  { mode: 'plan_build',  k: 2, n: 10, label: 'Plan+Build' },
  polish: { mode: 'review',      k: 4, n: 8,  label: 'Polish'     },
};

function selectLoopPreset(preset) {
  _loopPreset = preset;
  document.querySelectorAll('.loop-preset-card').forEach(c => {
    c.classList.toggle('active', c.dataset.preset === preset);
  });
  // Reset K/N to preset defaults (intentional — clicking a card resets parameters)
  const cfg = LOOP_PRESETS[preset] || LOOP_PRESETS.review;
  const kEl = document.getElementById('loopK');
  const nEl = document.getElementById('loopN');
  if (kEl) kEl.value = cfg.k;
  if (nEl) nEl.value = cfg.n;
  // Save preset+K/N but preserve current source (select may not be populated yet)
  _saveLoopPrefsPreserveSource();
}

function toggleLoopAdvanced() {
  const adv = document.getElementById('loopAdvanced');
  if (adv) adv.style.display = adv.style.display === 'none' ? '' : 'none';
}

async function loadLoopSources() {
  if (!activeSessionId) return;
  const sel = document.getElementById('loopSourceSelect');
  const customIn = document.getElementById('loopSourceCustom');
  if (!sel) return;
  try {
    const r = await fetch(`/api/sessions/${activeSessionId}/loop/sources`);
    if (!r.ok) return;
    const sources = await r.json();
    const saved = loadLoopPrefs()?.source || '';
    sel.innerHTML = '<option value="">— select file —</option>' +
      sources.map(s => `<option value="${esc(s.path)}"${s.path === saved ? ' selected' : ''}>${esc(s.label)}</option>`).join('');
    // No auto-detected sources → show custom input instead
    if (sources.length === 0) {
      sel.style.display = 'none';
      if (customIn) { customIn.style.display = ''; customIn.value = saved; }
    } else {
      sel.style.display = '';
      if (customIn) customIn.style.display = 'none';
      // Auto-select best candidate if nothing saved
      if (!saved) { sel.value = sources[0].path; saveLoopPrefs(); }
    }
  } catch(e) { /* ignore */ }
}

function onLoopSourceChange() {
  saveLoopPrefs();
}

function _loopPrefsKey() {
  return `loop-pref-${activeSessionId || 'default'}`;
}

function loadLoopPrefs() {
  try {
    const raw = localStorage.getItem(_loopPrefsKey());
    return raw ? JSON.parse(raw) : null;
  } catch(e) { return null; }
}

function _getLoopSource() {
  const sel = document.getElementById('loopSourceSelect');
  const customIn = document.getElementById('loopSourceCustom');
  if (customIn && customIn.style.display !== 'none') return customIn.value.trim();
  const hasOptions = sel && sel.options.length > 1;
  return hasOptions ? (sel.value || '') : (loadLoopPrefs()?.source || '');
}

function saveLoopPrefs() {
  try {
    const source = _getLoopSource();
    const prefs = {
      preset: _loopPreset,
      source,
      advanced: {
        k: parseInt(document.getElementById('loopK')?.value) || 3,
        n: parseInt(document.getElementById('loopN')?.value) || 6,
        model: document.getElementById('loopAdvModel')?.value || 'sonnet',
        contextDir: document.getElementById('loopContextDir')?.value || '',
      },
    };
    localStorage.setItem(_loopPrefsKey(), JSON.stringify(prefs));
  } catch(e) { /* ignore */ }
}

function _saveLoopPrefsPreserveSource() {
  saveLoopPrefs(); // saveLoopPrefs already preserves source when unpopulated
}

function applyLoopPrefs() {
  const prefs = loadLoopPrefs();
  if (!prefs) return;
  if (prefs.preset && LOOP_PRESETS[prefs.preset]) {
    selectLoopPreset(prefs.preset);
  }
  if (prefs.advanced) {
    const { k, n, model, contextDir } = prefs.advanced;
    if (k) { const el = document.getElementById('loopK'); if (el) el.value = k; }
    if (n) { const el = document.getElementById('loopN'); if (el) el.value = n; }
    if (model) { const el = document.getElementById('loopAdvModel'); if (el) el.value = model; }
    if (contextDir) { const el = document.getElementById('loopContextDir'); if (el) el.value = contextDir; }
  }
  // source is restored in loadLoopSources after options are populated
}

async function startLoop() {
  if (!activeSessionId) return;
  const artifactPath = _getLoopSource();
  if (!artifactPath) { showToast('Select or enter a source file first'); return; }
  const contextDir = document.getElementById('loopContextDir')?.value.trim() || null;
  const cfg = LOOP_PRESETS[_loopPreset] || LOOP_PRESETS.review;
  const k = parseInt(document.getElementById('loopK')?.value) || cfg.k;
  const n = parseInt(document.getElementById('loopN')?.value) || cfg.n;
  const model = document.getElementById('loopAdvModel')?.value || document.getElementById('settingLoopModel')?.value || 'sonnet';
  const btn = document.getElementById('loopStartBtn');
  if (btn) btn.disabled = true;
  try {
    const r = await fetch(`/api/sessions/${activeSessionId}/loop/start`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        artifact_path: artifactPath,
        context_dir: contextDir,
        convergence_k: k,
        convergence_n: n,
        mode: cfg.mode,
        max_iterations: parseInt(document.getElementById('settingLoopMax')?.value) || 20,
        supervisor_model: model,
      }),
    });
    if (!r.ok) {
      const d = await r.json().catch(() => ({}));
      showToast('Error: ' + (d.detail || r.statusText));
      return;
    }
    saveLoopPrefs();
    _loopConvergedToasted = false;
    showToast(`Loop started — ${cfg.label} · Iteration 1`);
  } catch(e) { showToast('Failed to start loop'); }
  finally { if (btn) btn.disabled = false; }
}

async function pauseLoop() {
  if (!activeSessionId) return;
  try {
    const r = await fetch(`/api/sessions/${activeSessionId}/loop/pause`, { method: 'POST' });
    if (!r.ok) { showToast('Pause failed'); return; }
    showToast('Loop paused — current workers will finish');
  } catch(e) { showToast('Pause failed'); }
}

async function resumeLoop() {
  if (!activeSessionId) return;
  try {
    const r = await fetch(`/api/sessions/${activeSessionId}/loop/resume`, { method: 'POST' });
    if (!r.ok) { showToast('Resume failed'); return; }
    showToast('Loop resumed');
  } catch(e) { showToast('Resume failed'); }
}

async function cancelLoop() {
  if (!activeSessionId) return;
  try {
    const r = await fetch(`/api/sessions/${activeSessionId}/loop`, { method: 'DELETE' });
    if (!r.ok) { showToast('Cancel failed'); return; }
    _loopConvergedToasted = false;
    showToast('Loop cancelled');
  } catch(e) { showToast('Cancel failed'); }
}

function drawSparkline(canvas, values) {
  if (!canvas) return;
  const ctx = canvas.getContext('2d');
  const w = canvas.width, h = canvas.height;
  ctx.clearRect(0, 0, w, h);
  if (!values || values.length === 0) return;
  // Normalize: entries may be int or {count, hash}
  const counts = values.map(v => typeof v === 'object' ? (v.count || 0) : v);
  const max = Math.max(...counts, 1);
  const barW = Math.max(3, Math.floor(w / (counts.length + 1)));
  const gap = 2;
  counts.forEach((v, i) => {
    const barH = Math.max(2, Math.round((v / max) * (h - 2)));
    const x = i * (barW + gap);
    const y = h - barH;
    ctx.fillStyle = v === 0 ? cssVar('--green') : cssVar('--accent');
    ctx.fillRect(x, y, barW, barH);
  });
}

function updateLoopUI(loopState) {
  const badge = document.getElementById('loopStatusBadge');
  const configPanel = document.getElementById('loopConfigPanel');
  const runningPanel = document.getElementById('loopRunningPanel');
  const pauseBtn = document.getElementById('loopPauseBtn');
  const resumeBtn = document.getElementById('loopResumeBtn');
  const cancelBtn = document.getElementById('loopCancelBtn');
  const iterLabel = document.getElementById('loopIterLabel');
  const convergenceLabel = document.getElementById('loopConvergence');
  const sparkCanvas = document.getElementById('loopSparkline');
  const runningPresetLabel = document.getElementById('loopRunningPreset');
  const deferredSection = document.getElementById('deferredSection');
  const deferredCount = document.getElementById('deferredCount');
  const deferredList = document.getElementById('deferredList');

  if (!badge) return;

  const status = (loopState && loopState.status) ? loopState.status : 'idle';
  const isRunning = status === 'running';
  const isPaused = status === 'paused';
  const isActive = isRunning || isPaused;
  const isConverged = status === 'converged';
  // Post-active: states that may have deferred items and need full rendering
  const isPostActive = isConverged || status === 'done' || status === 'cancelled';
  // Idle: truly no loop has run, nothing to show
  const isIdle = !isActive && !isPostActive;

  badge.textContent = status;
  badge.className = 'badge ' + status;

  // Panel visibility: running panel shown only while actively running/paused
  if (configPanel) configPanel.style.display = isActive ? 'none' : '';
  if (runningPanel) runningPanel.style.display = isActive ? '' : 'none';

  if (isIdle) {
    if (deferredSection) deferredSection.style.display = 'none';
    return;
  }

  // Running / paused / converged state
  if (pauseBtn) pauseBtn.style.display = isRunning ? '' : 'none';
  if (resumeBtn) resumeBtn.style.display = isPaused ? '' : 'none';
  if (cancelBtn) cancelBtn.style.display = isActive ? '' : 'none';

  // Preset label in running bar (infer from loop mode)
  if (runningPresetLabel && loopState) {
    const modeMap = { review: 'Review Fix', plan_build: 'Plan+Build' };
    // Try to match stored preset label
    const storedPreset = loadLoopPrefs()?.preset;
    const presetLabel = (storedPreset && LOOP_PRESETS[storedPreset])
      ? LOOP_PRESETS[storedPreset].label
      : (modeMap[loopState.mode] || loopState.mode || '');
    runningPresetLabel.textContent = presetLabel;
  }

  if (iterLabel && loopState) {
    iterLabel.textContent = `Iter ${loopState.iteration || 0}`;
  }

  // Convergence text
  if (convergenceLabel && loopState) {
    const hist = loopState.changes_history || [];
    const k = loopState.convergence_k || 3;
    const n = loopState.convergence_n || 6;
    const entries = hist.map(e => typeof e === 'object' ? e : {count: e, hash: ''});
    if (isConverged) {
      let reason = 'count';
      if (entries.length >= 2 && entries[entries.length-1].hash && entries[entries.length-1].hash === entries[entries.length-2].hash) {
        reason = 'semantic';
      } else if ((loopState.iteration || 0) >= (loopState.max_iterations || 20)) {
        reason = 'max_iterations';
      }
      convergenceLabel.textContent = `Converged after ${loopState.iteration} iters (${reason})`;
      convergenceLabel.style.color = 'var(--green)';
    } else if (entries.length > 0) {
      const recent = entries.slice(-n);
      const withinThreshold = recent.filter(e => e.count <= k).length;
      convergenceLabel.textContent = `${withinThreshold}/${n} ≤${k}`;
      convergenceLabel.style.color = 'var(--text2)';
    } else {
      convergenceLabel.textContent = '';
    }
  }

  drawSparkline(sparkCanvas, (loopState && loopState.changes_history) || []);

  // Convergence toast (one-shot)
  if (isConverged && !_loopConvergedToasted) {
    _loopConvergedToasted = true;
    showToast('✓ Loop converged — ready for human review');
    if (deferredSection && (loopState.deferred_items || []).length > 0) {
      deferredSection.open = true;
    }
    // Panel visibility is already set correctly above (configPanel shown, runningPanel hidden)
  }
  if (!isConverged) _loopConvergedToasted = false;

  // Deferred items
  const deferred = (loopState && loopState.deferred_items) || [];
  if (deferredSection && currentMode === 'execute') {
    deferredSection.style.display = deferred.length > 0 ? '' : 'none';
    if (deferredCount) deferredCount.textContent = deferred.length;
    if (deferredList) {
      deferredList.innerHTML = deferred.map(item => `
        <div class="deferred-item">
          <div class="deferred-iter">[Loop-${esc(String(item.iteration ?? '?'))}]</div>
          <div class="deferred-desc">${esc(item.description)}</div>
          ${item.reason ? `<div class="deferred-reason">${esc(item.reason)}</div>` : ''}
        </div>
      `).join('');
    }
  }
}

// ─── Swarm ────────────────────────────────────────────────────────────────────

let _swarmCompleteToasted = false;

async function startSwarm() {
  if (!activeSessionId) return;
  const btn = document.getElementById('swarmStartBtn');
  if (btn) btn.disabled = true;
  try {
    const slots = parseInt(document.getElementById('swarmSlots').value) || 3;
    const r = await fetch(`/api/sessions/${activeSessionId}/swarm/start`, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ slots }),
    });
    if (!r.ok) {
      const data = await r.json().catch(() => ({}));
      showToast(data.detail || 'Failed to start swarm', true);
    }
  } catch (e) {
    showToast('Swarm start failed: ' + e.message, true);
  } finally {
    if (btn) btn.disabled = false;
  }
}

async function stopSwarm() {
  if (!activeSessionId) return;
  try {
    const res = await fetch(`/api/sessions/${activeSessionId}/swarm/stop`, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ force: false }),
    });
    if (!res.ok) showToast('Failed to stop swarm', true);
  } catch (e) {
    showToast('Swarm stop failed: ' + e.message, true);
  }
}

async function forceStopSwarm() {
  if (!activeSessionId) return;
  try {
    const res = await fetch(`/api/sessions/${activeSessionId}/swarm/stop`, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ force: true }),
    });
    if (!res.ok) showToast('Failed to force-stop swarm', true);
  } catch (e) {
    showToast('Swarm force stop failed: ' + e.message, true);
  }
}

async function resizeSwarm() {
  if (!activeSessionId) return;
  try {
    const slots = parseInt(document.getElementById('swarmSlots').value) || 3;
    const r = await fetch(`/api/sessions/${activeSessionId}/swarm/resize`, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ slots }),
    });
    const data = await r.json();
    if (data.error) {
      showToast(data.error, true);
    } else {
      const si = document.getElementById('swarmSlots');
      if (si) si._userEdited = false;
    }
  } catch (e) {
    showToast('Swarm resize failed: ' + e.message, true);
  }
}

function _fmtElapsed(s) {
  const m = Math.floor(s / 60);
  const sec = s % 60;
  return m > 0 ? `${m}m ${sec}s` : `${sec}s`;
}

function updateSwarmUI(swarmState) {
  const badge = document.getElementById('swarmStatusBadge');
  const startBtn = document.getElementById('swarmStartBtn');
  const stopBtn = document.getElementById('swarmStopBtn');
  const forceStopBtn = document.getElementById('swarmForceStopBtn');
  const resizeBtn = document.getElementById('swarmResizeBtn');
  const progress = document.getElementById('swarmProgress');
  const metrics = document.getElementById('swarmMetrics');
  const elapsed = document.getElementById('swarmElapsed');
  const slotsInput = document.getElementById('swarmSlots');

  if (!badge) return;

  if (!swarmState || swarmState.status === 'idle') {
    badge.textContent = 'idle';
    badge.className = 'badge idle';
    if (startBtn) startBtn.style.display = '';
    if (stopBtn) stopBtn.style.display = 'none';
    if (forceStopBtn) forceStopBtn.style.display = 'none';
    if (resizeBtn) resizeBtn.style.display = 'none';
    if (progress) progress.style.display = 'none';
    if (slotsInput) { slotsInput.disabled = false; slotsInput._userEdited = false; }
    _swarmCompleteToasted = false;
    return;
  }

  const status = swarmState.status;
  badge.textContent = status;
  badge.className = 'badge ' + status;

  const isActive = status === 'active';
  const isDraining = status === 'draining';
  const isTerminal = status === 'done' || status === 'stopped';

  if (startBtn) startBtn.style.display = (isActive || isDraining) ? 'none' : '';
  if (stopBtn) stopBtn.style.display = isActive ? '' : 'none';
  if (forceStopBtn) forceStopBtn.style.display = (isActive || isDraining) ? '' : 'none';
  if (resizeBtn) resizeBtn.style.display = isActive ? '' : 'none';
  if (slotsInput) {
    slotsInput.disabled = isDraining;
    if (swarmState.target_slots && !slotsInput._userEdited) {
      slotsInput.value = swarmState.target_slots;
    }
  }

  // Progress
  const stats = swarmState.stats || {};
  const running = swarmState.running || 0;
  const target = swarmState.target_slots || 0;
  if (progress && metrics) {
    progress.style.display = (isActive || isDraining || isTerminal) ? 'flex' : 'none';
    const parts = [`${running}/${target} slots`];
    if (stats.done > 0 || stats.failed > 0) {
      parts.push(`${stats.done} done`);
      if (stats.failed > 0) parts.push(`${stats.failed} failed`);
    }
    metrics.textContent = parts.join(' · ');
  }
  if (elapsed && swarmState.elapsed_s) {
    elapsed.textContent = _fmtElapsed(swarmState.elapsed_s);
  }

  // Completion toast
  if (isTerminal && !_swarmCompleteToasted) {
    _swarmCompleteToasted = true;
    const reason = swarmState.done_reason || status;
    showToast(`Swarm ${status}: ${reason}`);
  }
  if (!isTerminal) _swarmCompleteToasted = false;
}

// ─── Analytics ─────────────────────────────────────────────────────────────────

function _modelColor(model) { return { haiku: cssVar('--green'), sonnet: cssVar('--accent'), opus: cssVar('--purple') }[model] || cssVar('--text2'); }

async function renderAnalytics() {
  if (!activeSessionId) return;
  try {
    const r = await fetch(`/api/sessions/${activeSessionId}/analytics`);
    const d = await r.json();
    const section = document.getElementById('analyticsSection');
    if (!section) return;
    if (d.total === 0) { section.style.display = 'none'; return; }
    section.style.display = '';

    const costBadge = document.getElementById('analyticsCostBadge');
    if (costBadge) costBadge.textContent = d.total_cost > 0 ? `$${d.total_cost.toFixed(4)}` : '';

    const summary = document.getElementById('analyticsSummary');
    if (summary) {
      summary.innerHTML = `
        <div style="display:flex;gap:12px;flex-wrap:wrap;font-size:11px;line-height:1.6">
          <span>Total: <b>${d.total}</b></span>
          <span style="color:var(--green)">Done: <b>${d.done}</b></span>
          <span style="color:var(--red)">Failed: <b>${d.failed}</b></span>
          ${d.interrupted ? `<span style="color:var(--yellow)">Interrupted: <b>${d.interrupted}</b></span>` : ''}
          <span>Rate: <b>${d.success_rate}%</b></span>
        </div>
        ${d.total_cost > 0 ? `<div style="font-size:11px;margin-top:4px;color:var(--text2)">Cost: <b style="color:var(--text)">$${d.total_cost.toFixed(4)}</b> &middot; Tokens: ${(d.total_input_tokens/1000).toFixed(1)}K in / ${(d.total_output_tokens/1000).toFixed(1)}K out</div>` : ''}`;
    }

    const modelsEl = document.getElementById('analyticsModels');
    if (modelsEl && Object.keys(d.model_stats).length > 0) {
      modelsEl.innerHTML = Object.entries(d.model_stats).map(([m, s]) => {
        const c = _modelColor(m);
        return `<div style="font-size:10px;color:var(--text2);margin-top:2px">
          <span style="color:${c};font-weight:600">${m}</span>:
          ${s.count} tasks, ${s.done} done, avg ${Math.round(s.avg_elapsed_s)}s
          ${s.total_cost > 0 ? `, $${s.total_cost.toFixed(4)}` : ''}
        </div>`;
      }).join('');
    }

    // Donut chart
    const entries = Object.entries(d.model_stats).filter(([,s]) => s.count > 0);
    if (entries.length > 0) drawDonut(entries);
  } catch(e) { console.warn(e); }
}

function drawDonut(entries) {
  const canvas = document.getElementById('analyticsDonut');
  if (!canvas) return;
  const ctx = canvas.getContext('2d');
  const w = canvas.width, h = canvas.height;
  ctx.clearRect(0, 0, w, h);
  const cx = w / 2, cy = h / 2, r = 32, inner = 18;
  const total = entries.reduce((s, [, v]) => s + v.count, 0);
  let angle = -Math.PI / 2;
  for (const [model, stats] of entries) {
    const slice = (stats.count / total) * Math.PI * 2;
    ctx.beginPath();
    ctx.arc(cx, cy, r, angle, angle + slice);
    ctx.arc(cx, cy, inner, angle + slice, angle, true);
    ctx.closePath();
    ctx.fillStyle = _modelColor(model);
    ctx.fill();
    angle += slice;
  }
}

setInterval(renderAnalytics, 10000);

// ─── Settings ─────────────────────────────────────────────────────────────────

async function loadSettings() {
  try {
    const r = await fetch('/api/settings');
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
    // Loop settings
    const elLoopModel = document.getElementById('settingLoopModel');
    const elLoopK = document.getElementById('settingLoopK');
    const elLoopN = document.getElementById('settingLoopN');
    const elLoopMax = document.getElementById('settingLoopMax');
    if (elLoopModel) elLoopModel.value = s.loop_supervisor_model ?? 'sonnet';
    if (elLoopK) elLoopK.value = s.loop_convergence_k ?? 2;
    if (elLoopN) elLoopN.value = s.loop_convergence_n ?? 3;
    if (elLoopMax) elLoopMax.value = s.loop_max_iterations ?? 20;
    // Sync loop inputs from settings defaults
    const loopK = document.getElementById('loopK');
    const loopN = document.getElementById('loopN');
    if (loopK && !loopK._userEdited) loopK.value = s.loop_convergence_k ?? 2;
    if (loopN && !loopN._userEdited) loopN.value = s.loop_convergence_n ?? 3;
    // Sync autoStartToggle in chat header
    const ast = document.getElementById('autoStartToggle');
    if (ast) ast.checked = s.auto_start ?? true;
    // Quality gate settings
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
    // Agent Teams
    const elAgentTeams = document.getElementById('settingAgentTeams');
    if (elAgentTeams) elAgentTeams.checked = s.agent_teams ?? false;
    // GitHub Issues sync
    const elGhSync = document.getElementById('settingGhSync');
    const elGhLabel = document.getElementById('settingGhLabel');
    if (elGhSync) elGhSync.checked = s.github_issues_sync ?? false;
    if (elGhLabel) elGhLabel.value = s.github_issues_label ?? 'orchestrator';
    const elWebhook = document.getElementById('settingWebhook');
    if (elWebhook) elWebhook.value = s.notification_webhook ?? '';
    // Show/hide sync button based on setting
    const syncBtn = document.getElementById('ghSyncBtn');
    if (syncBtn) syncBtn.style.display = s.github_issues_sync ? '' : 'none';
    // Load intervention count
    try {
      const ivRes = await fetch(`/api/interventions?session=${activeSessionId}`);
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
        }),
      });
      // Update sync button visibility
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
    const pull = await pullR.json();
    const pushR = await fetch(`/api/issues/sync-push?session=${activeSessionId}`, { method: 'POST' });
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

// ─── Multi-project Overview ────────────────────────────────────────────────────

async function renderOverview() {
  if (currentMode !== 'execute') return;
  try {
    const r = await fetch('/api/sessions/overview');
    const overviewData = await r.json();
    const section = document.getElementById('overviewSection');
    const list = document.getElementById('overviewList');
    if (!section || !list) return;
    section.style.display = overviewData.length > 1 ? '' : 'none';
    list.innerHTML = overviewData.map(s => {
      const total = s.done + s.failed + s.running + s.pending;
      const pct = total > 0 ? Math.round((s.done + s.failed) / total * 100) : 0;
      const eta = s.eta_seconds
        ? (s.eta_seconds < 60 ? '<1m' : `~${Math.round(s.eta_seconds / 60)}m`)
        : '';
      const isActive = s.session_id === activeSessionId;
      return `<div class="overview-row ${isActive ? 'active' : ''}" onclick="switchTab('${esc(s.session_id)}')">
        <span class="proj-name">${esc(s.name)}</span>
        <div class="proj-bar"><div class="proj-bar-fill" style="width:${pct}%"></div></div>
        <span class="proj-counts">${s.running > 0 ? `${s.running} run · ` : ''}${s.done}✓ · ${s.failed}✗</span>
        <span class="proj-eta">${eta}</span>
      </div>`;
    }).join('');
  } catch(e) { console.warn(e); }
}

async function startAllQueued() {
  try {
    const r = await fetch('/api/sessions/start-all-queued', { method: 'POST' });
    const d = await r.json();
    showToast(`Started ${d.total_started} worker${d.total_started !== 1 ? 's' : ''} across ${d.sessions.length} project${d.sessions.length !== 1 ? 's' : ''}`);
    renderOverview();
  } catch(e) {
    showToast('Failed to start workers');
  }
}

// ─── DAG View ─────────────────────────────────────────────────────────────────

let dagVisible = false;
let dagSelectedTask = null;

function toggleDag() {
  dagVisible = !dagVisible;
  const dagView = document.getElementById('dagView');
  const queueList = document.getElementById('queueList');
  const dagBtn = document.getElementById('dagBtn');
  if (!dagView || !queueList) return;

  dagView.style.display = dagVisible ? '' : 'none';
  queueList.style.display = dagVisible ? 'none' : '';
  if (dagBtn) dagBtn.classList.toggle('dag-active', dagVisible);

  if (dagVisible) renderDag();
}

function renderDag() {
  if (!dagVisible) return;
  const dagView = document.getElementById('dagView');
  if (!dagView) return;

  const tasks = queue;
  if (!tasks || tasks.length === 0) {
    dagView.innerHTML = '<div style="padding:20px;color:var(--text2);text-align:center;font-size:12px">No tasks in queue</div>';
    return;
  }

  // Compute levels via topological sort
  const taskMap = Object.fromEntries(tasks.map(t => [t.id, t]));
  const levels = {};

  function getLevel(id, visiting = new Set()) {
    if (levels[id] !== undefined) return levels[id];
    if (visiting.has(id)) return 0; // cycle guard
    visiting.add(id);
    const task = taskMap[id];
    if (!task || !(task.depends_on || []).length) {
      levels[id] = 0;
    } else {
      levels[id] = Math.max(...task.depends_on.map(dep => getLevel(dep, new Set(visiting)))) + 1;
    }
    return levels[id];
  }
  tasks.forEach(t => getLevel(t.id));

  // Group by level
  const levelGroups = {};
  tasks.forEach(t => {
    const lv = levels[t.id] ?? 0;
    if (!levelGroups[lv]) levelGroups[lv] = [];
    levelGroups[lv].push(t);
  });

  const nodeW = 148, nodeH = 34, hGap = 60, vGap = 10;
  const padX = 12, padY = 12;
  const colW = nodeW + hGap;
  const rowH = nodeH + vGap;
  const lvKeys = Object.keys(levelGroups);
  const maxLevel = lvKeys.length > 0 ? Math.max(...lvKeys.map(Number)) : 0;
  const lvVals = Object.values(levelGroups);
  const maxRows = lvVals.length > 0 ? Math.max(...lvVals.map(v => v.length)) : 1;
  const svgW = (maxLevel + 1) * colW + padX * 2;
  const svgH = Math.max(maxRows * rowH + padY * 2, 80);

  // Assign node positions
  const pos = {};
  for (const [lv, lvTasks] of Object.entries(levelGroups)) {
    const x = padX + Number(lv) * colW;
    lvTasks.forEach((t, i) => { pos[t.id] = { x, y: padY + i * rowH }; });
  }

  const STATUS_COLOR = {
    done: cssVar('--green'), running: cssVar('--accent'), failed: cssVar('--red'),
    paused: cssVar('--yellow'), blocked: cssVar('--yellow'), pending: cssVar('--text2'), queued: cssVar('--text2'),
  };
  const doneIds = new Set(tasks.filter(t => t.status === 'done').map(t => t.id));

  let edges = '';
  let nodes = '';

  // Draw edges
  tasks.forEach(t => {
    (t.depends_on || []).forEach(depId => {
      const f = pos[depId], to = pos[t.id];
      if (!f || !to) return;
      const x1 = f.x + nodeW, y1 = f.y + nodeH / 2;
      const x2 = to.x, y2 = to.y + nodeH / 2;
      const mx = (x1 + x2) / 2;
      const done = doneIds.has(depId);
      edges += `<path d="M${x1},${y1} C${mx},${y1} ${mx},${y2} ${x2},${y2}"
        fill="none" stroke="${done ? cssVar('--green') : cssVar('--border')}" stroke-width="1.5"
        marker-end="url(#${done ? 'arrowGreen' : 'arrowGray'})" />`;
    });
  });

  // Draw nodes
  tasks.forEach(t => {
    const p = pos[t.id];
    if (!p) return;
    const isSelected = dagSelectedTask === t.id;
    const isBlocked = (t.depends_on || []).some(dep => !doneIds.has(dep));
    const stroke = isSelected ? cssVar('--accent') : isBlocked ? cssVar('--yellow') : cssVar('--border');
    const strokeW = isSelected ? 2 : 1;
    const dot = STATUS_COLOR[t.status] || cssVar('--text2');
    const label = esc(firstLine(t.description).slice(0, 17));
    const suffix = firstLine(t.description).length > 17 ? '…' : '';
    nodes += `<g data-tid="${esc(t.id)}" onclick="dagClick(this.dataset.tid, event)" style="cursor:pointer" title="${esc(t.id)}: ${esc(firstLine(t.description))}">
      <rect x="${p.x}" y="${p.y}" width="${nodeW}" height="${nodeH}" rx="8"
        fill="${isSelected ? cssVar('--bg3') : cssVar('--bg2')}" stroke="${stroke}" stroke-width="${strokeW}" />
      <circle cx="${p.x + 10}" cy="${p.y + nodeH/2}" r="4" fill="${dot}" />
      <text x="${p.x + 20}" y="${p.y + nodeH/2 + 4}" fill="${cssVar('--text')}"
        font-size="11" font-family="'SF Mono','Fira Code',monospace">${label}${suffix}</text>
      <text x="${p.x + nodeW - 4}" y="${p.y + 11}" fill="${cssVar('--text2')}"
        font-size="9" text-anchor="end" font-family="sans-serif">${esc(t.id)}</text>
    </g>`;
  });

  const hintText = dagSelectedTask
    ? `Selected: ${dagSelectedTask} — Ctrl+click another task to add dependency`
    : 'Click to select · Ctrl+click to add dependency · Click selected again to deselect';

  dagView.innerHTML = `
    <svg xmlns="http://www.w3.org/2000/svg" width="${svgW}" height="${svgH}" style="display:block;min-width:${svgW}px">
      <defs>
        <marker id="arrowGray" markerWidth="7" markerHeight="5" refX="6" refY="2.5" orient="auto">
          <polygon points="0 0, 7 2.5, 0 5" fill="${cssVar('--border')}" />
        </marker>
        <marker id="arrowGreen" markerWidth="7" markerHeight="5" refX="6" refY="2.5" orient="auto">
          <polygon points="0 0, 7 2.5, 0 5" fill="${cssVar('--green')}" />
        </marker>
      </defs>
      ${edges}
      ${nodes}
    </svg>
    <div class="dag-hint">${hintText}</div>`;
}

async function dagClick(taskId, event) {
  if (event.ctrlKey && dagSelectedTask && dagSelectedTask !== taskId) {
    // Add dep: taskId depends on dagSelectedTask
    const task = queue.find(t => t.id === taskId);
    if (!task) return;
    const newDeps = [...new Set([...(task.depends_on || []), dagSelectedTask])];
    try {
      const sid = activeSessionId || '';
      await fetch(`/api/tasks/${taskId}/depends-on?session=${sid}`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ depends_on: newDeps }),
      });
      // Optimistic update
      task.depends_on = newDeps;
      showToast(`Set: "${taskId}" depends on "${dagSelectedTask}"`);
    } catch {
      showToast('Failed to update dependency');
    }
    dagSelectedTask = null;
  } else {
    dagSelectedTask = dagSelectedTask === taskId ? null : taskId;
  }
  renderDag();
}

loadSettings();
