#!/usr/bin/env python3
"""
Resolve goal file dependencies with {{}} template substitution.

Supports Goose-style recipe includes:
    ---
    includes:
      - path: ./base.yaml
        values:
          target: "{{ input_file }}"
    ---

Each included file is:
1. Read and parsed for its own includes (recursive)
2. Have {{variable}} substitutions applied from the `values` dict
3. Merged into the parent

Frontmatter is merged (arrays concatenated for multi-value fields).
Body content is concatenated under section headers.
"""

import re
import sys
import yaml
from pathlib import Path


def extract_frontmatter(content: str) -> tuple[dict, str]:
    """Parse YAML frontmatter from markdown content. Returns (frontmatter_dict, body)."""
    match = re.match(r'^---\n(.*?)\n---\n(.*)$', content, re.DOTALL)
    if not match:
        return {}, content
    fm_raw, body = match.groups()
    # Parse YAML (may contain nested structures)
    try:
        fm = yaml.safe_load(fm_raw) or {}
    except yaml.YAMLError:
        fm = {}
    return fm, body


def emit_frontmatter(fm: dict) -> str:
    """Serialize frontmatter dict back to YAML string."""
    return "---\n" + yaml.safe_dump(fm, default_flow_style=False, sort_keys=False) + "---\n"


def substitute(content: str, values: dict) -> str:
    """Replace {{key}} placeholders with values dict."""
    result = content
    for key, val in values.items():
        result = result.replace(f"{{{{{key}}}}}", str(val))
    return result


def substitute_recursive(obj, values: dict):
    """Recursively substitute {{key}} in strings, lists, and dicts."""
    if isinstance(obj, str):
        return substitute(obj, values)
    elif isinstance(obj, list):
        return [substitute_recursive(item, values) for item in obj]
    elif isinstance(obj, dict):
        return {k: substitute_recursive(v, values) for k, v in obj.items()}
    else:
        return obj


def merge_frontmatter(parent: dict, child: dict) -> dict:
    """Merge child frontmatter into parent. Arrays are concatenated."""
    merged = dict(parent)
    for key, child_val in child.items():
        if key not in merged:
            merged[key] = child_val
        elif isinstance(child_val, list) and isinstance(merged[key], list):
            # Concatenate lists, dedupe while preserving order
            seen = set()
            merged[key] = [x for x in merged[key] + child_val if not (x in seen or seen.add(x))]
        else:
            # Scalar: child wins
            merged[key] = child_val
    return merged


def merge_body(parent_body: str, child_body: str) -> str:
    """
    Merge two body contents.
    - If child has section headers (##), append them to parent
    - If child has no headers, append as a new ## Included: section
    """
    child_stripped = child_body.strip()
    if not child_stripped:
        return parent_body

    # Check if child has section headers
    has_headers = bool(re.search(r'^##\s+', child_stripped, re.MULTILINE))

    if has_headers:
        # Append child sections to parent
        if parent_body.strip():
            return parent_body.rstrip() + "\n\n" + child_stripped
        return child_stripped
    else:
        # Wrap inline content in a section
        if parent_body.strip():
            return parent_body.rstrip() + "\n\n## Included content\n\n" + child_stripped
        return "## Included content\n\n" + child_stripped


def resolve_includes(content: str, base_dir: Path, seen: set | None = None) -> str:
    """
    Recursively resolve all includes in a goal file.
    Returns the fully resolved content with no includes remaining.
    """
    if seen is None:
        seen = set()

    fm, body = extract_frontmatter(content)
    includes = fm.get('includes', [])

    if not includes:
        return content

    # Remove 'includes' from frontmatter — it's an implementation detail, not output
    fm.pop('includes', None)

    # Merge frontmatter and body from all includes
    for inc in includes:
        inc_path = inc.get('path')
        if not inc_path:
            continue

        # Resolve path relative to current file's directory
        inc_file = (base_dir / inc_path).resolve()
        values = inc.get('values', {})

        # Cycle detection
        if str(inc_file) in seen:
            continue
        seen.add(str(inc_file))

        # Read and resolve child recursively
        if not inc_file.exists():
            sys.stderr.write(f"resolve-goal-deps: warning: included file not found: {inc_file}\n")
            continue

        child_content = inc_file.read_text()
        child_resolved = resolve_includes(child_content, inc_file.parent, seen)

        # Substitute template variables in child's body and frontmatter
        fm_child, body_child = extract_frontmatter(child_resolved)
        if values:
            body_child = substitute(body_child, values)
            fm_child = substitute_recursive(fm_child, values)
        child_resolved = emit_frontmatter(fm_child) + body_child if fm_child else body_child

        # Merge frontmatter and body
        fm = merge_frontmatter(fm, fm_child)
        body = merge_body(body, body_child)

    # Reconstruct final content
    result = emit_frontmatter(fm) + body if fm else body
    return result


def main():
    if len(sys.argv) < 2:
        sys.stderr.write(f"Usage: {sys.argv[0]} GOAL_FILE\n")
        sys.exit(1)

    goal_file = Path(sys.argv[1]).resolve()
    if not goal_file.exists():
        sys.stderr.write(f"resolve-goal-deps: error: file not found: {goal_file}\n")
        sys.exit(1)

    content = goal_file.read_text()
    resolved = resolve_includes(content, goal_file.parent)
    print(resolved)


if __name__ == "__main__":
    main()
