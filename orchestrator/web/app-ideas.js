// ─── Ideas (Inline Expandable Cards) ────────────────────────────────────────
// No separate sidebar — evaluation + chat expand inside each card.

let _ideas = [];
let _expandedIdeaId = null;

// ─── Load & Render ──────────────────────────────────────────────────────────

async function loadIdeas() {
  try {
    const res = await fetch(`/api/ideas?session=${activeSessionId}`);
    if (!res.ok) return;
    _ideas = await res.json();
    renderIdeasList();
  } catch (e) {
    console.warn('loadIdeas error:', e);
  }
}

function renderIdeasList() {
  const list = document.getElementById('ideasList');
  const countEl = document.getElementById('ideaCount');
  if (!list) return;
  if (countEl) countEl.textContent = `(${_ideas.length})`;

  if (_ideas.length === 0) {
    list.innerHTML = '<div class="empty">No ideas yet — start typing below</div>';
    return;
  }
  list.innerHTML = _ideas.map(idea => {
    const isExpanded = idea.id === _expandedIdeaId;
    const statusClass = idea.status || 'raw';
    const evalParsed = idea.ai_evaluation_parsed;
    const summary = evalParsed?.summary || '';
    const feasibility = evalParsed?.feasibility;
    const effort = evalParsed?.effort || '';
    const sourceTag = idea.source !== 'human' ? `<span class="idea-source">${esc(idea.source)}</span>` : '';
    const statusBadge = _ideaStatusBadge(idea.status);
    const effortBadge = effort ? `<span class="idea-effort">${esc(effort)}</span>` : '';
    const feasBar = feasibility ? _feasibilityBar(feasibility) : '';

    return `
      <div class="idea-card ${isExpanded ? 'expanded' : ''} ${esc(statusClass)}"
           data-idea-id="${idea.id}">
        <div class="idea-card-header" onclick="toggleIdea(${idea.id})">
          <div class="idea-card-top">
            ${statusBadge}
            ${sourceTag}
            ${effortBadge}
            <span class="idea-time">${_timeAgo(idea.created_at)}</span>
          </div>
          <div class="idea-content">${esc(idea.content)}</div>
          ${!isExpanded && summary ? `<div class="idea-summary">${esc(summary)}</div>` : ''}
          ${!isExpanded ? feasBar : ''}
        </div>
        <div class="idea-detail" id="idea-detail-${idea.id}">
          ${isExpanded ? '<div class="eval-loading">Loading...</div>' : ''}
        </div>
      </div>`;
  }).join('');

  // If an idea is expanded, fetch and render its details
  if (_expandedIdeaId) {
    _loadIdeaDetail(_expandedIdeaId);
  }
}

function _ideaStatusBadge(status) {
  const labels = {
    raw: 'New', evaluating: 'Evaluating...', evaluated: 'Evaluated',
    promoting: 'Promoting...', promoted: 'Promoted', archived: 'Archived',
    queued: 'Queued', executing: 'Executing...', done: 'Done',
  };
  return `<span class="badge ${esc(status)}">${labels[status] || esc(status)}</span>`;
}

function _feasibilityBar(score) {
  const pct = Math.min(100, (score / 5) * 100);
  const color = score >= 4 ? 'var(--green)' : score >= 3 ? 'var(--yellow)' : 'var(--red)';
  return `<div class="feas-bar"><div class="feas-fill" style="width:${pct}%;background:${color}"></div></div>`;
}

function _timeAgo(dateStr) {
  if (!dateStr) return '';
  const d = new Date(dateStr + (dateStr.includes('Z') ? '' : 'Z'));
  const diff = (Date.now() - d.getTime()) / 1000;
  if (diff < 60) return 'just now';
  if (diff < 3600) return Math.floor(diff / 60) + 'm ago';
  if (diff < 86400) return Math.floor(diff / 3600) + 'h ago';
  return Math.floor(diff / 86400) + 'd ago';
}

// ─── Toggle Expand / Collapse ───────────────────────────────────────────────

function toggleIdea(id) {
  if (_expandedIdeaId === id) {
    _expandedIdeaId = null;
    renderIdeasList();
  } else {
    _expandedIdeaId = id;
    renderIdeasList();
  }
}


async function _loadIdeaDetail(id) {
  const detail = document.getElementById(`idea-detail-${id}`);
  if (!detail) return;
  try {
    const res = await fetch(`/api/ideas/${id}?session=${activeSessionId}`);
    if (!res.ok) {
      detail.innerHTML = '<div class="empty">Failed to load idea</div>';
      return;
    }
    const idea = await res.json();
    _renderIdeaDetail(detail, idea);
  } catch (e) {
    console.warn('_loadIdeaDetail error:', e);
    detail.innerHTML = '<div class="empty">Failed to load idea</div>';
  }
}

function _renderIdeaDetail(detailEl, idea) {
  const evalData = idea.ai_evaluation_parsed;
  const isTerminal = idea.status === 'promoted' || idea.status === 'archived';

  if (!evalData || evalData.error) {
    const errorMsg = evalData?.error || '';
    const statusMsg = idea.status === 'evaluating'
      ? '<div class="eval-loading">Evaluating...</div>'
      : `<div class="empty">No evaluation yet${errorMsg ? ': ' + esc(errorMsg) : ''}</div>
         <button class="btn small" onclick="triggerEvaluate(${idea.id})" style="margin:8px 0;display:inline-block">Evaluate Now</button>`;

    detailEl.innerHTML = `
      ${statusMsg}
      ${!isTerminal ? _actionsHtml(idea.id, idea.status) : ''}
    `;
    _bindEvalInput(detailEl, idea.id);
    return;
  }

  const feasScore = evalData.feasibility || 0;
  const feasColor = feasScore >= 4 ? 'var(--green)' : feasScore >= 3 ? 'var(--yellow)' : 'var(--red)';
  const risks = (evalData.risks || []).map(r => `<li>${esc(r)}</li>`).join('');
  const alts = (evalData.alternatives || []).map(a => `<li>${esc(a)}</li>`).join('');
  const missing = (evalData.missing || []).map(m => `<li>${esc(m)}</li>`).join('');
  const messages = idea.messages || [];

  detailEl.innerHTML = `
    <div class="eval-summary">${esc(evalData.summary || '')}</div>
    <div class="eval-metrics">
      <div class="eval-metric">
        <span class="eval-metric-label">Feasibility</span>
        <span class="eval-metric-value" style="color:${feasColor}">${feasScore}/5</span>
      </div>
      <div class="eval-metric">
        <span class="eval-metric-label">Effort</span>
        <span class="eval-metric-value">${esc(evalData.effort || '?')}</span>
      </div>
    </div>
    ${risks ? `<div class="eval-section"><strong>Risks</strong><ul>${risks}</ul></div>` : ''}
    ${alts ? `<div class="eval-section"><strong>Alternatives</strong><ul>${alts}</ul></div>` : ''}
    ${missing ? `<div class="eval-section"><strong>Missing</strong><ul>${missing}</ul></div>` : ''}
    <div class="eval-chat">
      <div class="eval-messages" id="eval-msgs-${idea.id}">
        ${messages.map(m => {
          const isHuman = m.role === 'human';
          return `<div class="eval-msg ${isHuman ? 'human' : 'ai'}">
            <span class="eval-msg-role">${isHuman ? 'You' : 'AI'}</span>
            <span class="eval-msg-content">${esc(m.content)}</span>
          </div>`;
        }).join('')}
      </div>
      <div class="eval-input-row">
        <input class="eval-input" id="eval-input-${idea.id}" placeholder="Discuss this idea..." />
        <button class="btn small" onclick="sendEvalMessage(${idea.id})">Send</button>
      </div>
    </div>
    ${!isTerminal ? _actionsHtml(idea.id, idea.status) : ''}
  `;

  // Scroll messages to bottom
  const msgsEl = document.getElementById(`eval-msgs-${idea.id}`);
  if (msgsEl) msgsEl.scrollTop = msgsEl.scrollHeight;

  _bindEvalInput(detailEl, idea.id);
}

function _actionsHtml(ideaId, status) {
  const inFlight = status === 'queued' || status === 'executing';
  return `
    <div class="eval-actions">
      <button class="btn small success" onclick="executeIdea(${ideaId})" ${inFlight ? 'disabled' : ''}>
        ${inFlight ? (status === 'queued' ? '⏳ Queued' : '⚡ Running') : '▶ Go'}
      </button>
      <button class="btn small" onclick="promoteIdea(${ideaId}, 'todo')">Promote to TODO</button>
      <button class="btn small secondary" onclick="promoteIdea(${ideaId}, 'vision')">Add to VISION</button>
      <button class="btn small danger" onclick="archiveIdea(${ideaId})">Archive</button>
    </div>`;
}

function _bindEvalInput(container, ideaId) {
  const input = container.querySelector(`#eval-input-${ideaId}`);
  if (input) {
    input.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        sendEvalMessage(ideaId);
      }
    });
  }
}

// ─── Submit Idea ────────────────────────────────────────────────────────────

async function submitIdea() {
  const input = document.getElementById('ideaInput');
  const content = input.value.trim();
  if (!content) return;
  input.value = '';
  input.focus();

  // Batch paste: split multi-line input into separate ideas
  const lines = content.split('\n').map(l => l.trim()).filter(Boolean);
  if (lines.length > 1) {
    try {
      const res = await fetch(`/api/ideas/batch?session=${activeSessionId}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ideas: lines.map(l => ({ content: l, auto_evaluate: true })) }),
      });
      if (res.ok) {
        const created = await res.json();
        _ideas.unshift(...created);
        renderIdeasList();
        showToast(`${created.length} ideas added`);
      } else {
        input.value = content;
        showToast('Failed to add ideas', true);
      }
    } catch (e) {
      input.value = content;
      showToast('Failed to add ideas: ' + e.message, true);
    }
    return;
  }

  // Single idea
  try {
    const res = await fetch(`/api/ideas?session=${activeSessionId}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ content, auto_evaluate: true }),
    });
    if (res.ok) {
      const idea = await res.json();
      _ideas.unshift(idea);
      renderIdeasList();
    } else {
      input.value = content;
      showToast('Failed to add idea', true);
    }
  } catch (e) {
    input.value = content;
    showToast('Failed to add idea: ' + e.message, true);
  }
}

// Enter to submit, Shift+Enter for newline
document.addEventListener('DOMContentLoaded', () => {
  const input = document.getElementById('ideaInput');
  if (input) {
    input.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        submitIdea();
      }
    });
  }
});

// ─── Discussion ─────────────────────────────────────────────────────────────

async function sendEvalMessage(ideaId) {
  const input = document.getElementById(`eval-input-${ideaId}`);
  if (!input) return;
  const content = input.value.trim();
  if (!content) return;
  input.value = '';

  // Optimistic: show user message + thinking indicator
  const msgsEl = document.getElementById(`eval-msgs-${ideaId}`);
  if (msgsEl) {
    msgsEl.insertAdjacentHTML('beforeend', `<div class="eval-msg human"><span class="eval-msg-role">You</span><span class="eval-msg-content">${esc(content)}</span></div>`);
    msgsEl.insertAdjacentHTML('beforeend', `<div class="eval-msg ai"><span class="eval-msg-role">AI</span><span class="eval-msg-content eval-loading">Thinking...</span></div>`);
    msgsEl.scrollTop = msgsEl.scrollHeight;
  }
  try {
    const res = await fetch(`/api/ideas/${ideaId}/messages?session=${activeSessionId}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ content }),
    });
    // Always reload to get fresh state (handles both success + error cleanup)
    _loadIdeaDetail(ideaId);
    if (!res.ok) showToast('Failed to send message', true);
  } catch (e) {
    showToast('Failed to send message: ' + e.message, true);
    _loadIdeaDetail(ideaId);
  }
}

// ─── Actions ────────────────────────────────────────────────────────────────

async function triggerEvaluate(id) {
  try {
    const res = await fetch(`/api/ideas/${id}/evaluate?session=${activeSessionId}`, { method: 'POST' });
    if (!res.ok) { showToast('Failed to start evaluation', true); return; }
    showToast('Evaluation started');
    const idea = _ideas.find(i => i.id === id);
    if (idea) { idea.status = 'evaluating'; renderIdeasList(); }
  } catch (e) {
    showToast('Failed to start evaluation', true);
  }
}

async function promoteIdea(ideaId, target) {
  try {
    const res = await fetch(`/api/ideas/${ideaId}/promote?session=${activeSessionId}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ target }),
    });
    if (res.ok) {
      showToast(`Idea promoted to ${target.toUpperCase()}`);
      _expandedIdeaId = null;
      loadIdeas();
    }
  } catch (e) {
    showToast('Failed to promote idea', true);
  }
}

async function archiveIdea(ideaId) {
  try {
    const res = await fetch(`/api/ideas/${ideaId}?session=${activeSessionId}`, { method: 'DELETE' });
    if (!res.ok) { showToast('Failed to archive idea', true); return; }
    showToast('Idea archived');
    _expandedIdeaId = null;
    loadIdeas();
  } catch (e) {
    showToast('Failed to archive idea', true);
  }
}

async function executeIdea(ideaId) {
  try {
    const res = await fetch(`/api/ideas/${ideaId}/execute?session=${activeSessionId}`, { method: 'POST' });
    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      showToast(data.detail || 'Failed to execute idea', true);
      return;
    }
    const data = await res.json();
    showToast(data.status === 'queued' ? 'Idea queued for execution' : 'Idea executing');
    const idea = _ideas.find(i => i.id === ideaId);
    if (idea) { idea.status = data.status; renderIdeasList(); }
  } catch (e) {
    showToast('Failed to execute idea: ' + e.message, true);
  }
}

async function syncBrainstorm() {
  try {
    const res = await fetch(`/api/ideas/sync-brainstorm?session=${activeSessionId}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ direction: 'both' }),
    });
    if (res.ok) {
      const data = await res.json();
      showToast(`Synced: ${data.imported} imported, ${data.exported} exported`);
      loadIdeas();
    }
  } catch (e) {
    showToast('Sync failed: ' + e.message, true);
  }
}

// ─── WebSocket Handlers ─────────────────────────────────────────────────────

function handleIdeaWsMessage(msg) {
  if (msg.type === 'idea_update') {
    const idea = _ideas.find(i => i.id === msg.idea_id);
    if (idea) {
      idea.status = msg.status;
      if (msg.evaluation) idea.ai_evaluation_parsed = msg.evaluation;
      // Targeted card update — avoid full re-render (prevents scroll jump)
      const card = document.querySelector(`.idea-card[data-idea-id="${msg.idea_id}"]`);
      if (card && _expandedIdeaId !== msg.idea_id) {
        _updateIdeaCard(card, idea);
      } else {
        renderIdeasList();
      }
    } else {
      loadIdeas();
    }
  } else if (msg.type === 'idea_message') {
    if (_expandedIdeaId === msg.idea_id) {
      _loadIdeaDetail(msg.idea_id);
    }
  }
}

function _updateIdeaCard(cardEl, idea) {
  const badge = cardEl.querySelector('.badge');
  if (badge) {
    const labels = {
      raw: 'New', evaluating: 'Evaluating...', evaluated: 'Evaluated',
      promoting: 'Promoting...', promoted: 'Promoted', archived: 'Archived',
      queued: 'Queued', executing: 'Executing...', done: 'Done',
    };
    badge.textContent = labels[idea.status] || idea.status;
    badge.className = 'badge ' + (idea.status || 'raw');
  }

  const evalParsed = idea.ai_evaluation_parsed;

  let summaryEl = cardEl.querySelector('.idea-summary');
  const summaryText = evalParsed?.summary || '';
  if (summaryText) {
    if (!summaryEl) {
      summaryEl = document.createElement('div');
      summaryEl.className = 'idea-summary fade-in';
      const contentEl = cardEl.querySelector('.idea-content');
      if (contentEl) contentEl.after(summaryEl);
      else cardEl.appendChild(summaryEl);
    }
    summaryEl.textContent = summaryText;
  }

  const feasibility = evalParsed?.feasibility;
  let feasBarEl = cardEl.querySelector('.feas-bar');
  if (feasibility) {
    const pct = Math.min(100, (feasibility / 5) * 100);
    const color = feasibility >= 4 ? 'var(--green)' : feasibility >= 3 ? 'var(--yellow)' : 'var(--red)';
    if (!feasBarEl) {
      feasBarEl = document.createElement('div');
      feasBarEl.className = 'feas-bar';
      feasBarEl.innerHTML = '<div class="feas-fill"></div>';
      cardEl.appendChild(feasBarEl);
    }
    const fill = feasBarEl.querySelector('.feas-fill');
    if (fill) {
      fill.style.width = pct + '%';
      fill.style.background = color;
    }
  }

  const effort = evalParsed?.effort || '';
  let effortEl = cardEl.querySelector('.idea-effort');
  if (effort) {
    if (!effortEl) {
      effortEl = document.createElement('span');
      effortEl.className = 'idea-effort';
      const topRow = cardEl.querySelector('.idea-card-top');
      if (topRow) topRow.insertBefore(effortEl, topRow.querySelector('.idea-time'));
    }
    effortEl.textContent = effort;
  }
}

window._ideaWsHandler = handleIdeaWsMessage;

// Load ideas on boot (unified layout — always visible)
loadIdeas();
