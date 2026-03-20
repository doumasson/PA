import asyncio

import pytest

from pa.scrapers.mfa_bridge import MFABridge


async def test_request_and_provide_mfa():
    bridge = MFABridge()

    async def provider():
        await asyncio.sleep(0.1)
        await bridge.provide_mfa("wellsfargo", "123456")

    asyncio.create_task(provider())
    code = await bridge.request_mfa("wellsfargo", "Enter MFA code")
    assert code == "123456"


async def test_mfa_timeout():
    bridge = MFABridge(timeout_seconds=0.2)
    with pytest.raises(asyncio.TimeoutError):
        await bridge.request_mfa("wellsfargo", "Enter MFA code")


async def test_mfa_multiple_institutions():
    bridge = MFABridge()

    async def provider1():
        await asyncio.sleep(0.05)
        await bridge.provide_mfa("wellsfargo", "111111")

    async def provider2():
        await asyncio.sleep(0.1)
        await bridge.provide_mfa("synchrony", "222222")

    asyncio.create_task(provider1())
    asyncio.create_task(provider2())

    code1 = await bridge.request_mfa("wellsfargo", "WF code")
    code2 = await bridge.request_mfa("synchrony", "Sync code")
    assert code1 == "111111"
    assert code2 == "222222"


async def test_has_pending_request():
    bridge = MFABridge()

    async def requester():
        await bridge.request_mfa("wellsfargo", "Enter code")

    task = asyncio.create_task(requester())
    await asyncio.sleep(0.05)
    assert bridge.has_pending("wellsfargo")
    assert not bridge.has_pending("synchrony")
    await bridge.provide_mfa("wellsfargo", "999999")
    await task
