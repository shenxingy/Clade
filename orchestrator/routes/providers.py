"""Secret-safe provider/model registry inspection and refresh endpoints."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter

from config import GLOBAL_SETTINGS
from provider_registry import DEFAULT_REGISTRY


router = APIRouter(prefix="/api/provider-registry", tags=["providers"])


@router.get("")
async def inspect_provider_registry():
    return await asyncio.to_thread(DEFAULT_REGISTRY.inspect, GLOBAL_SETTINGS)


@router.post("/refresh")
async def refresh_provider_registry():
    return await asyncio.to_thread(
        DEFAULT_REGISTRY.inspect,
        GLOBAL_SETTINGS,
        force_refresh=True,
    )
