// ─── Ideas Mode ─────────────────────────────────────────────────────────────
// Frontend logic for the Ideas brainstorm + AI evaluation panel.

let _ideas = [];
let _selectedIdeaId = null;

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
  if (!list) return;
  if (_ideas.length === 0) {
    list.innerHTML = '<div class="empty">No ideas yet — start typing below</div>';
    return;
  }
  list.innerHTML = _ideas.map(idea => {
    const isSelected = idea.id === _selectedIdeaId;
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
      <div class="idea-card ${isSelected ? 'selected' : ''} ${esc(statusClass)}"
           onclick="selectIdea(${idea.id})">
        <div class="idea-card-top">
          ${statusBadge}
          ${sourceTag}
          ${effortBadge}
          <span class="idea-time">${_timeAgo(idea.created_at)}</span>
        </div>
        <div class="idea-content">${esc(idea.content)}</div>
        ${summary ? `<div class="idea-summary">${esc(summary)}</div>` : ''}
        ${feasBar}
      </div>`;
  }).join('');
}

function _ideaStatusBadge(status) {
  const labels = {
    raw: 'New', evaluating: 'Evaluating...', evaluated: 'Evaluated',
    promoting: 'Promoting...', promoted: 'Promoted', archived: 'Archived',
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
      }
    } catch (e) {
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
      // Stay in input — don't selectIdea (async inbox UX)
    }
  } catch (e) {
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

// ─── Select & Detail ────────────────────────────────────────────────────────

async function selectIdea(id) {
  _selectedIdeaId = id;
  renderIdeasList();
  const content = document.getElementById('evalContent');
  if (content) content.innerHTML = '<div class="eval-loading">Loading...</div>';
  try {
    const res = await fetch(`/api/ideas/${id}?session=${activeSessionId}`);
    if (!res.ok) {
      if (content) content.innerHTML = '<div class="empty">Failed to load idea</div>';
      return;
    }
    const idea = await res.json();
    renderEvaluation(idea);
  } catch (e) {
    console.warn('selectIdea error:', e);
    if (content) content.innerHTML = '<div class="empty">Failed to load idea</div>';
  }
}

function renderEvaluation(idea) {
  const content = document.getElementById('evalContent');
  const chat = document.getElementById('evalChat');
  const actions = document.getElementById('evalActions');
  if (!content) return;

  const evalData = idea.ai_evaluation_parsed;
  if (!evalData || evalData.error) {
    const errorMsg = evalData?.error || '';
    const statusMsg = idea.status === 'evaluating'
      ? '<div class="eval-loading">Evaluating...</div>'
      : `<div class="empty">No evaluation yet${errorMsg ? ': ' + esc(errorMsg) : ''}</div>
         <button class="btn small" onclick="triggerEvaluate(${idea.id})" style="margin:8px auto;display:block">Evaluate Now</button>`;
    content.innerHTML = statusMsg;
    if (chat) chat.style.display = 'none';
    if (actions) actions.style.display = idea.status !== 'promoted' && idea.status !== 'archived' ? 'flex' : 'none';
    return;
  }

  const feasScore = evalData.feasibility || 0;
  const feasColor = feasScore >= 4 ? 'var(--green)' : feasScore >= 3 ? 'var(--yellow)' : 'var(--red)';
  const risks = (evalData.risks || []).map(r => `<li>${esc(r)}</li>`).join('');
  const alts = (evalData.alternatives || []).map(a => `<li>${esc(a)}</li>`).join('');
  const missing = (evalData.missing || []).map(m => `<li>${esc(m)}</li>`).join('');

  content.innerHTML = `
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
  `;

  // Show chat
  if (chat) {
    chat.style.display = 'flex';
    renderEvalMessages(idea.messages || []);
  }
  // Show actions (not for promoted/archived)
  if (actions) actions.style.display = idea.status !== 'promoted' && idea.status !== 'archived' ? 'flex' : 'none';
}

function renderEvalMessages(messages) {
  const container = document.getElementById('evalMessages');
  if (!container) return;
  container.innerHTML = messages.map(m => {
    const isHuman = m.role === 'human';
    return `<div class="eval-msg ${isHuman ? 'human' : 'ai'}">
      <span class="eval-msg-role">${isHuman ? 'You' : 'AI'}</span>
      <span class="eval-msg-content">${esc(m.content)}</span>
    </div>`;
  }).join('');
  container.scrollTop = container.scrollHeight;
}

// ─── Discussion ─────────────────────────────────────────────────────────────

async function sendEvalMessage() {
  if (!_selectedIdeaId) return;
  const input = document.getElementById('evalInput');
  const content = input.value.trim();
  if (!content) return;
  input.value = '';
  // Optimistic: show user message immediately
  const container = document.getElementById('evalMessages');
  if (container) {
    container.innerHTML += `<div class="eval-msg human"><span class="eval-msg-role">You</span><span class="eval-msg-content">${esc(content)}</span></div>`;
    container.innerHTML += `<div class="eval-msg ai"><span class="eval-msg-role">AI</span><span class="eval-msg-content eval-loading">Thinking...</span></div>`;
    container.scrollTop = container.scrollHeight;
  }
  try {
    const res = await fetch(`/api/ideas/${_selectedIdeaId}/messages?session=${activeSessionId}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ content }),
    });
    if (res.ok) {
      // Reload full idea to get updated messages
      selectIdea(_selectedIdeaId);
    }
  } catch (e) {
    showToast('Failed to send message: ' + e.message, true);
    // Remove the "Thinking..." placeholder on failure
    if (container) {
      const thinking = container.querySelector('.eval-loading');
      if (thinking) thinking.closest('.eval-msg')?.remove();
    }
  }
}

// Enter to send in eval chat
document.addEventListener('DOMContentLoaded', () => {
  const input = document.getElementById('evalInput');
  if (input) {
    input.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        sendEvalMessage();
      }
    });
  }
});

// ─── Actions ────────────────────────────────────────────────────────────────

async function triggerEvaluate(id) {
  try {
    await fetch(`/api/ideas/${id}/evaluate?session=${activeSessionId}`, { method: 'POST' });
    showToast('Evaluation started');
    // Update local status
    const idea = _ideas.find(i => i.id === id);
    if (idea) { idea.status = 'evaluating'; renderIdeasList(); }
  } catch (e) {
    showToast('Failed to start evaluation', true);
  }
}

async function promoteIdea(target) {
  if (!_selectedIdeaId) return;
  try {
    const res = await fetch(`/api/ideas/${_selectedIdeaId}/promote?session=${activeSessionId}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ target }),
    });
    if (res.ok) {
      showToast(`Idea promoted to ${target.toUpperCase()}`);
      loadIdeas();
    }
  } catch (e) {
    showToast('Failed to promote idea', true);
  }
}

async function archiveIdea() {
  if (!_selectedIdeaId) return;
  try {
    await fetch(`/api/ideas/${_selectedIdeaId}?session=${activeSessionId}`, { method: 'DELETE' });
    showToast('Idea archived');
    _selectedIdeaId = null;
    loadIdeas();
    const ec = document.getElementById('evalContent');
    const ch = document.getElementById('evalChat');
    const ac = document.getElementById('evalActions');
    if (ec) ec.innerHTML = '<div class="empty">Select an idea to see AI evaluation</div>';
    if (ch) ch.style.display = 'none';
    if (ac) ac.style.display = 'none';
  } catch (e) {
    showToast('Failed to archive idea', true);
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
      // Targeted card update — avoid full re-render (prevents scroll jump + focus loss)
      const card = document.querySelector(`.idea-card[onclick*="selectIdea(${msg.idea_id})"]`);
      if (card) {
        _updateIdeaCard(card, idea);
      } else {
        renderIdeasList();
      }
      if (_selectedIdeaId === msg.idea_id) selectIdea(msg.idea_id);
    } else {
      // New idea from another source — reload
      loadIdeas();
    }
  } else if (msg.type === 'idea_message') {
    if (_selectedIdeaId === msg.idea_id) {
      selectIdea(msg.idea_id);  // reload to show new message
    }
  }
}

function _updateIdeaCard(cardEl, idea) {
  // Update status badge
  const badge = cardEl.querySelector('.badge');
  if (badge) {
    const labels = {
      raw: 'New', evaluating: 'Evaluating...', evaluated: 'Evaluated',
      promoting: 'Promoting...', promoted: 'Promoted', archived: 'Archived',
    };
    badge.textContent = labels[idea.status] || idea.status;
    badge.className = 'badge ' + (idea.status || 'raw');
  }

  const evalParsed = idea.ai_evaluation_parsed;

  // Insert/update summary
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

  // Insert/update feasibility bar
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

  // Update effort badge
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

// Register as a global handler — app-core.js calls this if defined
// (avoids fragile monkey-patching of connectStatus)
window._ideaWsHandler = handleIdeaWsMessage;
