"""Home Assistant plugin — inert-until-configured, then bridge to HA.

No real network anywhere: unconfigured paths bail before any request, and
configured paths run against monkeypatched HAClient methods.
"""
import types

from pa.plugins import validate_plugin
from pa.plugins.homeassistant import HomeAssistantPlugin
from pa.plugins.homeassistant.client import HAClient, HAError
from pa.plugins.homeassistant.commands import handle_ha
from pa.plugins.homeassistant.nl import handle_ha_nl

# -- fakes ---------------------------------------------------------------


class FakeConfig:
    def __init__(self, data=None):
        self._data = data or {}

    def get(self, key, default=None):
        return self._data.get(key, default)


class FakeBrain:
    def __init__(self, answer):
        self.answer = answer
        self.prompts = []

    async def query_json(self, prompt, **kw):
        self.prompts.append(prompt)
        return self.answer


class FakeLedger:
    def __init__(self):
        self.records = []

    async def record(self, err, source):
        self.records.append((err, source))
        return "sig"


CONFIGURED = FakeConfig(
    {"homeassistant": {"url": "http://ha.local:8123/", "token": "llt-abc"}}
)

FAKE_STATES = [
    {"entity_id": "light.kitchen", "state": "off",
     "attributes": {"friendly_name": "Kitchen Light"}},
    {"entity_id": "light.porch", "state": "on",
     "attributes": {"friendly_name": "Porch Light"}},
    {"entity_id": "person.dad", "state": "home",
     "attributes": {"friendly_name": "Dad"}},
    {"entity_id": "person.mom", "state": "not_home",
     "attributes": {"friendly_name": "Mom"}},
    {"entity_id": "sensor.hallway_temperature", "state": "21.5",
     "attributes": {"friendly_name": "Hallway Temperature"}},
    {"entity_id": "sun.sun", "state": "above_horizon",
     "attributes": {"friendly_name": "Sun"}},  # boring domain, must be filtered
]


def make_ctx(config, brain=None, ledger=None):
    return types.SimpleNamespace(config=config, brain=brain, ledger=ledger)


def patch_states(monkeypatch, states=FAKE_STATES):
    async def fake_states(self):
        return list(states)

    monkeypatch.setattr(HAClient, "states", fake_states)


# -- contract ---------------------------------------------------------------


def test_plugin_passes_contract():
    validate_plugin(HomeAssistantPlugin())


def test_client_configured_property():
    assert not HAClient(FakeConfig()).configured
    assert not HAClient(FakeConfig({"homeassistant": {"url": "x"}})).configured
    assert HAClient(CONFIGURED).configured


# -- unconfigured: politely inert, zero network -------------------------------


async def test_command_unconfigured_says_not_online():
    reply = await handle_ha(make_ctx(FakeConfig()), None, None)
    assert "brain box isn't online yet" in reply
    assert "config.local.json" in reply


async def test_nl_unconfigured_says_not_online():
    reply = await handle_ha_nl(make_ctx(FakeConfig()), "turn on the lights", None)
    assert "brain box isn't online yet" in reply


# -- configured: /ha status ----------------------------------------------------


async def test_ha_command_counts_by_domain(monkeypatch):
    async def fake_ping(self):
        return {"message": "API running."}

    monkeypatch.setattr(HAClient, "ping", fake_ping)
    patch_states(monkeypatch)
    reply = await handle_ha(make_ctx(CONFIGURED), None, None)
    assert "online" in reply
    assert "light: 2" in reply and "person: 2" in reply and "sensor: 1" in reply


# -- configured: NL get -------------------------------------------------------


async def test_whos_home_answers_from_person_entities(monkeypatch):
    patch_states(monkeypatch)
    brain = FakeBrain(
        {"action": "get", "entity_id": "person.dad", "service": None,
         "reply": "Just Dad is home right now."}
    )
    reply = await handle_ha_nl(make_ctx(CONFIGURED, brain=brain), "who's home", None)
    assert reply == "Just Dad is home right now."
    # The brain saw the person entities but not the filtered-out sun domain.
    prompt = brain.prompts[0]
    assert "person.dad" in prompt and "person.mom" in prompt
    assert "sun.sun" not in prompt


async def test_get_falls_back_to_state_when_brain_omits_reply(monkeypatch):
    patch_states(monkeypatch)
    brain = FakeBrain(
        {"action": "get", "entity_id": "light.porch", "service": None, "reply": None}
    )
    reply = await handle_ha_nl(
        make_ctx(CONFIGURED, brain=brain), "is the porch light on", None
    )
    assert "Porch Light" in reply and "on" in reply


# -- configured: NL set -------------------------------------------------------


async def test_turn_on_kitchen_light_calls_service(monkeypatch):
    patch_states(monkeypatch)
    calls = []

    async def fake_call_service(self, domain, service, entity_id=None, **data):
        calls.append((domain, service, entity_id, data))
        return []

    monkeypatch.setattr(HAClient, "call_service", fake_call_service)
    brain = FakeBrain(
        {"action": "set", "entity_id": "light.kitchen",
         "service": "light.turn_on", "reply": None}
    )
    reply = await handle_ha_nl(
        make_ctx(CONFIGURED, brain=brain), "turn on the kitchen light", None
    )
    assert calls == [("light", "turn_on", "light.kitchen", {})]
    assert "Kitchen Light" in reply and "turn on" in reply


# -- failures: ledger + honest message ----------------------------------------


async def test_ha_failure_hits_ledger_and_stays_graceful(monkeypatch):
    async def broken_states(self):
        raise HAError("Home Assistant unreachable at http://ha.local:8123")

    monkeypatch.setattr(HAClient, "states", broken_states)
    ledger = FakeLedger()
    reply = await handle_ha_nl(
        make_ctx(CONFIGURED, ledger=ledger), "turn off the porch light", None
    )
    assert len(ledger.records) == 1
    err, source = ledger.records[0]
    assert isinstance(err, HAError)
    assert source == "homeassistant.nl"
    assert "couldn't reach" in reply
    assert "Traceback" not in reply


async def test_command_failure_hits_ledger(monkeypatch):
    async def broken_ping(self):
        raise HAError("Home Assistant returned 401 for GET /api/")

    monkeypatch.setattr(HAClient, "ping", broken_ping)
    ledger = FakeLedger()
    reply = await handle_ha(make_ctx(CONFIGURED, ledger=ledger), None, None)
    assert len(ledger.records) == 1
    assert ledger.records[0][1] == "homeassistant.command"
    assert "couldn't reach" in reply
