"""
Ideas manager — CRUD, AI evaluation, BRAINSTORM.md sync.
Depends on: config.py (leaf)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

import aiosqlite

logger = logging.getLogger(__name__)

# ─── AI Evaluation Prompt ────────────────────────────────────────────────────

_EVAL_PROMPT = """You are evaluating a project idea. Assess:
1. Feasibility (1-5): Can this be built with current codebase?
2. Risks: What could go wrong?
3. Better alternatives: Is there a simpler approach?
4. Missing details: What hasn't been considered?
5. Estimated effort: S/M/L

Respond in JSON only: {"feasibility": N, "risks": [...], "alternatives": [...], "missing": [...], "effort": "S|M|L", "summary": "one-line verdict"}

Idea:
"""

_DISCUSS_PROMPT = """You are discussing a project idea with the user.
Challenge assumptions, suggest alternatives, ask about unconsidered scenarios.
Be concise (2-4 sentences). If the idea is good, say so clearly.

Original idea: {idea}

AI evaluation: {evaluation}

Conversation so far:
{history}

User's latest message: {message}

Respond directly (no JSON):"""

# ─── IdeasManager ────────────────────────────────────────────────────────────


class IdeasManager:
    """CRUD + AI evaluation for the ideas table. Uses same DB path as TaskQueue."""

    def __init__(self, db_path: Path):
        self._db_path = db_path
        self._initialized = False
        self._init_lock = asyncio.Lock()

    async def _ensure_tables(self) -> None:
        """Create ideas/idea_messages tables if they don't exist (init-once)."""
        async with self._init_lock:
            if self._initialized:
                return
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
            async with aiosqlite.connect(str(self._db_path)) as db:
                await db.execute("""CREATE TABLE IF NOT EXISTS ideas (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    content TEXT NOT NULL,
                    source TEXT DEFAULT 'human',
                    project TEXT,
                    status TEXT DEFAULT 'raw',
                    ai_evaluation TEXT,
                    priority INTEGER DEFAULT 0,
                    promoted_to TEXT,
                    created_at TEXT DEFAULT (datetime('now')),
                    updated_at TEXT DEFAULT (datetime('now'))
                )""")
                await db.execute("""CREATE TABLE IF NOT EXISTS idea_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    idea_id INTEGER NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TEXT DEFAULT (datetime('now')),
                    FOREIGN KEY (idea_id) REFERENCES ideas(id)
                )""")
                await db.commit()
            self._initialized = True

    @asynccontextmanager
    async def _db(self):
        await self._ensure_tables()
        async with aiosqlite.connect(str(self._db_path)) as db:
            db.row_factory = aiosqlite.Row
            yield db

    # ─── CRUD ────────────────────────────────────────────────────────────────

    async def add_idea(self, content: str, source: str = "human",
                       project: str | None = None) -> dict:
        async with self._db() as db:
            cur = await db.execute(
                "INSERT INTO ideas (content, source, project) VALUES (?, ?, ?)",
                (content, source, project),
            )
            await db.commit()
            idea_id = cur.lastrowid
        return await self.get_idea(idea_id)

    async def list_ideas(self, status: str | None = None,
                         project: str | None = None,
                         limit: int = 100, offset: int = 0) -> list[dict]:
        clauses, params = [], []
        if status:
            clauses.append("status = ?")
            params.append(status)
        if project:
            clauses.append("project = ?")
            params.append(project)
        where = "WHERE " + " AND ".join(clauses) if clauses else ""
        params += [limit, offset]
        async with self._db() as db:
            async with db.execute(
                f"SELECT * FROM ideas {where} ORDER BY created_at DESC LIMIT ? OFFSET ?",
                params,
            ) as cur:
                rows = await cur.fetchall()
        return [self._row_to_dict(r) for r in rows]

    async def get_idea(self, idea_id: int) -> dict | None:
        async with self._db() as db:
            async with db.execute("SELECT * FROM ideas WHERE id = ?", (idea_id,)) as cur:
                row = await cur.fetchone()
            if not row:
                return None
            idea = self._row_to_dict(row)
            async with db.execute(
                "SELECT * FROM idea_messages WHERE idea_id = ? ORDER BY created_at ASC",
                (idea_id,),
            ) as cur:
                idea["messages"] = [dict(r) for r in await cur.fetchall()]
        return idea

    _VALID_STATUSES = {"raw", "evaluating", "evaluated", "promoting", "promoted", "archived",
                        "queued", "executing", "done"}

    async def update_idea(self, idea_id: int, **fields) -> dict | None:
        allowed = {"content", "status", "ai_evaluation", "priority",
                    "source", "project", "promoted_to"}
        fields = {k: v for k, v in fields.items() if k in allowed}
        if not fields:
            return await self.get_idea(idea_id)
        if "status" in fields and fields["status"] not in self._VALID_STATUSES:
            raise ValueError(f"Invalid status: {fields['status']}")
        fields["updated_at"] = datetime.now().isoformat()
        set_clause = ", ".join(f'"{k}" = ?' for k in fields)
        values = list(fields.values()) + [idea_id]
        async with self._db() as db:
            await db.execute(f"UPDATE ideas SET {set_clause} WHERE id = ?", values)
            await db.commit()
        return await self.get_idea(idea_id)

    async def archive_idea(self, idea_id: int) -> dict | None:
        return await self.update_idea(idea_id, status="archived")

    async def add_message(self, idea_id: int, role: str, content: str) -> dict:
        async with self._db() as db:
            cur = await db.execute(
                "INSERT INTO idea_messages (idea_id, role, content) VALUES (?, ?, ?)",
                (idea_id, role, content),
            )
            await db.commit()
            return {"id": cur.lastrowid, "idea_id": idea_id,
                    "role": role, "content": content}

    # ─── AI Evaluation ───────────────────────────────────────────────────────

    async def evaluate_idea(self, idea_id: int) -> dict | None:
        """Run AI evaluation via `claude -p` (haiku). Non-blocking."""
        idea = await self.get_idea(idea_id)
        if not idea:
            return None
        await self.update_idea(idea_id, status="evaluating")
        _env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}
        try:
            proc = await asyncio.create_subprocess_exec(
                "claude", "-p", "--model", "haiku",
                _EVAL_PROMPT + idea["content"],
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=_env,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=30)
            raw = stdout.decode().strip()
            # Extract JSON from response
            eval_data = _extract_json(raw)
            await self.update_idea(
                idea_id,
                ai_evaluation=json.dumps(eval_data) if eval_data else raw,
                status="evaluated",
            )
        except asyncio.TimeoutError:
            try:
                proc.kill()
                await proc.wait()
            except ProcessLookupError:
                pass
            await self.update_idea(idea_id, status="raw",
                                   ai_evaluation='{"error": "evaluation timed out"}')
        except Exception as e:
            logger.warning("evaluate_idea(%s) failed: %s", idea_id, e)
            await self.update_idea(idea_id, status="raw",
                                   ai_evaluation='{"error": "evaluation failed"}')
        return await self.get_idea(idea_id)

    async def discuss_idea(self, idea_id: int, message: str) -> dict | None:
        """Add user message, generate AI response via claude -p."""
        idea = await self.get_idea(idea_id)
        if not idea:
            return None
        await self.add_message(idea_id, "human", message)
        # Build conversation history
        history = "\n".join(
            f"{m['role']}: {m['content']}" for m in idea.get("messages", [])
        )
        prompt = _DISCUSS_PROMPT.format(
            idea=idea["content"],
            evaluation=idea.get("ai_evaluation", "not yet evaluated"),
            history=history,
            message=message,
        )
        _env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}
        try:
            proc = await asyncio.create_subprocess_exec(
                "claude", "-p", "--model", "haiku", prompt,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=_env,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=30)
            ai_reply = stdout.decode().strip()
        except asyncio.TimeoutError:
            try:
                proc.kill()
                await proc.wait()
            except ProcessLookupError:
                pass
            logger.warning("discuss_idea(%s) timed out", idea_id)
            ai_reply = "(AI response timed out)"
        except Exception as e:
            logger.warning("discuss_idea(%s) failed: %s", idea_id, e)
            ai_reply = "(AI response unavailable)"
        msg = await self.add_message(idea_id, "ai", ai_reply)
        return msg

    # ─── Promotion ───────────────────────────────────────────────────────────

    async def promote_idea(self, idea_id: int, target: str,
                           project_dir: Path | None = None) -> dict | None:
        """Promote idea to TODO.md or GOALS.md. target = 'todo' | 'vision'."""
        idea = await self.get_idea(idea_id)
        if not idea:
            return None
        await self.update_idea(idea_id, status="promoting")
        content = idea["content"]
        eval_data = idea.get("ai_evaluation", "")

        if project_dir:
            if target == "todo":
                todo_path = project_dir / "TODO.md"
                entry = f"\n- [ ] {content}\n"
                if eval_data:
                    entry += f"  <!-- AI assessment: {eval_data[:200]} -->\n"
                _append_to_file(todo_path, entry)
                promoted_ref = "todo"
            else:
                goals_path = project_dir / "GOALS.md"
                entry = f"\n## Idea: {content}\n"
                _append_to_file(goals_path, entry)
                promoted_ref = "vision"
        else:
            promoted_ref = target

        return await self.update_idea(idea_id, status="promoted",
                                      promoted_to=promoted_ref)

    # ─── BRAINSTORM.md Sync ──────────────────────────────────────────────────

    async def sync_to_brainstorm(self, project_dir: Path) -> int:
        """Write un-promoted raw/evaluated ideas to BRAINSTORM.md."""
        ideas = await self.list_ideas(project=project_dir.name)
        active = [i for i in ideas if i["status"] in ("raw", "evaluated")]
        brainstorm = project_dir / "BRAINSTORM.md"
        lines = ["# BRAINSTORM\n\n"]
        for idea in active:
            source_tag = f"[{idea['source']}]" if idea["source"] != "human" else ""
            lines.append(f"- {source_tag} {idea['content']}\n")
        brainstorm.write_text("".join(lines))
        return len(active)

    async def import_from_brainstorm(self, project_dir: Path,
                                     project_name: str | None = None) -> int:
        """Read BRAINSTORM.md, create ideas for items not already in DB."""
        brainstorm = project_dir / "BRAINSTORM.md"
        if not brainstorm.exists():
            return 0
        text = brainstorm.read_text()
        existing = await self.list_ideas(limit=500)
        existing_contents = {i["content"].strip().lower() for i in existing}
        count = 0
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            # Strip markdown list marker
            item = re.sub(r"^[-*]\s*(\[.*?\]\s*)?", "", line).strip()
            if not item or item.lower() in existing_contents:
                continue
            source = "brainstorm"
            # Detect [AI] tag
            if item.startswith("[AI]"):
                source = "ai"
                item = item[4:].strip()
            await self.add_idea(item, source=source,
                                project=project_name or project_dir.name)
            existing_contents.add(item.lower())
            count += 1
        return count

    # ─── Helpers ─────────────────────────────────────────────────────────────

    @staticmethod
    def _row_to_dict(row) -> dict:
        d = dict(row)
        # Parse ai_evaluation JSON if present
        raw = d.get("ai_evaluation")
        if isinstance(raw, str):
            try:
                d["ai_evaluation_parsed"] = json.loads(raw)
            except Exception:
                d["ai_evaluation_parsed"] = None
        return d


def _extract_json(text: str) -> dict | None:
    """Extract first JSON object from text."""
    # Try direct parse
    try:
        return json.loads(text)
    except Exception:
        pass
    # Try to find {...} block
    match = re.search(r"\{[^{}]*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except Exception:
            pass
    return None


def _append_to_file(path: Path, content: str) -> None:
    """Append content to file, creating if needed."""
    if path.exists():
        existing = path.read_text()
        path.write_text(existing.rstrip() + "\n" + content)
    else:
        path.write_text(content)
