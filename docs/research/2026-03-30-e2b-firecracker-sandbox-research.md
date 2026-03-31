# E2B & Firecracker microVM 沙盒技术深度研究

> 研究日期: 2026-03-30  
> 研究目标: 理解 E2B 沙盒平台和 Firecracker microVM 的技术架构，评估对 Clade agent 执行隔离的可借鉴模式

---

## 目录

1. [E2B 概览](#1-e2b-概览)
2. [E2B SDK 核心接口](#2-e2b-sdk-核心接口)
3. [沙盒生命周期](#3-沙盒生命周期)
4. [文件系统与持久化](#4-文件系统与持久化)
5. [网络隔离策略](#5-网络隔离策略)
6. [模板系统 (Templates)](#6-模板系统-templates)
7. [E2B 计费模型](#7-e2b-计费模型)
8. [与 Claude Code / AI Agent 的集成](#8-与-claude-code--ai-agent-的集成)
9. [Firecracker microVM 深度解析](#9-firecracker-microvm-深度解析)
10. [Snapshot/Restore 原理 — 28ms 启动的关键](#10-snapshotrestore-原理--28ms-启动的关键)
11. [vsock 通信机制](#11-vsock-通信机制)
12. [Jailer 安全层](#12-jailer-安全层)
13. [沙盒隔离技术对比](#13-沙盒隔离技术对比)
14. [AI Agent 场景中的应用现状](#14-ai-agent-场景中的应用现状)
15. [对 Clade 的可借鉴模式](#15-对-clade-的可借鉴模式)

---

## 1. E2B 概览

E2B (Execute to Build) 是一个开源的 AI agent 云沙盒基础设施，核心价值主张：**让 AI 生成的代码在安全隔离的环境中执行**。

- **GitHub Stars**: 11,500+ (2026-03)
- **语言**: 主要 Python + Go (infra)
- **底层技术**: Firecracker microVM + KVM
- **许可证**: Apache 2.0
- **生态定位**: AI 代码执行的事实标准，Manus、Claude Code 等均采用

### 核心价值

```
传统 Docker 容器          E2B Firecracker microVM
─────────────────         ───────────────────────
共享主机内核               独立内核 (真正隔离)
容器逃逸风险               硬件级虚拟化边界
10-20s 冷启动             ~150ms 启动 (快照后 28ms)
较高攻击面                 极小攻击面 (50k 行 Rust)
```

---

## 2. E2B SDK 核心接口

### Python SDK 核心类: `AsyncSandbox`

```python
from e2b import AsyncSandbox

# ─── 创建沙盒 ───
sandbox = await AsyncSandbox.create(
    template="base",          # 模板名称或 ID
    timeout=3600,             # 超时秒数 (Pro 最大 86400)
    metadata={"user": "uid"}, # 自定义元数据
    envs={"KEY": "value"},    # 环境变量
    secure=True,              # 需要访问令牌
    allow_internet_access=True
)

# ─── 命令执行 ───
result = await sandbox.commands.run(
    "pip install numpy",
    cwd="/home/user",
    timeout=60,
    on_stdout=lambda d: print(d),
    on_stderr=lambda d: print(d)
)
print(result.stdout, result.exit_code)

# 后台进程
handle = await sandbox.commands.run("python server.py", background=True)
await handle.wait()

# PTY 交互式终端
pty = await sandbox.pty.create(
    size=PtySize(cols=80, rows=24),
    on_data=lambda data: print(data)
)

# ─── 文件系统 ───
await sandbox.files.write("/path/to/file.py", "print('hello')")
content = await sandbox.files.read("/path/to/file.py")
entries = await sandbox.files.list("/home/user", depth=2)
watch = await sandbox.files.watch_dir("/workspace", on_event=callback)

# ─── 生命周期管理 ───
info = await sandbox.get_info()
metrics = await sandbox.get_metrics()
await sandbox.set_timeout(7200)
await sandbox.kill()

# ─── 暂停/恢复 (Beta) ───
await sandbox.beta_pause()                   # 保存完整内存+文件系统状态
same_sbx = await AsyncSandbox.connect(       # 自动恢复已暂停沙盒
    sandbox_id=sandbox.sandbox_id
)
```

### JavaScript/TypeScript SDK

```typescript
import { Sandbox } from 'e2b'

const sandbox = await Sandbox.create({
  template: 'base',
  timeoutMs: 60_000,
  onStdout: (data) => console.log(data.line),
})

const result = await sandbox.commands.run('echo "Hello"')
console.log(result.stdout)  // Hello

// 文件操作
await sandbox.files.write('/hello.txt', 'world')
const content = await sandbox.files.read('/hello.txt')

// Code Interpreter SDK (专门用于代码执行)
import { Sandbox } from '@e2b/code-interpreter'
const sbx = await Sandbox.create()
const execution = await sbx.runCode('x = 1 + 1; x')
console.log(execution.text)  // 2
```

### 列出 / 管理所有沙盒

```python
# 列出运行中的沙盒
paginator = await AsyncSandbox.list(query={"state": ["running"]})
sandboxes = await paginator.next_items()

# 列出已暂停的沙盒
paused = await AsyncSandbox.list(query={"state": ["paused"]})
```

---

## 3. 沙盒生命周期

```
                    create()
                       │
                       ▼
              ┌─────────────────┐
              │    Running      │◄────────────────────┐
              │  (初始状态)      │                     │
              └────────┬────────┘                     │
                       │                              │ connect()
               beta_pause()                           │ (auto-resume)
                       │                              │
                       ▼                              │
              ┌─────────────────┐                     │
              │    Paused       │─────────────────────┘
              │  (文件+内存保存) │
              └────────┬────────┘
                       │
                  kill() / 手动
                       │
                       ▼
              ┌─────────────────┐
              │    Killed       │
              │  (资源释放)      │
              └─────────────────┘
```

### 关键生命周期参数

| 状态 | 描述 | 计费 |
|------|------|------|
| Running | 正常执行，CPU/内存活跃 | 按秒计费 |
| Paused | 快照保存，暂停执行 | 不计费 |
| Killed | 终态，资源释放 | 不计费 |

### 超时策略

```python
# 自动暂停 (而非销毁) on timeout
sandbox = await AsyncSandbox.beta_create(
    template="base",
    timeout=300,         # 5分钟无操作
    auto_pause=True      # 超时后暂停而非 kill
)
```

### 生命周期限制

| 计划 | 最大持续运行时间 | 并发沙盒 |
|------|---------------|---------|
| Hobby (免费) | 1 小时 | 20 |
| Pro ($150/月) | 24 小时 | 100-1100 |
| Enterprise | 自定义 | 1100+ |

注: pause/resume 循环可重置运行时计时器。

---

## 4. 文件系统与持久化

### 跨 Session 持久化机制

E2B 提供两种持久化路径：

**路径 1: Pause/Resume (内存快照)**
```
暂停时: 整个文件系统 + 进程内存 → 快照文件
恢复时: 从快照还原 (≈1 秒)
适用场景: 有状态 agent，需要保留运行时状态
```

**路径 2: 挂载云存储 (FUSE 协议)**
```python
# 支持: Amazon S3, Google Cloud Storage, Cloudflare R2
sandbox = await AsyncSandbox.create(
    template="base",
    envs={
        "STORAGE_BUCKET": "my-bucket",
        "STORAGE_PATH": "/workspace"
    }
)
```

### 文件操作 API 完整参考

```python
# 读取 (支持 text/bytes/stream)
text = await sandbox.files.read("/path", format="text")
raw  = await sandbox.files.read("/path", format="bytes")
stream = await sandbox.files.read("/path", format="stream")

# 写入
info = await sandbox.files.write("/path", "content")
infos = await sandbox.files.write_files([
    {"path": "/a.txt", "data": "hello"},
    {"path": "/b.txt", "data": "world"},
])

# 目录操作
await sandbox.files.make_dir("/workspace/output")
entries = await sandbox.files.list("/workspace", depth=2)

# 监控文件变化
async def on_event(event):
    print(f"{event.type}: {event.path}")

watcher = await sandbox.files.watch_dir(
    "/workspace",
    on_event=on_event,
    recursive=True
)

# 删除/重命名
await sandbox.files.remove("/tmp/old_file")
await sandbox.files.rename("/old", "/new")
```

### 已知限制 (Beta)

Pause/Resume 存在 bug: 沙盒多次 pause/resume 循环后，文件变更可能不被保留 (issue #884)。生产环境建议额外配合云存储挂载。

---

## 5. 网络隔离策略

### 默认行为
- 互联网访问: **默认开启**
- 端口监听: 支持，可通过 SDK 访问

### 细粒度网络控制

```python
# 完全禁用互联网访问
sandbox = await AsyncSandbox.create(
    allow_internet_access=False
)

# 细粒度域名过滤 (仅 HTTP 80 + HTTPS 443 via SNI)
sandbox = await AsyncSandbox.create(
    network={
        "allowOut": ["api.openai.com", "pypi.org"],
        "denyOut": ["0.0.0.0/0"]  # CIDR 支持
    }
)
```

### 网络架构原理

```
沙盒内部 (guest)            主机侧
─────────────────           ─────────────────
eth0 (virtio-net)    ──►    TAP 接口
                     ──►    NAT 转发
vsock (AF_VSOCK)     ──►    Unix socket
                            (无 IP, 无端口, 无路由)
```

vsock 是核心通信通道: 沙盒和主机之间没有传统网络栈，guest 内的 agent 通过 virtio socket 直接与主机通信，**消除了整个网络攻击面**。

---

## 6. 模板系统 (Templates)

### 模板的本质

模板 = **一个预先启动并快照的 microVM 状态**。

关键洞察: "The process is already running when you create a sandbox from that template" — 模板捕获的是**完成初始化后的运行状态**，而非构建指令。

### Build System 2.0 (代码化模板)

```python
# 不再需要 Dockerfile — 直接用代码定义
from e2b import Template

template = (
    Template()
    .from_image("node:24")           # 基础镜像
    .copy("src/", ".")               # 复制文件
    .run_cmd("npm install")          # 执行安装
    .set_envs({"NODE_ENV": "prod"})  # 环境变量
    .set_start_cmd("node server.js") # 启动命令
    .wait_for_timeout(5_000)         # 等待就绪
)

# 构建并发布 (支持 CPU/内存规格)
await template.build(
    cpu_count=2,
    memory_mb=2048,
    template_id="my-template"
)
```

### Dockerfile 方式 (旧版)

```dockerfile
# e2b.Dockerfile
FROM ubuntu:22.04
RUN apt-get update && apt-get install -y python3 nodejs
COPY requirements.txt .
RUN pip install -r requirements.txt
# E2B CLI 将此 Dockerfile 转换为 microVM 快照
```

```bash
# 构建模板
e2b template build --name my-template --cpu-count 2 --memory-mb 2048

# 使用模板
sandbox = await AsyncSandbox.create(template="my-template")
```

### 转换流程: Dockerfile → microVM

```
Dockerfile
    │
    ▼ e2b template build
Docker Image 构建
    │
    ▼ E2B 内部转换
rootfs 提取 → Firecracker microVM 启动 → 完成初始化
    │
    ▼ Pause + Snapshot
microVM 快照文件 (内存 + CPU 状态 + 文件系统)
    │
    ▼ 分发到各节点缓存
create() → CoW 复制 → 28ms 恢复 → Running
```

Build System 2.0 声称缓存命中时构建速度提升 **14x**。

---

## 7. E2B 计费模型

### 定价单位

| 资源 | 价格 |
|------|------|
| vCPU | $0.0504/vCPU·小时 |
| 内存 | $0.0162/GiB·小时 |
| 计费粒度 | 按秒 |
| 暂停状态 | 不计费 |

### 实际成本示例

```
标准配置 (2 vCPU, 2 GiB RAM):
  = 2 × $0.0504 + 2 × $0.0162
  = $0.1008 + $0.0324
  = $0.1332 / 小时
  ≈ $0.037 / 1000 沙盒·秒
```

### 计费模型揭示的使用模式

1. **按秒计费** → 推动 pause/resume 设计，agent 不工作时应暂停沙盒
2. **内存定价** → 沙盒尽量轻量化 (Firecracker <5MB overhead 的价值)
3. **并发限制** → 不同计划的 agent 并行度上限不同
4. **暂停不计费** → 长期有状态 agent 可低成本保活

---

## 8. 与 Claude Code / AI Agent 的集成

### Claude Code 官方 E2B 模板

```python
# 在 E2B 沙盒里运行 Claude Code agent
from e2b import AsyncSandbox

sandbox = await AsyncSandbox.create(
    template="claude-code",           # 官方预构建模板
    envs={
        "ANTHROPIC_API_KEY": api_key
    },
    timeout=0                         # 0 = 不超时 (长任务)
)

# 在沙盒内运行 Claude
result = await sandbox.commands.run(
    "claude --dangerously-skip-permissions -p 'Create a hello world index.html'",
    timeout=300
)
print(result.stdout)
```

### Claude Code 的原生沙盒 (`@anthropic-ai/sandbox-runtime`)

Claude Code 自身也内置了沙盒机制 (完全独立于 E2B):

```json
// ~/.claude/settings.json
{
  "sandbox": {
    "enabled": true,
    "filesystem": {
      "allowWrite": ["~/projects", "/tmp"],
      "denyRead": ["~/.ssh", "~/.aws"]
    },
    "network": {
      "allowedDomains": ["api.anthropic.com", "github.com"],
      "httpProxyPort": 8080
    }
  }
}
```

| 特性 | Claude Code 原生沙盒 | E2B 沙盒 |
|------|---------------------|---------|
| 底层技术 | bubblewrap (Linux) / Seatbelt (macOS) | Firecracker microVM |
| 隔离级别 | OS namespace | 硬件虚拟化 |
| 独立内核 | 否 | 是 |
| 启动开销 | <1ms | ~150ms |
| 跨 session 持久化 | 否 | 是 (pause/resume) |
| 适用场景 | 本地开发保护 | 云端不可信代码执行 |

### Manus 的集成模式

Manus 是最典型的 E2B 使用案例:

```
用户请求
    │
    ▼
Planner Agent (任务分解)
    │
    ├── Executor Agent 1 ──► E2B Sandbox 1
    ├── Executor Agent 2 ──► E2B Sandbox 2  
    └── Executor Agent N ──► E2B Sandbox N
              │
              ▼
        27 种工具 (浏览器/文件/终端)
              │
              ▼
        持久化 session (数小时)
```

Manus 的选择依据: Docker 冷启动 10-20s 且缺少完整 OS 能力，E2B 提供 ~150ms 启动 + 完整 Linux 环境。

---

## 9. Firecracker microVM 深度解析

### 架构概述

Firecracker 是由 AWS 开发的 VMM (Virtual Machine Monitor)，基于 KVM，用 Rust 编写。每个 Firecracker 进程对应一个 microVM，包含三类线程:

```
Firecracker 进程
├── API 线程        ← 控制平面，接受 REST API 请求 (Unix socket)
├── VMM 线程        ← 设备模拟 (virtio net/block/vsock)
└── vCPU 线程(s)    ← 客户机代码执行 (最多 32 vCPU)
```

### 核心设计原则

**最小化设备集** — Firecracker 只模拟必要设备：

```
支持的设备:
├── virtio-net    (网络)
├── virtio-block  (磁盘)
├── virtio-vsock  (vsock 通信)
├── virtio-rng    (随机数)
└── virtio-balloon (内存气球)

不支持:
├── USB
├── GPU
├── PCI 设备 (默认)
├── BIOS
└── 传统硬件仿真
```

**结果**: 攻击面极小，仅 ~50,000 行 Rust 代码 (vs QEMU 近 200 万行 C 代码)。

### 性能对比数据

| 指标 | Firecracker | QEMU MicroVM | QEMU Standard | Docker |
|------|-------------|-------------|---------------|--------|
| 冷启动时间 | ~125ms | ~375ms | ~1250ms | ~1000ms |
| 快照恢复 | **28ms** | N/A | N/A | N/A |
| 内存开销 | <5 MiB | ~50 MiB | ~128 MiB | ~128 MiB |
| 代码量 | 50k 行 Rust | 2M 行 C | 2M 行 C | - |
| 隔离级别 | 硬件虚拟化 | 硬件虚拟化 | 硬件虚拟化 | 内核命名空间 |

### Firecracker REST API

所有操作通过 Unix socket 的 HTTP API 完成:

```bash
# 1. 启动 Firecracker
./firecracker --api-sock /tmp/firecracker.socket

# 2. 配置 boot source
curl --unix-socket /tmp/firecracker.socket \
  -X PUT 'http://localhost/boot-source' \
  -d '{"kernel_image_path": "/vmlinux", "boot_args": "console=ttyS0 reboot=k"}'

# 3. 配置 rootfs
curl --unix-socket /tmp/firecracker.socket \
  -X PUT 'http://localhost/drives/rootfs' \
  -d '{"drive_id": "rootfs", "path_on_host": "/root.ext4", "is_root_device": true}'

# 4. 配置网络
curl --unix-socket /tmp/firecracker.socket \
  -X PUT 'http://localhost/network-interfaces/eth0' \
  -d '{"iface_id": "eth0", "guest_mac": "AA:FC:00:00:00:01", "host_dev_name": "tap0"}'

# 5. 启动
curl --unix-socket /tmp/firecracker.socket \
  -X PUT 'http://localhost/actions' \
  -d '{"action_type": "InstanceStart"}'
```

---

## 10. Snapshot/Restore 原理 — 28ms 启动的关键

这是整个技术栈最重要的 key insight。

### 传统启动 vs 快照恢复

```
传统冷启动 (~1000ms):
Firecracker 启动 → 内核加载 → 根文件系统挂载 → init 进程 → 服务启动 → agent 就绪

快照恢复 (~28ms):
找到快照文件 → CoW 复制 → 恢复内存映射 → 恢复 CPU 状态 → vsock 重连 → 就绪
```

### 快照的物理构成

```
snapshot/
├── memory.bin       ← 完整内存内容 (使用 MAP_PRIVATE 延迟加载)
├── vmstate.json     ← CPU 寄存器、设备状态、KVM 状态
└── disk.ext4        ← 磁盘 (用户自管理，通常 CoW 共享)
```

### 关键技术: MAP_PRIVATE 内存映射

```
传统方式: 快照 → 磁盘 → 恢复时全部读入内存 (慢)

Firecracker 方式:
  快照文件 ──MAP_PRIVATE──► 虚拟地址空间
                             │
                             ▼ 缺页时才真正读取 (lazy)
                        实际物理内存
```

**效果**: 恢复瞬间只需建立内存映射关系，不需要实际读取任何数据。VM 从快照点立即"醒来"，缺页中断按需加载内存页。

### 28ms 时间分解 (ForgeVM 实测)

```
~5ms   Firecracker 进程初始化
~8ms   内存快照文件 memory-mapping
~10ms  CPU 和设备状态恢复
~5ms   vsock 重连 + agent 就绪确认
─────
28ms   总计
```

### 预热 (Pre-warming) 技术

```python
# 概念伪代码 — E2B 的实际实现
class SandboxPool:
    def __init__(self, template_id: str, pool_size: int = 10):
        self.warm_pool: list[FirecrackerVM] = []
        self._prefill(template_id, pool_size)

    def _prefill(self, template_id: str, n: int):
        # 预先从模板快照创建 N 个 CoW 副本
        for _ in range(n):
            vm = FirecrackerVM.restore_from_snapshot(
                snapshot=TEMPLATE_SNAPSHOTS[template_id],
                cow=True  # 写时复制，共享只读基础快照
            )
            self.warm_pool.append(vm)

    async def acquire(self) -> FirecrackerVM:
        if self.warm_pool:
            vm = self.warm_pool.pop()
            asyncio.create_task(self._refill_one())
            return vm                    # 几乎 0 延迟
        return FirecrackerVM.restore_from_snapshot(...)  # fallback ~28ms
```

### Snapshot API 操作序列

```bash
# 1. 暂停运行中的 VM
curl --unix-socket /tmp/firecracker.socket \
  -X PATCH 'http://localhost/vm' \
  -d '{"state": "Paused"}'

# 2. 创建快照
curl --unix-socket /tmp/firecracker.socket \
  -X PUT 'http://localhost/snapshot/create' \
  -d '{
    "snapshot_type": "Full",
    "snapshot_path": "./vmstate.snap",
    "mem_file_path": "./mem.snap"
  }'

# 3. 恢复 (新进程)
curl --unix-socket /tmp/firecracker.socket \
  -X PUT 'http://localhost/snapshot/load' \
  -d '{
    "snapshot_path": "./vmstate.snap",
    "mem_backend": {
      "backend_type": "File",
      "backend_path": "./mem.snap"
    },
    "vsock_override": {"uds_path": "./new-v.sock"}
  }'
```

### 安全注意事项

**同一快照不能恢复多次** (安全风险): 加密 token、随机数种子等唯一性标识会在 clone 间重复。

解决方案:
1. **VMGenID 设备**: 每次恢复时暴露变化的 16 字节标识符，触发 guest 重新初始化 PRNG (需 Linux 5.18+)
2. **正确模式**: 创建快照 → 终止原始 VM → 从快照加载一次 (不复用)

---

## 11. vsock 通信机制

vsock 是 Firecracker 中 agent-host 通信的核心通道。

### 技术本质

```
传统网络:      Guest eth0 ──► Host TAP ──► IP 路由
vsock:        Guest AF_VSOCK ──► virtio ──► Host AF_UNIX
```

**关键区别**: vsock 绕过网络栈，直接内核间通道，没有 IP 地址、没有端口（vsock port 是独立命名空间）、没有路由表。

### 配置

```bash
# 在 Firecracker 启动时配置
curl --unix-socket /tmp/firecracker.socket \
  -X PUT 'http://localhost/vsock' \
  -d '{
    "guest_cid": 3,
    "uds_path": "./v.sock"
  }'
```

### 连接模式

**Host → Guest (host 发起)**:
```
主机连接 ./v.sock → 发送 "CONNECT 8080\n" → Firecracker 转发 → guest 内的 8080 端口
← 收到 "OK 49152\n" (已分配的主机侧端口)
```

**Guest → Host (guest 发起)**:
```
guest 进程连接 vsock CID=2 port=3000 → Firecracker 转发 → ./v.sock_3000 (主机 Unix socket)
```

### 在 Agent 架构中的典型用法

```
┌─────────────────────────────────────┐
│          Firecracker microVM        │
│                                     │
│  ┌─────────────────────────────┐   │
│  │  agent process (PID 1)      │   │
│  │  - 执行 LLM 指令            │   │
│  │  - 监听 vsock port 8888     │   │
│  └────────────┬────────────────┘   │
│               │ AF_VSOCK           │
└───────────────┼─────────────────────┘
                │ virtio vsock
┌───────────────┼─────────────────────┐
│   Host        │                     │
│  ┌────────────▼────────────────┐   │
│  │  orchestrator               │   │
│  │  - 监听 ./v.sock            │   │
│  │  - 发送命令: run/stop/status │   │
│  │  - 流式获取 stdout/stderr    │   │
│  └─────────────────────────────┘   │
└─────────────────────────────────────┘
```

### 优势

1. **安全**: 无网络栈暴露，不可通过 IP 直接攻击
2. **性能**: 零网络开销，直接内存通道
3. **简洁**: Guest agent 不需要网络配置
4. **隔离**: 每个 VM 有独立的 vsock 路径，不可互相访问

---

## 12. Jailer 安全层

Jailer 是 Firecracker 的安全包装器，建立多层隔离屏障。

### Jailer 执行序列

```
jailer 进程 (以 root 运行)
│
├── 1. 验证参数 (VM ID 格式, 路径合法性)
├── 2. 关闭所有继承的文件描述符 (stdin/out/err 除外)
├── 3. 清除所有环境变量
├── 4. 创建 chroot 目录: <base>/<exec_name>/<vm_id>/root/
├── 5. 复制 Firecracker 二进制到 chroot (防内存共享)
├── 6. 设置 resource limits (fsize, no-file=2048)
├── 7. 创建 cgroup 子目录 + 写入约束值
├── 8. mount namespace (unshare) + pivot_root
├── 9. 创建 /dev/kvm, /dev/net/tun (受限所有权)
├── 10. 可选: 加入 network namespace (--netns)
├── 11. 可选: 创建新 PID namespace (--new-pid-ns)
├── 12. 降权: setuid/setgid 到指定 uid/gid
└── 13. exec → Firecracker 二进制 (携带时间元数据)
```

### Cgroup 资源约束

```bash
# 启动 Jailer 示例
./jailer \
  --id vm-abc123 \
  --exec-file /usr/bin/firecracker \
  --uid 1000 --gid 1000 \
  --chroot-base-dir /srv/jailer \
  --cgroup-version 2 \
  --cgroup cpuset.cpus=0-3 \
  --cgroup memory.max=2G \
  --cgroup cpu.weight=100 \
  --netns /var/run/netns/vm-abc123 \
  --new-pid-ns \
  -- \
  --api-sock /tmp/firecracker.socket
```

### 隔离层次

```
Layer 1: KVM 硬件虚拟化         (CPU/内存隔离)
Layer 2: seccomp 过滤           (系统调用白名单)
Layer 3: chroot + pivot_root    (文件系统隔离)
Layer 4: mount namespace        (挂载点隔离)
Layer 5: network namespace      (网络隔离)
Layer 6: PID namespace          (进程隔离)
Layer 7: cgroup v2              (资源限制)
Layer 8: 权限降级 (uid/gid)     (最小权限)
```

---

## 13. 沙盒隔离技术对比

### 三大技术路线全面对比

| 维度 | Docker/runc | gVisor | Firecracker microVM |
|------|------------|--------|---------------------|
| **隔离机制** | Linux 命名空间 + cgroup | 用户态内核拦截 syscall | KVM 硬件虚拟化 |
| **内核共享** | 共享主机内核 | 独立用户态内核 | 独立完整内核 |
| **内核逃逸风险** | 高 (CVE 频发) | 中 (用户态 shim) | 极低 (硬件隔离) |
| **冷启动时间** | ~100ms | ~200ms | ~125ms |
| **快照恢复** | 不支持 | 不支持 | **28ms** |
| **内存开销** | ~128 MiB | ~100 MiB | **<5 MiB** |
| **并发密度** | 高 | 中 | 极高 (低开销) |
| **syscall 兼容性** | 完全 | 约 237/341 个 | 完全 |
| **GPU 支持** | 是 | 有限 | 否 (默认) |
| **网络性能** | 高 | 中 | 中高 |
| **攻击面** | 大 | 中 | 极小 (50k 行) |
| **使用者** | 通用 | Modal, GKE | E2B, AWS Lambda, Fargate |

### 隔离强度谱系

```
弱 ─────────────────────────────────────────────── 强
│
Docker   │  gVisor    │  Firecracker  │  Confidential
容器      │  用户态内核 │  microVM      │  Computing
(Level 1) │ (Level 2)  │ (Level 3)    │  (Level 5)
         │            │               │
共享内核  │  syscall   │  独立内核      │  加密内存
         │  拦截层     │  硬件边界      │  (AMD SEV-SNP)
```

### 启动时间实测对比 (各沙盒平台)

| 平台 | 技术 | 冷启动 | 快照恢复 |
|------|------|--------|---------|
| Zeroboot | Firecracker CoW fork | 0.79ms | - |
| E2B | Firecracker | ~150ms | ~28ms |
| Daytona | Docker | ~90ms | - |
| Modal | gVisor | ~200ms | - |
| Northflank | gVisor | ~1000ms | - |

### 内存密度对比

```
每 GB 主机内存可运行的沙盒数:
Zeroboot (CoW fork):  ~3800 个 (265 KB/沙盒)
Firecracker:          ~200 个 (5 MB/沙盒)
Docker:               ~8 个 (128 MB/沙盒)
```

---

## 14. AI Agent 场景中的应用现状

### E2B 在 AI Agent 生态的地位

```
谁在用 E2B?
├── Manus        (multi-agent 自主 AI)
├── Claude Code  (Anthropic 官方集成模板)
├── Cursor       (AI 代码编辑器)
├── OpenClaw     (AI dev agent)
└── 数百个 agent 框架
```

**Manus 联合创始人引言**: "E2B was the best solution, and it looked like every company was using it."

### AWS Lambda / Fargate 的 Firecracker 使用

AWS 是 Firecracker 的创始者，将其用于:
- Lambda: 每次函数调用启动独立 microVM
- Fargate: 每个容器任务在 microVM 中运行
- 规模: 每秒支持数百万并发 microVM

### Microsandbox (新兴挑战者)

```
特点:
├── 自托管, 本地优先
├── libkrun microVM (而非 Firecracker)
├── <200ms 启动
├── Rust 编写
├── Apache 2.0 许可
└── 网络层 secret 注入 (TLS proxy)
```

核心差异: 凭证永不离开本机，适合高安全本地 agent。

### 三层架构市场分层

```
Layer 1: 原语层 (自建 12 个月+)
  Firecracker, gVisor, Cloud Hypervisor

Layer 2: 可嵌入运行时 (天级集成)
  E2B (云托管), Microsandbox (自托管)

Layer 3: 托管平台 (小时级集成)
  Modal, Northflank, Daytona (全托管, 含 GPU)
```

---

## 15. 对 Clade 的可借鉴模式

### 当前 Clade 的 Agent 执行模型

Clade 的 worker 通过 Claude Code CLI 在 git worktree 中执行任务:

```
WorkerPool → spawn Claude Code subprocess → git worktree → 任务执行
```

现存问题:
1. **无隔离**: worker 直接访问主机文件系统，并发写冲突风险
2. **无资源限制**: 失控 worker 可以耗尽 CPU/内存
3. **无网络控制**: worker 可以访问任意网络资源
4. **无 snapshot**: 每次任务从零开始，无法利用缓存状态

### 借鉴路径分析

#### 路径 A: 集成 E2B SDK (云端)

```python
# worker.py 改造示意
from e2b import AsyncSandbox

async def run_worker_in_sandbox(task: Task, repo_path: str) -> WorkerResult:
    async with AsyncSandbox.create(
        template="claude-code",         # 预装 Claude Code 的模板
        timeout=task.timeout or 3600,
        allow_internet_access=False,    # 默认断网
        envs={
            "ANTHROPIC_API_KEY": settings.api_key,
            "TASK_ID": task.id,
        }
    ) as sandbox:
        # 上传代码库
        await upload_repo(sandbox, repo_path)

        # 执行 Claude Code
        result = await sandbox.commands.run(
            f"claude --dangerously-skip-permissions -p '{task.prompt}'",
            timeout=task.timeout,
            on_stdout=lambda d: stream_output(task.id, d),
        )

        # 收集产物
        artifacts = await collect_artifacts(sandbox)
        return WorkerResult(output=result.stdout, artifacts=artifacts)
```

**优势**: 最快集成 (天级)，开箱即用的隔离  
**代价**: $0.13/小时/worker，需要云访问

#### 路径 B: 自托管 Microsandbox (本地)

```bash
# 在 Aries 服务器上部署 Microsandbox
microsandbox server start --port 7080 --bind 127.0.0.1

# Clade worker 通过 microsandbox API 创建沙盒
microsandbox run \
  --image claude-code:latest \
  --memory 2g --cpus 2 \
  --secret ANTHROPIC_API_KEY \
  -- claude --dangerously-skip-permissions -p "..."
```

**优势**: 数据不离本机，无 API 费用  
**代价**: 自己维护 infra，需要 KVM 支持

#### 路径 C: 轻量级进程隔离 (最简方案)

不引入 microVM，利用 Claude Code 原生沙盒:

```json
// worker 启动时注入的 .claude/settings.json
{
  "sandbox": {
    "enabled": true,
    "filesystem": {
      "allowWrite": ["./worktree-<task-id>"],
      "denyRead": ["~/.ssh", "~/.aws", "~/.config"]
    },
    "network": {
      "allowedDomains": ["api.anthropic.com", "github.com", "pypi.org"]
    }
  }
}
```

**优势**: 零额外基础设施，立即可用  
**代价**: 仅 OS namespace 级别，非硬件隔离

### 推荐的 Snapshot 借鉴模式

Clade 的 worker 有大量重复的"初始化"工作 (安装依赖、读取代码库)。Firecracker snapshot 的 pre-warming 思路可以转化为:

```python
# 概念: Worker State Cache
class WorkerStateCache:
    """
    类比 Firecracker pre-warming:
    - 预先创建一批"已初始化"的 worker 状态
    - 新任务直接从缓存状态启动，跳过初始化
    """

    async def warm_for_repo(self, repo_path: str) -> CachedState:
        # 创建 worktree + 安装依赖 (一次性)
        state = await WorkerState.initialize(repo_path)
        # 序列化到磁盘 (类比 memory snapshot)
        return await state.checkpoint()

    async def create_worker(self, task: Task) -> Worker:
        cached = await self.get_or_warm(task.repo)
        # CoW 复制 worktree (类比 snapshot CoW)
        return Worker.from_checkpoint(cached, task)
```

### Key Insights 总结

1. **Snapshot > 重建**: 快照恢复比重新初始化快 10-100x。Clade 的 task 执行可以用 "pre-warmed worktree" 类比这个模式。

2. **vsock 模式 = Clade 的 session-context 模式**: vsock 的本质是"host 通过专用通道控制 guest agent"，这正是 Clade 的 loop-runner → worker subprocess 模式。可以将 worker 输出流/状态上报标准化为类似协议。

3. **隔离 = 信任边界**: 未来 Clade 如果要支持"运行用户提供的代码"或"多租户 agent"，microVM 级别的隔离是必要的，而非 Docker 容器。

4. **pause/resume = 长 session agent**: Clade 的 loop 可以设计为 pause-able——完成一个 sprint 后暂停 worker 状态，下次 sprint 继续，而非每次从头克隆仓库。

5. **计费模型反映设计**: E2B 按秒计费 + 暂停不计费 → Clade worker 也应该设计为"不工作时释放资源"，而非让 worker 长时间 idle 等待。

---

## 附录: 进一步研究资源

- [E2B 基础设施源码](https://github.com/e2b-dev/infra) — Go 实现，含 Firecracker 编排逻辑
- [Firecracker 快照文档](https://github.com/firecracker-microvm/firecracker/blob/main/docs/snapshotting/snapshot-support.md)
- [Jailer 文档](https://github.com/firecracker-microvm/firecracker/blob/main/docs/jailer.md)
- [vsock 文档](https://github.com/firecracker-microvm/firecracker/blob/main/docs/vsock.md)
- [28ms 沙盒启动实现 (ForgeVM)](https://dev.to/adwitiya/how-i-built-sandboxes-that-boot-in-28ms-using-firecracker-snapshots-i0k)
- [Microsandbox GitHub](https://github.com/microsandbox/microsandbox)
- [AI Agent 沙盒隔离技术对比 (2026)](https://manveerc.substack.com/p/ai-agent-sandboxing-guide)
- [E2B 自托管指南](https://github.com/e2b-dev/infra/blob/main/self-host.md)
