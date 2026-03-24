# Claude Code Kit — OpenClaw Adapter

Monitor and control [Claude Code Kit](https://github.com/shenxingy/claude-code-kit) autonomous coding loops from any messaging channel via [OpenClaw](https://openclaw.ai).

## What this does

Three OpenClaw skills that let you manage overnight coding sessions from your phone:

| Skill | What you say in Telegram/WhatsApp | What happens |
|-------|-----------------------------------|-------------|
| **cck-status** | "how's the loop going" | Shows iteration, progress, cost, recent commits |
| **cck-control** | "start a loop to fix all tests, run 5 times" | Starts autonomous loop with specified params |
| **cck-report** | "what did it do overnight" | Shows session report, cost breakdown, blockers |

## Architecture

```
Phone → Telegram → OpenClaw → HTTP → monitor.py → reads CLI state files
                                          ↓
                                    .claude/loop-state
                                    logs/loop/
                                    .claude/loop-cost.log
                                    .claude/session-report-*.md
```

`monitor.py` is a lightweight HTTP server (~150 lines) that reads the state files produced by Claude Code Kit's CLI tools (`loop-runner.sh`, `start.sh`). It does not depend on the orchestrator.

## Setup

### 1. Install Claude Code Kit (if not already)

```bash
git clone https://github.com/shenxingy/claude-code-kit.git
cd claude-code-kit && ./install.sh
```

### 2. Start the monitor

```bash
# Single project
CCK_API_KEY=your-secret-key python adapters/openclaw/monitor.py \
  --project /path/to/your/project --port 9100

# Multiple projects
CCK_API_KEY=your-secret-key python adapters/openclaw/monitor.py \
  --project /path/to/proj1 --project /path/to/proj2
```

Requires: Python 3.10+, `aiohttp` (`pip install aiohttp`).

### 3. (Optional) Run as systemd service

```bash
# Edit monitor.service to set your project path and API key
cp adapters/openclaw/monitor.service ~/.config/systemd/user/cck-monitor.service
# Edit the file, then:
systemctl --user enable --now cck-monitor
```

### 4. Install skills in OpenClaw

Copy the `skills/` directory to your OpenClaw skills folder:

```bash
cp -r adapters/openclaw/skills/cck-* ~/.openclaw/skills/
```

### 5. Configure OpenClaw environment

Set these in your OpenClaw config:

```
CCK_BASE_URL=http://your-server:9100   # or Tailscale URL
CCK_API_KEY=your-secret-key            # must match monitor's key
```

## API Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/health` | Health check (no auth required) |
| `GET` | `/status?project=PATH` | Loop state, commits, cost, supervisor output |
| `GET` | `/report?project=PATH` | Session report, cost history, blockers |
| `POST` | `/control` | Start/stop loop, clear blockers |

All endpoints (except `/health`) require `Authorization: Bearer <CCK_API_KEY>` when the key is set.

## Security

- **Always set `CCK_API_KEY`** when exposing the monitor outside localhost
- The monitor only reads state files and starts/stops loops — it cannot execute arbitrary commands
- Recommended: expose via Tailscale rather than public internet
