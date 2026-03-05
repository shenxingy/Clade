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
    else if ((msg.type === 'idea_update' || msg.type === 'idea_message') && window._ideaWsHandler) {
      window._ideaWsHandler(msg);
    }
    else if (msg.type === 'suggested_goals') {
      showSuggestedGoals(msg.content, msg.session_id);
    }
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

  // Reload loop prefs/sources for the new session
  applyLoopPrefs();
  loadLoopSources();

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

