#!/usr/bin/env bash
# linter-config-guard.sh — PreToolUse hook (Edit|Write)
# Blocks modifications to linter/formatter/type-checker config files.
# ECC Plankton pattern: protect code-quality tooling from being silenced by LLMs.
#
# Claude Code calls this with the tool input JSON on stdin.
# Exit 2 with a message to block the operation.

set -euo pipefail

INPUT=$(cat)
FILE_PATH=$(echo "$INPUT" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('file_path','') or d.get('path',''))" 2>/dev/null || true)

if [[ -z "$FILE_PATH" ]]; then
    exit 0
fi

BASENAME=$(basename "$FILE_PATH")

# Protected patterns (linter / formatter / type-checker configs)
PROTECTED_FILES=(
    ".ruff.toml"
    "ruff.toml"
    ".flake8"
    "mypy.ini"
    ".mypy.ini"
    "pyrightconfig.json"
    "biome.json"
    "biome.jsonc"
    ".eslintrc"
    ".eslintrc.js"
    ".eslintrc.cjs"
    ".eslintrc.json"
    ".eslintrc.yml"
    ".eslintrc.yaml"
    ".pylintrc"
    ".pre-commit-config.yaml"
    "stylua.toml"
    ".stylua.toml"
)

for protected in "${PROTECTED_FILES[@]}"; do
    if [[ "$BASENAME" == "$protected" ]]; then
        echo "linter-config-guard: blocked write to '$FILE_PATH'" >&2
        cat <<EOF
{
  "decision": "block",
  "reason": "Writing to linter/formatter config files is not allowed. Modifying '$FILE_PATH' could silence code-quality checks and introduce silent regressions. To fix lint errors, fix the code — not the linter config."
}
EOF
        exit 0
    fi
done

# pyproject.toml: block if it contains [tool.ruff], [tool.mypy], [tool.pylint], [tool.flake8]
if [[ "$BASENAME" == "pyproject.toml" ]]; then
    NEW_CONTENT=$(echo "$INPUT" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('new_string','') or d.get('content',''))" 2>/dev/null || true)
    if echo "$NEW_CONTENT" | grep -qE '^\[tool\.(ruff|mypy|pylint|flake8|pyright)\]'; then
        echo "linter-config-guard: blocked linter section write to pyproject.toml" >&2
        cat <<EOF
{
  "decision": "block",
  "reason": "Modifying linter/type-checker sections in 'pyproject.toml' is not allowed. This could disable code-quality enforcement. Fix the underlying code issues instead."
}
EOF
        exit 0
    fi
fi

exit 0
