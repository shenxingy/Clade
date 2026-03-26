#!/bin/bash
# memory-watchdog.sh — 内存压力过高时自动杀掉 claude worker 进程，防止死机
#
# 用法:
#   启动:  nohup ~/.claude/scripts/memory-watchdog.sh &
#   停止:  kill $(cat /tmp/memory-watchdog.pid)
#
# 工作原理:
#   每 15 秒检查一次内存使用率。
#   当使用率超过阈值时:
#     1. 先发 SIGTERM 给最老的 claude -p worker（优雅退出）
#     2. 等 10 秒，如果内存仍然高，继续杀下一个
#     3. 如果阈值极高（>95%），直接 SIGKILL
#
# 可通过环境变量覆盖默认值:
#   MEM_WARN_THRESHOLD=80  — 开始告警的阈值（%）
#   MEM_KILL_THRESHOLD=88  — 开始杀进程的阈值（%）
#   MEM_EMERGENCY=95       — 紧急 SIGKILL 阈值（%）
#   CHECK_INTERVAL=15      — 检查间隔（秒）

set -euo pipefail

MEM_WARN_THRESHOLD="${MEM_WARN_THRESHOLD:-80}"
MEM_KILL_THRESHOLD="${MEM_KILL_THRESHOLD:-88}"
MEM_EMERGENCY="${MEM_EMERGENCY:-95}"
CHECK_INTERVAL="${CHECK_INTERVAL:-15}"
PID_FILE="/tmp/memory-watchdog.pid"
LOG_FILE="/tmp/memory-watchdog.log"

# 写入 PID 文件
echo $$ > "$PID_FILE"

log() {
  echo "$(date '+%Y-%m-%d %H:%M:%S') $1" | tee -a "$LOG_FILE"
}

# 获取内存使用百分比（macOS）
get_mem_usage() {
  # vm_stat 输出页面信息，page size 16384 on Apple Silicon
  local page_size=$(sysctl -n hw.pagesize)
  local pages_free=$(vm_stat | awk '/Pages free/ {gsub(/\./,"",$3); print $3}')
  local pages_inactive=$(vm_stat | awk '/Pages inactive/ {gsub(/\./,"",$3); print $3}')
  local pages_speculative=$(vm_stat | awk '/Pages speculative/ {gsub(/\./,"",$3); print $3}')
  local mem_total=$(sysctl -n hw.memsize)

  local free_bytes=$(( (pages_free + pages_inactive + pages_speculative) * page_size ))
  local used_pct=$(( 100 - (free_bytes * 100 / mem_total) ))

  echo "$used_pct"
}

# 获取 claude -p worker 的 PID 列表（按启动时间从老到新排序）
get_worker_pids() {
  pgrep -f "claude.*-p" 2>/dev/null | head -20 || true
}

# 杀掉最老的一个 worker
kill_oldest_worker() {
  local sig="${1:-TERM}"
  local pids
  pids=$(get_worker_pids)

  if [[ -z "$pids" ]]; then
    log "  无 claude worker 进程可杀"
    return 1
  fi

  local oldest_pid
  oldest_pid=$(echo "$pids" | head -1)
  log "  发送 SIG${sig} 到 PID $oldest_pid"
  kill -"$sig" "$oldest_pid" 2>/dev/null || true
  return 0
}

log "=== Memory watchdog 启动 ==="
log "  告警阈值: ${MEM_WARN_THRESHOLD}%  杀进程: ${MEM_KILL_THRESHOLD}%  紧急: ${MEM_EMERGENCY}%"
log "  检查间隔: ${CHECK_INTERVAL}s"
log "  PID: $$"

while true; do
  usage=$(get_mem_usage)

  if (( usage >= MEM_EMERGENCY )); then
    log "[EMERGENCY] 内存 ${usage}% >= ${MEM_EMERGENCY}%，强制杀进程"
    kill_oldest_worker KILL
    sleep 5
    # 如果还是高，继续杀
    usage=$(get_mem_usage)
    if (( usage >= MEM_EMERGENCY )); then
      log "[EMERGENCY] 仍然 ${usage}%，继续杀"
      kill_oldest_worker KILL
    fi

  elif (( usage >= MEM_KILL_THRESHOLD )); then
    log "[KILL] 内存 ${usage}% >= ${MEM_KILL_THRESHOLD}%，优雅终止 worker"
    kill_oldest_worker TERM
    sleep 10

  elif (( usage >= MEM_WARN_THRESHOLD )); then
    log "[WARN] 内存 ${usage}% >= ${MEM_WARN_THRESHOLD}%，暂不动作"
  fi

  sleep "$CHECK_INTERVAL"
done
