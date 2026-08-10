"""Home Assistant plugin — the smart-home bridge.

Fully functional in code today; gracefully inert until the physical brain
box arrives. The moment homeassistant.url + .token appear in
config.local.json, /ha and natural-language control light up.
"""
from pa.plugins import Command, NLHandler, PluginBase
from pa.plugins.homeassistant.commands import handle_ha
from pa.plugins.homeassistant.nl import handle_ha_nl


class HomeAssistantPlugin(PluginBase):
    name = "homeassistant"
    description = "Smart-home control and status via Home Assistant"
    version = "0.1.0"

    def schema_sql(self) -> str:
        return ""  # stateless: HA itself is the source of truth

    def commands(self) -> list[Command]:
        return [
            Command(
                name="ha",
                description="Home Assistant status and entity counts",
                handler=handle_ha,
            ),
        ]

    def nl_handlers(self) -> list[NLHandler]:
        return [
            NLHandler(
                keywords=["turn on", "turn off", "who's home", "whos home",
                          "is the", "temperature", "lights", "garage door",
                          "lock the", "unlock", "thermostat"],
                handler=handle_ha_nl,
                description="Control and query the smart home via Home Assistant",
                # 9: below the home plugin's maintenance handler (10), so
                # "when did I change the filter" still routes there.
                priority=9,
                intent_id="homeassistant.control",
                examples=["turn on the kitchen lights",
                          "is the garage door open",
                          "who's home right now",
                          "what's the temperature inside"],
            ),
        ]

    def system_prompt_fragment(self) -> str:
        return (
            "Smart home: once the Home Assistant brain box is online, Albus "
            "can switch lights, check doors and locks, read temperatures, and "
            "see who's home. Until it's configured, say so honestly."
        )
