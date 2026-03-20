# tests/scrapers/test_mfa_bridge.py
import asyncio
import pytest
from pa.scrapers.mfa_bridge import MFABridge


async def test_mfa_round_trip():
    bridge = MFABridge(timeout_seconds=2.0)
    assert not bridge.has_pending("bank")

    async def provide():
        await asyncio.sleep(0.05)
        await bridge.provide_mfa("bank", "123456")

    asyncio.create_task(provide())
    code = await bridge.request_mfa("bank", "Enter code")
    assert code == "123456"


async def test_mfa_timeout():
    bridge = MFABridge(timeout_seconds=0.05)
    with pytest.raises(asyncio.TimeoutError):
        await bridge.request_mfa("bank", "Enter code")


async def test_has_pending():
    bridge = MFABridge(timeout_seconds=2.0)

    async def slow_request():
        try:
            await bridge.request_mfa("bank", "Enter code")
        except asyncio.TimeoutError:
            pass

    task = asyncio.create_task(slow_request())
    await asyncio.sleep(0.01)
    assert bridge.has_pending("bank")
    task.cancel()
    try:
        await task
    except (asyncio.CancelledError, asyncio.TimeoutError):
        pass
