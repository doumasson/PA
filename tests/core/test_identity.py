from pa.core.identity import NAME, GREETING, PERSONA

def test_name_is_george():
    assert NAME == "George"

def test_greeting_uses_name():
    assert "George" in GREETING

def test_persona_uses_name():
    assert "George" in PERSONA
    assert "personal assistant" in PERSONA.lower()
