#!/usr/bin/env bash
# pipeline-check.sh — Health check for registered background pipelines
#
# Usage: pipeline-check.sh [project-filter]
#
# Reads ~/.claude/pipeline-registry.yml for registered project paths.
# For each project, reads PROJECT/.claude/pipeline.yml and runs checks.
# Output: STATUS|project_name|pipeline_name|detail  (one line per pipeline)
#
# STATUS values: HEALTHY, DEGRADED, DEAD, UNKNOWN
# If project-filter is given, only process matching projects (case-insensitive substring).

set -euo pipefail

REGISTRY="$HOME/.claude/pipeline-registry.yml"
FILTER="${1:-}"

# ─── YAML Parsing Helpers ─────────────────────────────────────────────────────

# Extract a scalar value from simple YAML: key: value
# Usage: _yaml_get FILE KEY
_yaml_get() {
  local file="$1" key="$2"
  grep -E "^[[:space:]]*${key}[[:space:]]*:" "$file" 2>/dev/null \
    | head -1 \
    | sed 's/^[^:]*:[[:space:]]*//' \
    | tr -d '"'"'" \
    | tr -d '\r'
}

# Extract list items under a key (lines starting with "  - " after the key block)
# Uses python3 for reliable YAML list parsing
# Usage: _yaml_list FILE KEY
_yaml_list() {
  local file="$1" key="$2"
  python3 - "$file" "$key" <<'PYEOF' 2>/dev/null || true
import sys, re

filepath, target_key = sys.argv[1], sys.argv[2]
with open(filepath) as f:
    lines = f.readlines()

in_block = False
indent = None
for line in lines:
    stripped = line.rstrip()
    if re.match(r'^' + re.escape(target_key) + r'\s*:', stripped):
        in_block = True
        indent = None
        continue
    if in_block:
        if not stripped:
            continue
        m = re.match(r'^(\s+)-\s+(.*)', stripped)
        if m:
            if indent is None:
                indent = len(m.group(1))
            if len(m.group(1)) == indent:
                print(m.group(2).strip().strip('"\''))
            elif len(m.group(1)) < indent:
                break
        else:
            # Non-list line at any indent ends the block
            leading = len(stripped) - len(stripped.lstrip())
            if indent is None or leading <= 0:
                break
            break
PYEOF
}

# Parse pipeline.yml blocks into a flat representation using python3
# Prints lines: FIELD=VALUE for each check block, with CHECK_START as separator
_parse_pipeline_yml() {
  local file="$1"
  python3 - "$file" <<'PYEOF' 2>/dev/null || true
import sys, re

filepath = sys.argv[1]
with open(filepath) as f:
    content = f.read()

# Split into top-level sections by detecting "project_name:" and "checks:" keys
lines = content.splitlines()

# Extract top-level scalars
def get_scalar(key):
    for line in lines:
        m = re.match(r'^' + re.escape(key) + r'\s*:\s*(.*)', line.strip())
        if m:
            val = m.group(1).strip().strip('"\'')
            return val
    return ''

project_name = get_scalar('project_name')
print(f'PROJECT_NAME={project_name}')

# Parse checks list — each check is a YAML mapping block under "- name:"
in_checks = False
check_lines = []
for line in lines:
    if re.match(r'^checks\s*:', line):
        in_checks = True
        continue
    if in_checks:
        check_lines.append(line)

# Group check_lines into individual check blocks
# Detect list-item indent dynamically from the first "  - " line
blocks = []
current = []
list_indent = None
for line in check_lines:
    m = re.match(r'^(\s+)-\s', line)
    if m:
        indent_len = len(m.group(1))
        if list_indent is None:
            list_indent = indent_len
        if indent_len == list_indent:
            if current:
                blocks.append(current)
            current = [line]
        else:
            current.append(line)
    else:
        current.append(line)
if current:
    blocks.append(current)

prop_indent = (list_indent or 2) + 2  # properties are indented 2 more than the list marker
for block in blocks:
    print('CHECK_START')
    # Flatten the block: first line is "  - name: foo", rest are "    key: val"
    for line in block:
        # Strip leading "  - " or property indent
        stripped = re.sub(r'^\s+\-\s', '', line, count=1)
        if stripped == line:  # no "- " found, strip property indent
            stripped = re.sub(r'^\s{' + str(prop_indent) + r'}', '', line)
        stripped = stripped.rstrip()
        if not stripped:
            continue
        m = re.match(r'^(\w+)\s*:\s*(.*)', stripped)
        if m:
            key = m.group(1)
            val = m.group(2).strip().strip('"\'')
            print(f'{key}={val}')
PYEOF
}

# ─── Check Functions ──────────────────────────────────────────────────────────

# Check log file mtime — returns "HEALTHY" or "DEGRADED: <reason>"
_check_log_mtime() {
  local logfile="$1" max_age_min="$2"
  if [[ -z "$logfile" ]]; then
    echo "HEALTHY"
    return
  fi
  if [[ ! -f "$logfile" ]]; then
    echo "DEGRADED: log not found ($logfile)"
    return
  fi
  local now file_mtime age_sec age_min
  now=$(date +%s)
  file_mtime=$(stat --format=%Y "$logfile" 2>/dev/null) || {
    echo "DEGRADED: cannot stat log"
    return
  }
  age_sec=$(( now - file_mtime ))
  age_min=$(( age_sec / 60 ))
  if [[ "$age_min" -gt "$max_age_min" ]]; then
    echo "DEGRADED: log stale ${age_min}m (limit ${max_age_min}m)"
  else
    echo "HEALTHY"
  fi
}

# Run a single check block; prints: STATUS|detail
_run_check() {
  local check_type="$1" unit_or_port_or_pattern="$2"
  local logfile="${3:-}" log_max_age="${4:-60}"

  local status detail log_result

  case "$check_type" in
    systemd)
      if systemctl --user is-active "$unit_or_port_or_pattern" &>/dev/null; then
        status="HEALTHY"
        detail="unit $unit_or_port_or_pattern active"
      else
        echo "DEAD|unit $unit_or_port_or_pattern not active"
        return
      fi
      # Additionally check log if specified
      if [[ -n "$logfile" ]]; then
        log_result=$(_check_log_mtime "$logfile" "$log_max_age")
        if [[ "$log_result" != "HEALTHY" ]]; then
          echo "DEGRADED|process alive but $log_result"
          return
        fi
      fi
      echo "HEALTHY|$detail"
      ;;

    port)
      # target is either a port number (http://localhost:PORT) or a full URL
      local url
      if [[ "$unit_or_port_or_pattern" =~ ^https?:// ]]; then
        url="$unit_or_port_or_pattern"
      else
        url="http://localhost:${unit_or_port_or_pattern}"
      fi
      if curl -sf --max-time 3 "$url" &>/dev/null; then
        echo "HEALTHY|$url responding"
      else
        echo "DEAD|$url not responding"
      fi
      ;;

    process)
      if pgrep -f "$unit_or_port_or_pattern" &>/dev/null; then
        status="HEALTHY"
        detail="process found"
      else
        echo "DEAD|no process matching '$unit_or_port_or_pattern'"
        return
      fi
      # Additionally check log if specified
      if [[ -n "$logfile" ]]; then
        log_result=$(_check_log_mtime "$logfile" "$log_max_age")
        if [[ "$log_result" != "HEALTHY" ]]; then
          echo "DEGRADED|process alive but $log_result"
          return
        fi
      fi
      echo "HEALTHY|$detail"
      ;;

    logfile)
      local result
      result=$(_check_log_mtime "$unit_or_port_or_pattern" "$log_max_age")
      if [[ "$result" == "HEALTHY" ]]; then
        echo "HEALTHY|log fresh"
      else
        echo "DEGRADED|$result"
      fi
      ;;

    *)
      echo "UNKNOWN|unsupported check type '$check_type'"
      ;;
  esac
}

# ─── Process One Project ─────────────────────────────────────────────────────

_process_project() {
  local project_dir="$1"
  local pipeline_yml="${project_dir}/.claude/pipeline.yml"

  if [[ ! -f "$pipeline_yml" ]]; then
    return
  fi

  # Validate schema_version
  local schema_ver
  schema_ver=$(_yaml_get "$pipeline_yml" "schema_version")
  if [[ -n "$schema_ver" && "$schema_ver" != "1" ]]; then
    echo "UNKNOWN|$(basename "$project_dir")|schema|pipeline.yml schema_version=$schema_ver not supported (expected 1)"
    return
  fi

  # Parse pipeline.yml
  local parsed
  parsed=$(_parse_pipeline_yml "$pipeline_yml")

  # Extract project_name
  local project_name
  project_name=$(echo "$parsed" | grep '^PROJECT_NAME=' | head -1 | cut -d= -f2-)
  if [[ -z "$project_name" ]]; then
    project_name=$(basename "$project_dir")
  fi

  # Apply filter
  if [[ -n "$FILTER" ]]; then
    local lower_name lower_filter
    lower_name=$(echo "$project_name" | tr '[:upper:]' '[:lower:]')
    lower_filter=$(echo "$FILTER" | tr '[:upper:]' '[:lower:]')
    if [[ "$lower_name" != *"$lower_filter"* ]]; then
      return
    fi
  fi

  # Process each check block
  local check_name="" check_type="" unit="" port="" pattern="" logfile="" log_max_age="60"
  local restart_cmd=""
  local in_check=false

  _emit_check() {
    if [[ -z "$check_name" || -z "$check_type" ]]; then
      return
    fi
    local target=""
    case "$check_type" in
      systemd)  target="$unit" ;;
      port)     target="$port" ;;
      process)  target="$pattern" ;;
      logfile)  target="$logfile" ; logfile="" ;;  # logfile IS the target
    esac
    if [[ -z "$target" ]]; then
      echo "UNKNOWN|${project_name}|${check_name}|missing target field"
      return
    fi

    local result
    result=$(_run_check "$check_type" "$target" "$logfile" "$log_max_age")
    local status="${result%%|*}"
    local detail="${result#*|}"
    echo "${status}|${project_name}|${check_name}|${detail}"

    # Reset for next check
    check_name="" check_type="" unit="" port="" pattern="" logfile=""
    log_max_age="60" restart_cmd=""
    in_check=false
  }

  while IFS= read -r line; do
    if [[ "$line" == "CHECK_START" ]]; then
      _emit_check
      in_check=true
      continue
    fi
    [[ "$in_check" == false ]] && continue

    local key="${line%%=*}"
    local val="${line#*=}"
    case "$key" in
      name)             check_name="$val" ;;
      type)             check_type="$val" ;;
      unit)             unit="$val" ;;
      port)             port="$val" ;;
      pattern)          pattern="$val" ;;
      log)              logfile="$val" ;;
      log_max_age_minutes) log_max_age="$val" ;;
      restart_cmd)      restart_cmd="$val" ;;
    esac
  done <<< "$parsed"

  # Emit last check
  _emit_check
}

# ─── Main ─────────────────────────────────────────────────────────────────────

if [[ ! -f "$REGISTRY" ]]; then
  echo "UNKNOWN|pipeline-monitor|registry|~/.claude/pipeline-registry.yml not found" >&2
  exit 0
fi

# Parse registry: list of project paths
project_paths=$(_yaml_list "$REGISTRY" "projects")

if [[ -z "$project_paths" ]]; then
  echo "UNKNOWN|pipeline-monitor|registry|no projects registered in pipeline-registry.yml" >&2
  exit 0
fi

while IFS= read -r project_path; do
  [[ -z "$project_path" ]] && continue
  # Expand ~ if present
  project_path="${project_path/#\~/$HOME}"
  if [[ ! -d "$project_path" ]]; then
    echo "UNKNOWN|$(basename "$project_path")|registry|project directory not found: $project_path"
    continue
  fi
  _process_project "$project_path"
done <<< "$project_paths"
