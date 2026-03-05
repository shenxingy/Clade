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
  if (deferredSection) {
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
    // Automation schedule
    const elPatrolSched = document.getElementById('settingPatrolSchedule');
    const elResearchSched = document.getElementById('settingResearchSchedule');
    if (elPatrolSched) elPatrolSched.value = s.patrol_schedule ?? '';
    if (elResearchSched) elResearchSched.value = s.research_schedule ?? '';
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
          patrol_schedule: document.getElementById('settingPatrolSchedule')?.value || '',
          research_schedule: document.getElementById('settingResearchSchedule')?.value || '',
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
    const sessions = await resp.json();
    if (sessions.length < 2) {
      const btnContainer = document.getElementById('portfolioBtnContainer');
      if (btnContainer) btnContainer.style.display = 'none';
      return;
    }
    const btnContainer = document.getElementById('portfolioBtnContainer');
    if (btnContainer) btnContainer.style.display = '';
    const rows = sessions.map(s => {
      const pending = s.pending_count || 0;
      const running = s.running_count || 0;
      const done = s.done_count || 0;
      const failed = s.failed_count || 0;
      const cost = s.total_cost != null ? `$${s.total_cost.toFixed(2)}` : '—';
      const rate = s.cost_rate_per_hour != null ? `$${s.cost_rate_per_hour.toFixed(2)}` : '—';
      let eta = '—';
      if (pending === 0 && running === 0) {
        eta = 'done';
      } else if (s.cost_rate_per_hour && done > 0) {
        const elapsed = s.total_cost / s.cost_rate_per_hour;
        const rate_tasks = done / elapsed;
        const eta_hours = pending / rate_tasks;
        eta = eta_hours < 1 ? `${Math.round(eta_hours * 60)}min` : `${eta_hours.toFixed(1)}h`;
      }
      const name = s.session_id ? s.session_id.replace('/home/', '').split('/').slice(-2).join('/') : s.session_id;
      return `<tr><td>${esc(name)}</td><td style="text-align:center">${pending}</td><td style="text-align:center">${running}</td><td style="text-align:center">${done}</td><td style="text-align:center">${failed}</td><td style="text-align:center">${cost}</td><td style="text-align:center">${rate}</td><td style="text-align:center">${eta}</td></tr>`;
    }).join('');
    const tableBody = document.getElementById('portfolioTable');
    if (tableBody) tableBody.innerHTML = rows;
  } catch (e) {
    // fail silently
  }
}

// ─── Suggested Goals Widget ────────────────────────────────────────────────────

function showSuggestedGoals(content, sessionId) {
  if (sessionId) sessionStorage.setItem('suggestedGoals_' + sessionId, content);

  let div = document.getElementById('suggestedGoals');
  if (!div) {
    div = document.createElement('div');
    div.id = 'suggestedGoals';
    div.style.cssText = 'margin: 8px 0; padding: 12px; border: 1px solid #5a3e5a; border-radius: 4px; background: #1a0a2e;';
    const loopSection = document.getElementById('loopSection');
    if (loopSection) loopSection.parentNode.insertBefore(div, loopSection.nextSibling);
    else document.querySelector('.right-panel')?.appendChild(div);
  }
  div.innerHTML = `
    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px;">
      <span style="color:#c792ea; font-weight:bold;">✨ Suggested Next Goals</span>
      <span>
        <button onclick="navigator.clipboard.writeText(document.getElementById('suggestedGoalsContent').textContent)"
          style="background:#333; color:#ccc; border:1px solid #555; border-radius:3px; padding:2px 8px; cursor:pointer; margin-right:4px;">Copy</button>
        <button onclick="document.getElementById('suggestedGoals').style.display='none'"
          style="background:#333; color:#ccc; border:1px solid #555; border-radius:3px; padding:2px 8px; cursor:pointer;">×</button>
      </span>
    </div>
    <pre id="suggestedGoalsContent" style="margin:0; white-space:pre-wrap; color:#e0e0e0; font-size:0.9em;">${content.replace(/</g, '&lt;').replace(/>/g, '&gt;')}</pre>
  `;
  div.style.display = 'block';
}

// ─── Multi-project Overview ────────────────────────────────────────────────────

async function renderOverview() {
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
