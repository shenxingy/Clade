---
name: slt
description: Toggle the statusline quota pace indicator (mode/theme)
argument-hint: '[symbol|percent|number|off] [theme [name]]'
user_invocable: true
---

# Statusline Toggle

Cycles the display mode of the quota pace indicator in the Claude Code status line.

## Modes

`symbol` → `percent` → `number` → `off` → back to `symbol`

## Usage

```
/slt                    # Cycle to next mode
/slt theme              # Show available themes
/slt theme <name>       # Set theme (circles, bird, moon, weather, mood, coffee, rocket, ocean, dragon)
/slt symbol|percent|number|off   # Set specific mode
```
