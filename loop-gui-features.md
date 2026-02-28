# Goal: Phase 7.3 + Phase 8 GUI Features

## Context

**Files to modify:**
- `orchestrator/config.py` — `_ALLOWED_TASK_COLS`, `_SETTINGS_DEFAULTS`, `GLOBAL_SETTINGS`
- `orchestrator/task_queue.py` — `_ensure_db()` DB migrations, `import_from_proposed()`
- `orchestrator/session.py` — `status_loop()` (auto-scaling), worker spawn
- `orchestrator/server.py` — new routes, webhook endpoint
- `orchestrator/worker.py` — MCP config detection in subprocess launch
- `orchestrator/web/index.html` — badge rendering, preset cards, settings panel

**New files to create:**
- `orchestrator/task_factory/__init__.py`
- `orchestrator/task_factory/ci_watcher.py`
- `orchestrator/task_factory/coverage_scan.py`
- `orchestrator/task_factory/dep_update.py`
- `orchestrator/routes/__init__.py`
- `orchestrator/routes/webhooks.py`
- `configs/templates/mcp.json.example`

**Exact code patterns (verified by reading source):**

DB migration pattern in `task_queue.py` around line 117–146 — wrap each in try/except:
```python
try:
    await db.execute("ALTER TABLE tasks ADD COLUMN task_type TEXT DEFAULT 'AUTO'")
except Exception:
    pass
```

Settings pattern in `config.py` around line 54–74 — add to `_SETTINGS_DEFAULTS` dict:
```python
"auto_scale": False,
"min_workers": 1,
"webhook_secret": "",
```

`_ALLOWED_TASK_COLS` in `config.py` line 23 — add to the set:
```python
"task_type", "source_ref", "parent_task_id"
```

`import_from_proposed()` in `task_queue.py` line 436 — the header parsing loop:
- Add after `retries` parsing: if line starts with `"TYPE:"` → set `task_type`
- Valid values: `HORIZONTAL`, `VERTICAL`, `AUTO`; default `AUTO`
- Add `task_type` to the task dict passed to `add()`

`status_loop()` is in `orchestrator/session.py` line 673. Auto-scaling logic goes after the existing `auto_start` block (around line 707). See Session Start pattern below.

`start_worker()` is called from `session.py` — MCP detection goes inside `worker.py` where the subprocess command is built.

---

## Requirements

### Feature 1: Task type field (DB + parse + UI)

**DB** (`task_queue.py` `_ensure_db()`): Add 3 new columns using the try/except pattern:
```python
# Task type and dedup tracking columns
try:
    await db.execute("ALTER TABLE tasks ADD COLUMN task_type TEXT DEFAULT 'AUTO'")
except Exception:
    pass
try:
    await db.execute("ALTER TABLE tasks ADD COLUMN source_ref TEXT")
except Exception:
    pass
try:
    await db.execute("ALTER TABLE tasks ADD COLUMN parent_task_id TEXT")
except Exception:
    pass
```

**config.py** `_ALLOWED_TASK_COLS`: Add `"task_type"`, `"source_ref"`, `"parent_task_id"` to the set.

**config.py** `_SETTINGS_DEFAULTS`: Add `"auto_scale": False`, `"min_workers": 1`, `"webhook_secret": ""`.

**task_queue.py** `import_from_proposed()` header loop: After the `retries` check, add:
```python
elif in_header and line.startswith("TYPE:"):
    val = line.split(":", 1)[1].strip().upper()
    if val in ("HORIZONTAL", "VERTICAL", "AUTO"):
        task_type = val
```
Initialize `task_type = "AUTO"` before the loop. Pass `task_type=task_type` to `add()`.

**index.html** `renderQueue()`: In the task card HTML, add a badge after the model badge:
- `HORIZONTAL` → `<span class="badge badge-h">H</span>` (orange)
- `VERTICAL` → `<span class="badge badge-v">V</span>` (blue)
- `AUTO` → `<span class="badge badge-a">A</span>` (gray, or omit entirely)

CSS for badges (add to `<style>` block):
```css
.badge-h { background: #f97316; color: #fff; border-radius: 3px; padding: 1px 5px; font-size: 11px; font-weight: bold; }
.badge-v { background: #3b82f6; color: #fff; border-radius: 3px; padding: 1px 5px; font-size: 11px; font-weight: bold; }
.badge-a { background: #6b7280; color: #fff; border-radius: 3px; padding: 1px 5px; font-size: 11px; font-weight: bold; }
```

Also add to worker cards: show the task_type badge next to the task description.

---

### Feature 2: Horizontal auto-decomposition

**Location:** `orchestrator/session.py`, inside `status_loop()` before calling `start_worker()` for a task.

Before the `await session.worker_pool.start_worker(...)` call for `_task` in the auto-start loop, add:
```python
if _task.get("task_type") == "HORIZONTAL":
    await _decompose_horizontal(_task, session)
    continue  # parent task is now 'grouped', skip start_worker
```

**`_decompose_horizontal(task, session)` function** (add to `session.py`):
1. Call `claude --model claude-haiku-4-5-20251001 -p "List the source files that need changes for this task. Output one file path per line, no explanation:\n{task_description}"` with timeout 30s using `asyncio.create_subprocess_exec`
2. Parse stdout to get file list (strip empty lines, lines starting with `#`)
3. Cap at 20 files
4. For each file path: create a child task with description `[file: {path}] {original_description}`, set `parent_task_id=task['id']`, `task_type='VERTICAL'`
5. Set parent task status to `grouped` via `session.task_queue.update(task['id'], status='grouped')`
6. Call `await broadcast()` after state changes

Add `"grouped"` as a valid task status (it renders like "pending" in UI but signals decomposed).

**Monitoring:** In `poll_all()` or `status_loop()`, check if all children of a grouped parent are done → set parent to `done`. Look for tasks where `parent_task_id == parent['id']` and all have status `done`.

---

### Feature 3: Worker auto-scaling

**config.py** `_SETTINGS_DEFAULTS`: Already covered in Feature 1 (add `auto_scale`, `min_workers`).

**session.py** `status_loop()`: After the existing auto_start block (around line 720), add auto-scaling logic:

```python
# Auto-scaling: spawn additional workers when queue is backlogged
if GLOBAL_SETTINGS.get("auto_scale", False) and not _swarm_active:
    _running_now = sum(1 for w in session.worker_pool.all() if w.status == "running")
    _pending_now = len([t for t in _auto_tasks if t["status"] == "pending"])
    _max_w = GLOBAL_SETTINGS.get("max_workers", 8) or 8
    _min_w = GLOBAL_SETTINGS.get("min_workers", 1)
    _spawn_cooldown = getattr(session, '_last_autoscale', 0)
    if (_pending_now > _running_now * 2
            and _running_now < _max_w
            and time.time() - _spawn_cooldown > 30):
        # Spawn one extra worker for the next ready pending task
        _ready = [t for t in _auto_tasks if t["status"] == "pending" and _deps_met(t, _done_ids)]
        if _ready and not session._budget_exceeded:
            await session.worker_pool.start_worker(
                _ready[0], session.task_queue,
                session.project_dir, session.claude_dir,
            )
            session._last_autoscale = time.time()
```

**index.html** Settings panel: Add auto-scale toggle and min/max inputs:
```html
<div class="setting-row">
  <label>Auto-Scale Workers</label>
  <input type="checkbox" id="auto_scale" onchange="saveSetting('auto_scale', this.checked)">
</div>
<div class="setting-row">
  <label>Min Workers</label>
  <input type="number" id="min_workers" min="1" max="16" onchange="saveSetting('min_workers', +this.value)">
</div>
```
Load `auto_scale` and `min_workers` values in the existing `loadSettings()` call.

---

### Feature 4: CI failure watcher

Create `orchestrator/task_factory/__init__.py` (empty or minimal):
```python
"""Task factory modules for auto-generating tasks from external sources."""
```

Create `orchestrator/task_factory/ci_watcher.py`:
```python
"""CI failure watcher — polls GitHub Actions for failed runs, creates tasks."""
import os
import httpx
import logging

logger = logging.getLogger(__name__)

async def check_ci_failures(task_queue, project_dir: str) -> list[str]:
    """Check GitHub Actions for failed runs. Returns list of created task IDs."""
    token = os.environ.get("GITHUB_TOKEN", "")
    if not token:
        return []
    # Detect repo from git remote
    import subprocess
    try:
        remote = subprocess.check_output(
            ["git", "remote", "get-url", "origin"], cwd=project_dir, text=True
        ).strip()
    except Exception:
        return []
    # Parse owner/repo from remote URL
    # Supports: https://github.com/owner/repo.git and git@github.com:owner/repo.git
    import re
    m = re.search(r"github\.com[:/]([^/]+)/([^/.]+)", remote)
    if not m:
        return []
    owner, repo = m.group(1), m.group(2)
    url = f"https://api.github.com/repos/{owner}/{repo}/actions/runs?status=failure&per_page=10"
    headers = {"Authorization": f"token {token}", "Accept": "application/vnd.github.v3+json"}
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(url, headers=headers)
            if resp.status_code != 200:
                return []
            runs = resp.json().get("workflow_runs", [])
    except Exception as e:
        logger.warning("CI watcher fetch error: %s", e)
        return []
    created = []
    existing = await task_queue.list()
    existing_refs = {t.get("source_ref") for t in existing}
    for run in runs:
        source_ref = f"ci_run_{run['id']}"
        if source_ref in existing_refs:
            continue
        desc = (
            f"Fix CI failure: {run.get('name', 'Unknown workflow')} failed on "
            f"branch {run.get('head_branch', '?')}. "
            f"Run URL: {run.get('html_url', '')}. "
            f"Investigate the failure and fix the root cause."
        )
        task_id = await task_queue.add(description=desc, source_ref=source_ref)
        created.append(task_id)
        logger.info("Created CI failure task %s for run %s", task_id, run['id'])
    return created
```

**Integration in `session.py`**: Add a `_ci_watcher_last` timestamp on sessions (default 0). In `status_loop()`, every 5 minutes (300s), call `check_ci_failures` if `GLOBAL_SETTINGS.get("github_issues_sync", False)`:
```python
# Task factory: CI watcher (every 5 min)
if (GLOBAL_SETTINGS.get("github_issues_sync", False)
        and time.time() - getattr(session, '_ci_watcher_last', 0) > 300):
    session._ci_watcher_last = time.time()
    try:
        from task_factory.ci_watcher import check_ci_failures
        await check_ci_failures(session.task_queue, str(session.project_dir))
    except Exception as e:
        logger.warning("CI watcher error: %s", e)
```

---

### Feature 5: Test coverage gap detector

Create `orchestrator/task_factory/coverage_scan.py`:
```python
"""Coverage gap scanner — finds under-tested modules, creates tasks."""
import json
import logging
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

async def check_coverage_gaps(task_queue, project_dir: str, threshold: float = 80.0) -> list[str]:
    """Find modules below coverage threshold and create tasks to add tests."""
    project_path = Path(project_dir)
    coverage_file = project_path / ".coverage"
    json_file = project_path / "coverage.json"
    # Try to generate coverage.json if .coverage exists
    if coverage_file.exists() and not json_file.exists():
        try:
            subprocess.run(["python", "-m", "coverage", "json"], cwd=project_dir, timeout=30, capture_output=True)
        except Exception:
            pass
    if not json_file.exists():
        return []
    try:
        data = json.loads(json_file.read_text())
        files = data.get("files", {})
    except Exception as e:
        logger.warning("Coverage scan parse error: %s", e)
        return []
    existing = await task_queue.list()
    existing_refs = {t.get("source_ref") for t in existing}
    created = []
    for filepath, info in files.items():
        summary = info.get("summary", {})
        pct = summary.get("percent_covered", 100.0)
        if pct < threshold:
            source_ref = f"coverage_{filepath.replace('/', '_')}"
            if source_ref in existing_refs:
                continue
            desc = (
                f"Add tests for {filepath} — currently {pct:.1f}% covered (threshold: {threshold}%). "
                f"Missing lines: {summary.get('missing_lines', '?')}. "
                f"Write unit tests to bring coverage above {threshold}%."
            )
            task_id = await task_queue.add(description=desc, source_ref=source_ref)
            created.append(task_id)
            logger.info("Created coverage task %s for %s (%.1f%%)", task_id, filepath, pct)
    return created
```

---

### Feature 6: Dependency update bot

Create `orchestrator/task_factory/dep_update.py`:
```python
"""Dependency update bot — checks for outdated packages, creates update tasks."""
import json
import logging
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

async def check_outdated_deps(task_queue, project_dir: str) -> list[str]:
    """Check for outdated dependencies and create update tasks."""
    project_path = Path(project_dir)
    existing = await task_queue.list()
    existing_refs = {t.get("source_ref") for t in existing}
    created = []

    # Python: pip list --outdated
    if (project_path / "requirements.txt").exists() or (project_path / "pyproject.toml").exists():
        try:
            result = subprocess.run(
                ["pip", "list", "--outdated", "--format=json"],
                cwd=project_dir, capture_output=True, text=True, timeout=30
            )
            outdated = json.loads(result.stdout or "[]")
            for pkg in outdated[:10]:  # cap at 10
                name, current, latest = pkg.get("name"), pkg.get("version"), pkg.get("latest_version")
                source_ref = f"dep_{name}_{latest}"
                if source_ref in existing_refs:
                    continue
                desc = f"Update Python package {name} from {current} to {latest}. Run: pip install {name}=={latest}, update requirements, run tests."
                task_id = await task_queue.add(description=desc, source_ref=source_ref)
                created.append(task_id)
        except Exception as e:
            logger.warning("pip outdated check failed: %s", e)

    # Node.js: npm outdated
    if (project_path / "package.json").exists():
        try:
            result = subprocess.run(
                ["npm", "outdated", "--json"],
                cwd=project_dir, capture_output=True, text=True, timeout=30
            )
            outdated = json.loads(result.stdout or "{}")
            for name, info in list(outdated.items())[:10]:
                current, latest = info.get("current", "?"), info.get("latest", "?")
                source_ref = f"dep_{name}_{latest}"
                if source_ref in existing_refs:
                    continue
                desc = f"Update npm package {name} from {current} to {latest}. Run: npm install {name}@{latest}, run tests."
                task_id = await task_queue.add(description=desc, source_ref=source_ref)
                created.append(task_id)
        except Exception as e:
            logger.warning("npm outdated check failed: %s", e)

    return created
```

---

### Feature 7: GitHub webhook endpoint

Create `orchestrator/routes/__init__.py`:
```python
"""FastAPI route modules."""
```

Create `orchestrator/routes/webhooks.py`:
```python
"""GitHub webhook endpoint — creates tasks from Issues and PR comments."""
import hashlib
import hmac
import json
import logging
from fastapi import APIRouter, Header, HTTPException, Request
from config import GLOBAL_SETTINGS
from task_queue import TaskQueue

router = APIRouter()
logger = logging.getLogger(__name__)


def _verify_signature(payload: bytes, signature: str, secret: str) -> bool:
    if not secret or not signature:
        return not secret  # if no secret configured, allow all
    expected = "sha256=" + hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


@router.post("/api/webhooks/github")
async def github_webhook(
    request: Request,
    x_github_event: str = Header(default=""),
    x_hub_signature_256: str = Header(default=""),
):
    payload_bytes = await request.body()
    secret = GLOBAL_SETTINGS.get("webhook_secret", "")
    if not _verify_signature(payload_bytes, x_hub_signature_256, secret):
        raise HTTPException(status_code=401, detail="Invalid signature")
    try:
        payload = json.loads(payload_bytes)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    # Get active session's task queue (use default session)
    from session import registry
    session = registry.get_default()
    if not session:
        return {"status": "no_active_session"}

    tq: TaskQueue = session.task_queue
    existing = await tq.list()
    existing_refs = {t.get("source_ref") for t in existing}
    created = []

    if x_github_event == "issues":
        action = payload.get("action", "")
        issue = payload.get("issue", {})
        labels = [l.get("name", "") for l in issue.get("labels", [])]
        if action in ("labeled", "opened") and "claude-do-it" in labels:
            source_ref = f"gh_issue_{issue['number']}"
            if source_ref not in existing_refs:
                desc = f"GitHub Issue #{issue['number']}: {issue['title']}\n\n{issue.get('body', '')}"
                task_id = await tq.add(description=desc, source_ref=source_ref)
                created.append(task_id)

    elif x_github_event == "issue_comment":
        comment = payload.get("comment", {})
        body = comment.get("body", "")
        if body.startswith("/claude "):
            instruction = body[len("/claude "):].strip()
            issue = payload.get("issue", {})
            pr = payload.get("pull_request")
            num = issue.get("number", 0)
            ref_prefix = "gh_pr" if pr else "gh_issue"
            source_ref = f"{ref_prefix}_{num}_comment_{comment['id']}"
            if source_ref not in existing_refs:
                context = f"PR #{num}" if pr else f"Issue #{num}"
                desc = f"[{context}] {instruction}"
                task_id = await tq.add(description=desc, source_ref=source_ref)
                created.append(task_id)

    return {"status": "ok", "created": created}
```

**Register in `server.py`**: Near the top where other app setup happens, add:
```python
from routes.webhooks import router as webhooks_router
app.include_router(webhooks_router)
```

**Settings panel in index.html**: Add a `webhook_secret` password input field alongside other settings.

---

### Feature 8: GUI preset cards

**index.html**: Above the task textarea (find the task form section), add a "Quick Presets" section:

```html
<div class="preset-cards" id="presetCards">
  <div class="preset-card" onclick="applyPreset('test-writer')">
    <div class="preset-icon">🧪</div>
    <div class="preset-name">Test Writer</div>
    <div class="preset-desc">Add unit tests for untested code</div>
  </div>
  <div class="preset-card" onclick="applyPreset('refactor-bot')">
    <div class="preset-icon">♻️</div>
    <div class="preset-name">Refactor Bot</div>
    <div class="preset-desc">Clean up code smell and tech debt</div>
  </div>
  <div class="preset-card" onclick="applyPreset('docs-bot')">
    <div class="preset-icon">📝</div>
    <div class="preset-name">Docs Bot</div>
    <div class="preset-desc">Write or update documentation</div>
  </div>
  <div class="preset-card" onclick="applyPreset('security-scan')">
    <div class="preset-icon">🔒</div>
    <div class="preset-name">Security Scan</div>
    <div class="preset-desc">Audit for vulnerabilities</div>
  </div>
</div>
```

CSS for preset cards:
```css
.preset-cards { display: flex; gap: 8px; margin-bottom: 12px; flex-wrap: wrap; }
.preset-card { flex: 1; min-width: 120px; padding: 10px; border: 1px solid #374151; border-radius: 6px; cursor: pointer; transition: border-color 0.15s, background 0.15s; text-align: center; }
.preset-card:hover { border-color: #6366f1; background: #1e1b4b22; }
.preset-icon { font-size: 20px; margin-bottom: 4px; }
.preset-name { font-size: 13px; font-weight: 600; color: #e5e7eb; }
.preset-desc { font-size: 11px; color: #9ca3af; margin-top: 2px; }
```

JavaScript `applyPreset(type)` function:
```javascript
function applyPreset(type) {
  const presets = {
    'test-writer': {
      text: 'Scan the codebase for untested functions and modules. Write comprehensive unit tests using the project\'s existing test framework. Focus on edge cases, error paths, and boundary conditions. Commit tests with meaningful names.',
      model: 'sonnet',
      type: 'HORIZONTAL'
    },
    'refactor-bot': {
      text: 'Identify code smells: duplicated logic, overly long functions (>50 lines), magic numbers, unclear naming, deeply nested conditionals. Refactor for readability and maintainability. No behavior changes — tests must still pass.',
      model: 'sonnet',
      type: 'HORIZONTAL'
    },
    'docs-bot': {
      text: 'Review the codebase for missing or outdated documentation. Write or update: module-level docstrings, README sections, inline comments for non-obvious logic. Focus on public APIs and key algorithms.',
      model: 'haiku',
      type: 'VERTICAL'
    },
    'security-scan': {
      text: 'Audit the codebase for security vulnerabilities: SQL injection, XSS, hardcoded secrets, insecure deserialization, missing input validation, overly permissive CORS, exposed error details in API responses. Fix any issues found.',
      model: 'sonnet',
      type: 'VERTICAL'
    }
  };
  const p = presets[type];
  if (!p) return;
  // Fill textarea
  const textarea = document.getElementById('taskDescription') || document.querySelector('textarea[name="description"]') || document.querySelector('textarea');
  if (textarea) textarea.value = p.text;
  // Set model selector
  const modelSel = document.getElementById('modelSelect') || document.querySelector('select[name="model"]') || document.querySelector('select');
  if (modelSel) modelSel.value = p.model;
  // Set task type if the UI has a type selector
  const typeSel = document.getElementById('taskType');
  if (typeSel) typeSel.value = p.type;
}
```

---

### Feature 9: MCP integration

**worker.py**: In the function that builds the `claude` subprocess command, after assembling the base command, detect and append MCP config:

Find where `cmd` is assembled (look for `claude` subprocess args). Add:
```python
# MCP config auto-detection
mcp_config = Path(project_dir) / ".claude" / "mcp.json"
if mcp_config.exists():
    cmd.extend(["--mcp-config", str(mcp_config)])
```

**Create `configs/templates/mcp.json.example`**:
```json
{
  "mcpServers": {
    "brave-search": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-brave-search"],
      "env": {
        "BRAVE_API_KEY": "your-brave-api-key-here"
      }
    },
    "filesystem": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "/path/to/project"]
    },
    "playwright": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-playwright"]
    }
  }
}
```

---

## Acceptance Criteria

- [x] `task_type` column exists in tasks table (verified: `ALTER TABLE` in `_ensure_db()`)
- [x] `source_ref` column exists in tasks table
- [x] `parent_task_id` column exists in tasks table
- [x] `import_from_proposed()` parses `TYPE:` header field and stores `task_type`
- [x] Task cards in UI show H/V/A badge based on `task_type`
- [x] `_SETTINGS_DEFAULTS` includes `auto_scale`, `min_workers`, `webhook_secret`
- [x] Settings panel has auto-scale toggle + min/max inputs that persist to settings file
- [x] `status_loop()` has auto-scaling logic with 30s cooldown
- [x] `_decompose_horizontal()` exists and creates child tasks for HORIZONTAL task type
- [x] `orchestrator/task_factory/ci_watcher.py` exists and has `check_ci_failures()` function
- [x] `orchestrator/task_factory/coverage_scan.py` exists and has `check_coverage_gaps()` function
- [x] `orchestrator/task_factory/dep_update.py` exists and has `check_outdated_deps()` function
- [x] `orchestrator/routes/webhooks.py` exists with `/api/webhooks/github` endpoint
- [x] Webhook endpoint validates HMAC signature
- [x] Webhook router registered in `server.py` with `app.include_router()`
- [x] GUI preset cards appear above task form (4 presets: test-writer, refactor-bot, docs-bot, security-scan)
- [x] Clicking a preset fills textarea + sets model
- [x] `worker.py` detects `.claude/mcp.json` and passes `--mcp-config` to subprocess
- [x] `configs/templates/mcp.json.example` exists
- [x] Server starts without errors after all changes

---

## Verification Checklist

### Auto-Verifiable (worker must complete)

- [ ] `cd orchestrator && python -c "import server; print('OK')"` passes (no import errors)
- [ ] `cd orchestrator && python -c "from task_factory.ci_watcher import check_ci_failures; print('OK')"` passes
- [x] `cd orchestrator && python -c "from routes.webhooks import router; print('OK')"` passes
- [ ] All new Python files have no syntax errors (`python -m py_compile <file>`)
- [ ] No circular imports introduced (DAG rule)
- [ ] Each feature committed separately with `committer`

### Human-Verifiable

- [x] H/V/A badges visible in task queue and worker cards
- [x] Preset cards render correctly and fill form on click
- [x] Settings panel shows auto-scale toggle and persists on reload
- [ ] Server starts: `cd orchestrator && python server.py` no errors

---

## Implementation Notes

- Read each target file fully before editing (never blind edits)
- DB migration must use try/except pattern — SQLite has no `IF NOT EXISTS` for ALTER
- `_ALLOWED_TASK_COLS` and `_SETTINGS_DEFAULTS` are in `config.py`, NOT `task_queue.py`
- `status_loop()` is in `session.py` (not server.py) — check line 673
- After any state change in session.py, call `await broadcast(session)` or equivalent
- `task_queue.add()` signature: check existing callers to match kwargs
- For webhook route: `registry.get_default()` — check how `registry` is accessed in server.py
- Keep files under 1500 lines — if server.py or session.py exceeds limit, extract to module
- Commit order: DB columns first → config changes → task_queue → session → server → frontend
- Use `committer "feat: ..." file1 file2` for each logical unit (one feature = one commit)
