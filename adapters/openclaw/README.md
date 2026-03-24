# Clade — OpenClaw Adapter

Monitor and control [Clade](https://github.com/shenxingy/clade) autonomous coding loops from any messaging channel via [OpenClaw](https://openclaw.ai).

## What this does

Three OpenClaw skills that let you manage overnight coding sessions from your phone:

| Skill | What you say in Telegram/WhatsApp | What happens |
|-------|-----------------------------------|-------------|
| **clade-status** | "how's the loop going" | Shows iteration, progress, cost, recent commits |
| **clade-control** | "start a loop to fix all tests, run 5 times" | Starts autonomous loop with specified params |
| **clade-report** | "what did it do overnight" | Shows session report, cost breakdown, blockers |

## Architecture

```
Phone → Telegram → OpenClaw → HTTP → monitor.py → reads CLI state files
                                          ↓
                                    .claude/loop-state
                                    logs/loop/
                                    .claude/loop-cost.log
                                    .claude/session-report-*.md
```

`monitor.py` is a lightweight HTTP server (~150 lines) that reads the state files produced by Clade's CLI tools (`loop-runner.sh`, `start.sh`). It does not depend on the orchestrator.

## Setup

### 1. Install Clade (if not already)

```bash
git clone https://github.com/shenxingy/clade.git
cd clade && ./install.sh
```

### 2. Start the monitor

```bash
# Single project
CLADE_API_KEY=your-secret-key python adapters/openclaw/monitor.py \
  --project /path/to/your/project --port 9100

# Multiple projects
CLADE_API_KEY=your-secret-key python adapters/openclaw/monitor.py \
  --project /path/to/proj1 --project /path/to/proj2
```

Requires: Python 3.10+, `aiohttp` (`pip install aiohttp`).

### 3. (Optional) Run as systemd service

```bash
# Edit monitor.service to set your project path and API key
cp adapters/openclaw/monitor.service ~/.config/systemd/user/clade-monitor.service
# Edit the file, then:
systemctl --user enable --now clade-monitor
```

### 4. Install skills in OpenClaw

Copy the `skills/` directory to your OpenClaw skills folder:

```bash
cp -r adapters/openclaw/skills/clade-* ~/.openclaw/skills/
```

### 5. Configure OpenClaw environment

Set these in your OpenClaw config:

```
CLADE_BASE_URL=http://your-server:9100   # or Tailscale URL
CLADE_API_KEY=your-secret-key            # must match monitor's key
```

## API Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/health` | Health check (no auth required) |
| `GET` | `/status?project=PATH` | Loop state, commits, cost, supervisor output |
| `GET` | `/report?project=PATH` | Session report, cost history, blockers |
| `POST` | `/control` | Start/stop loop, clear blockers |

All endpoints (except `/health`) require `Authorization: Bearer <CLADE_API_KEY>` when the key is set.

## Security

- **Always set `CLADE_API_KEY`** when exposing the monitor outside localhost
- The monitor only reads state files and starts/stops loops — it cannot execute arbitrary commands
- Recommended: expose via Tailscale rather than public internet
