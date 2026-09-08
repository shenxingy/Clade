"""Auto-scale floor and import fan-out ceiling tests.

Lifted verbatim out of test_worker_modules.py, which had reached 1446 of the
1500-line ceiling test_conventions.py enforces. The two sections moved together
because both are *bounds* rather than behaviour: the `min_workers` floor that
`session._autoscale_should_spawn` reads, and the ceiling on how many project
modules `worker.py` may import.
"""

import pytest


# ─── session: the min_workers auto-scale floor ────────────────────────────────
# The other half of the same defect class: `min_workers` was editable in the
# React settings panel and persisted, and no backend code read it. TODO.md's
# "Worker auto-scaling" item shipped the max cap and the backlog ratio and
# marked the whole thing done.

from session import _autoscale_should_spawn


class TestAutoscaleShouldSpawn:
    def test_floor_spawns_below_min_workers(self):
        """The case that was False before the floor was wired."""
        assert _autoscale_should_spawn(
            running=1, pending=1, min_workers=3, max_workers=8
        ) is True

    def test_floor_never_exceeds_max_workers(self):
        assert _autoscale_should_spawn(
            running=4, pending=10, min_workers=8, max_workers=4
        ) is False

    def test_floor_needs_pending_work(self):
        """A floor cannot conjure workers for an empty queue."""
        assert _autoscale_should_spawn(
            running=0, pending=0, min_workers=3, max_workers=8
        ) is False

    def test_floor_stops_once_reached(self):
        assert _autoscale_should_spawn(
            running=3, pending=1, min_workers=3, max_workers=8
        ) is False

    def test_backlog_ratio_still_fires_at_default_floor(self):
        assert _autoscale_should_spawn(
            running=2, pending=5, min_workers=1, max_workers=8
        ) is True

    def test_backlog_ratio_does_not_fire_below_threshold(self):
        """The floor must not have weakened the pre-existing ratio trigger."""
        assert _autoscale_should_spawn(
            running=2, pending=3, min_workers=1, max_workers=8
        ) is False

    def test_zero_min_workers_is_treated_as_one(self):
        assert _autoscale_should_spawn(
            running=0, pending=1, min_workers=0, max_workers=8
        ) is True


# ─── worker.py import fan-out ceiling ─────────────────────────────────────────
# worker.py reached 30 top-level project imports by absorbing every extraction's
# edge, four of which imported names it never used — two of those the only
# reason github_sync and handoff_registry were edges at all. The
# by-responsibility split that would fix the hub shape is blocked on 38
# `setattr(wmod, ...)` sites in test_oracle_integrity.py, so this bounds the
# slide instead. Like LINE_LIMIT_EXCEPTIONS, it must SHRINK, never grow.

IMPORT_FANOUT_CEILING = {"worker.py": 28}


def _project_import_fanout(module_path):
    import ast
    from pathlib import Path

    orch = Path(module_path).resolve().parent
    project = {p.stem for p in orch.glob("*.py")} | {"routes", "task_factory"}
    tree = ast.parse(Path(module_path).read_text())
    mods = set()
    for node in tree.body:  # top level only — lazy imports are the escape hatch
        if isinstance(node, ast.Import):
            mods.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            mods.add(node.module.split(".")[0])
    return mods & project


class TestImportFanoutCeiling:
    def test_fanout_stays_under_ceiling(self):
        from pathlib import Path

        orch = Path(__file__).resolve().parents[1]
        over = []
        for name, ceiling in sorted(IMPORT_FANOUT_CEILING.items()):
            count = len(_project_import_fanout(orch / name))
            if count > ceiling:
                over.append(f"{name}: {count} project imports (ceiling {ceiling})")
        assert not over, (
            "Module import fan-out grew. Route the new dependency through the "
            "module that already owns it, or lower the ceiling in the same "
            "commit:\n" + "\n".join(over)
        )

    def test_ceilings_still_needed(self):
        """A ceiling that has been beaten must be lowered, or it protects nothing."""
        from pathlib import Path

        orch = Path(__file__).resolve().parents[1]
        stale = []
        for name, ceiling in sorted(IMPORT_FANOUT_CEILING.items()):
            path = orch / name
            if not path.is_file():
                stale.append(f"{name}: gone — remove from IMPORT_FANOUT_CEILING")
                continue
            count = len(_project_import_fanout(path))
            if count < ceiling:
                stale.append(f"{name}: now {count} — lower IMPORT_FANOUT_CEILING to it")
        assert not stale, "\n".join(stale)


class TestAutoscaleFloorCoercion:
    """orchestrator-settings.json is user-edited and untyped."""

    @pytest.mark.parametrize("junk", ["", "three", None, [], {}])
    def test_junk_min_workers_falls_back_to_one(self, junk):
        # Falls back to a floor of 1, which cannot spawn past auto_start —
        # and must not raise inside status_loop's once-a-second tick.
        assert _autoscale_should_spawn(
            running=1, pending=1, min_workers=junk, max_workers=8
        ) is False

    def test_numeric_string_min_workers_is_honoured(self):
        assert _autoscale_should_spawn(
            running=1, pending=1, min_workers="3", max_workers=8
        ) is True
