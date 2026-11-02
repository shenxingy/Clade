"""Opening an existing project in the GUI must not spawn a duplicate agent."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import HTTPException

import server


@pytest.mark.parametrize('spelling', ['direct', 'parent', 'symlink'])
async def test_gui_open_reuses_resolved_project_without_spawning(tmp_path, monkeypatch, spelling):
    project = tmp_path / 'project'
    project.mkdir()
    alias = tmp_path / 'alias'
    alias.symlink_to(project, target_is_directory=True)
    submitted = {'direct': project, 'parent': project / '..' / 'project', 'symlink': alias}[spelling]
    existing = SimpleNamespace(project_dir=project, to_dict=lambda: {'session_id': 'existing'})
    registry = Mock()
    registry.all.return_value = [existing]
    monkeypatch.setattr(server, 'registry', registry)

    result = await server.create_session({'path': str(submitted), 'reuse_existing': True})

    assert result == {'session_id': 'existing'}
    registry.create.assert_not_called()


async def test_gui_open_still_rejects_missing_directory(tmp_path):
    with pytest.raises(HTTPException) as error:
        await server.create_session({'path': str(tmp_path / 'missing'), 'reuse_existing': True})
    assert error.value.status_code == 400
