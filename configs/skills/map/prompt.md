# /map Skill: Generate Project Architecture Diagram

## Purpose
Automatically scan the project structure and generate `ARCHITECTURE.md` with a module relationship diagram using Mermaid.

## Execution Steps

1. **Read existing ARCHITECTURE.md**
   - If `ARCHITECTURE.md` exists at the project root, read it first
   - This helps preserve any existing documentation and allows you to update rather than overwrite

2. **Scan project structure**
   - Use Glob to find major directories: `find . -maxdepth 2 -type d -not -path '*/\.*' -not -path '*/node_modules/*' -not -path '*/__pycache__/*'`
   - For each top-level directory (src/, lib/, app/, components/, etc.), identify:
     - What it contains (modules, libraries, features)
     - Its primary responsibility
     - Key files or sub-modules within it

3. **Identify modules and dependencies**
   - Scan key files with Grep/Read to understand module structure
   - Map logical dependencies (imports, API calls, shared state)
   - Identify which modules depend on which others
   - Look for: package.json, setup.py, .go files, main entry points

4. **Generate Mermaid diagram**
   - Create a `graph TD` (top-down) Mermaid diagram showing:
     - Each major module as a node (use clear, short names)
     - Arrows showing dependencies: `ModuleA --> ModuleB` means ModuleA imports/uses ModuleB
     - Group related modules if they form a subsystem
   - Keep the diagram readable (max ~10-15 nodes for clarity)
   - Example structure:
     ```
     graph TD
       API["API Layer"]
       DB["Database"]
       Auth["Authentication"]
       UI["Frontend"]

       UI --> API
       API --> Auth
       API --> DB
       Auth --> DB
     ```

5. **Write ARCHITECTURE.md**
   - Create or update `ARCHITECTURE.md` at the project root
   - **Structure**:
     ```markdown
     # Project Architecture

     ## Overview
     [1-2 sentence high-level description of what the project does]

     ## Directory Structure

     ### src/
     [Description of what this directory contains]
     - Key files: file1.ts, file2.ts

     ### lib/
     [Description]
     - Key files: ...

     [... repeat for each top-level directory ...]

     ## Module Relationships

     ```mermaid
     [Your generated Mermaid graph]
     ```

     ## Key Components

     ### Module Name
     - **Location**: src/module/
     - **Responsibility**: What this module does
     - **Exports**: Key functions/classes
     - **Depends on**: Other modules it uses

     [... repeat for each major module ...]

     ## Data Flow
     [Optional: describe how data flows through the system, if applicable]
     ```
   - Keep descriptions concise (1-3 lines per section)
   - Focus on "why" not "what" — what problem does each module solve?

6. **Report success**
   - Tell the user: "Updated ARCHITECTURE.md"
   - If the diagram is complex, add a note about what the diagram shows

## Implementation Notes

- **Diagram scope**: Show the 5-10 most important modules, not every single file
- **Avoid noise**: Don't include vendored code (node_modules, venv, .git)
- **Update strategy**: If ARCHITECTURE.md exists, preserve existing descriptions and update the diagram + file list
- **Language**: Use English for all documentation
- **Mermaid syntax**: Use valid Mermaid graph TD syntax; test the diagram visually if possible

## Success Criteria

✓ ARCHITECTURE.md exists at project root
✓ Diagram renders without syntax errors
✓ All major modules are represented
✓ Dependencies are correctly shown
✓ Descriptions are clear and concise
