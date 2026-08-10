from pa.core.identity import GREETING, NAME, PERSONA


def test_name_is_albus():
    assert NAME == "Albus"


def test_greeting_uses_name():
    assert NAME in GREETING


def test_persona_uses_name():
    assert NAME in PERSONA
    assert "personal assistant" in PERSONA.lower()
