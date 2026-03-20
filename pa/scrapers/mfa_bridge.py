import asyncio
from dataclasses import dataclass, field


@dataclass
class _PendingMFA:
    institution: str
    prompt: str
    event: asyncio.Event = field(default_factory=asyncio.Event)
    code: str = ""


class MFABridge:
    def __init__(self, timeout_seconds: float = 300.0):
        self._timeout = timeout_seconds
        self._pending: dict[str, _PendingMFA] = {}

    async def request_mfa(self, institution: str, prompt: str) -> str:
        pending = _PendingMFA(institution=institution, prompt=prompt)
        self._pending[institution] = pending
        try:
            await asyncio.wait_for(pending.event.wait(), timeout=self._timeout)
            return pending.code
        finally:
            self._pending.pop(institution, None)

    async def provide_mfa(self, institution: str, code: str) -> None:
        pending = self._pending.get(institution)
        if pending:
            pending.code = code
            pending.event.set()

    def has_pending(self, institution: str) -> bool:
        return institution in self._pending

    def get_pending_prompt(self, institution: str) -> str | None:
        pending = self._pending.get(institution)
        return pending.prompt if pending else None
