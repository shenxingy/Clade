import pytest

import ideas as idm


@pytest.mark.asyncio
async def test_connection_is_reused(tmp_path):
    mgr = idm.IdeasManager(tmp_path / "ideas.db")

    first = await mgr._get_conn()
    second = await mgr._get_conn()

    assert first is second
    await mgr.close()


@pytest.mark.asyncio
async def test_crud_roundtrip(tmp_path):
    mgr = idm.IdeasManager(tmp_path / "ideas.db")

    created = await mgr.add_idea("Persist one connection", source="test", project="clade")
    fetched = await mgr.get_idea(created["id"])

    assert fetched is not None
    assert fetched["content"] == "Persist one connection"
    assert fetched["source"] == "test"
    assert fetched["project"] == "clade"
    await mgr.close()


@pytest.mark.asyncio
async def test_reopen_after_close(tmp_path):
    mgr = idm.IdeasManager(tmp_path / "ideas.db")

    await mgr._get_conn()
    await mgr.close()
    created = await mgr.add_idea("Connection reopens")

    assert created["content"] == "Connection reopens"
    await mgr.close()
