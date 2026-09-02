"""repo_map.py must stay the pure half of the old worker_tldr.

The split (2026-09-01) was mechanical — every function body moved verbatim, so
re-asserting their behaviour here would only duplicate test_worker_modules.py
and test_pagerank_and_jsparse.py, which already cover them from the new module.
What the split actually BUYS is an invariant: this module does no LLM call, no
subprocess, no DB, and no async work, which is why session.py and
routes/workers.py can import it without pulling in the money-spending half.

That invariant is exactly the thing that rots silently — a localizer helper
added to the wrong file compiles, imports, and passes every other test. These
two tests are the only thing that would notice.
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO_MAP = Path(__file__).resolve().parents[1] / "repo_map.py"


def _source() -> str:
    return REPO_MAP.read_text(encoding="utf-8")


def test_repo_map_makes_no_llm_or_subprocess_call() -> None:
    src = _source()
    tree = ast.parse(src, filename=str(REPO_MAP))

    # An async def is the tell for every expensive path in worker_tldr: the
    # localizer, the fault localizer, the SBFL pre-pass, the repro generator
    # and the scorer are all coroutines. None of them belongs here.
    coroutines = [
        node.name for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef)
    ]
    assert not coroutines, (
        "repo_map.py grew coroutines "
        f"{sorted(coroutines)} — the async/LLM half belongs in worker_tldr.py"
    )
    assert not any(
        isinstance(node, (ast.Await, ast.AsyncFor, ast.AsyncWith))
        for node in ast.walk(tree)
    ), "repo_map.py grew an await — it must stay synchronous"

    for marker, why in [
        ("claude -p", "an LLM call"),
        ("create_subprocess", "a subprocess spawn"),
        ("subprocess.", "a subprocess spawn"),
        ("aiosqlite", "a DB handle"),
        ("HAIKU_MODEL", "a model id (worker.py threads that into leaves)"),
    ]:
        assert marker not in src, (
            f"repo_map.py contains {marker!r} — that is {why}, and this module "
            "is imported by session.py / routes/workers.py precisely because "
            "it has none"
        )


def test_repo_map_imports_only_stdlib_and_fault_localize() -> None:
    """The module-level project imports must stay exactly {fault_localize}.

    test_conventions.py's leaf gate grants repo_map the same allowance as the
    other primitive leaves, which means it would NOT catch repo_map importing
    config or worker_utils. This does.
    """
    tree = ast.parse(_source(), filename=str(REPO_MAP))
    orchestrator = REPO_MAP.parent
    project_modules = {p.stem for p in orchestrator.glob("*.py")} | {
        "routes", "task_factory",
    }

    imported: set[str] = set()
    for stmt in tree.body:
        if isinstance(stmt, ast.Import):
            imported.update(a.name.split(".")[0] for a in stmt.names)
        elif isinstance(stmt, ast.ImportFrom) and stmt.module and stmt.level == 0:
            imported.add(stmt.module.split(".")[0])

    assert imported & project_modules == {"fault_localize"}, (
        "repo_map.py's project imports changed: "
        f"{sorted(imported & project_modules)}"
    )
