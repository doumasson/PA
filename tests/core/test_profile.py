import datetime

from pa.core.profile import Kid, Profile


def test_from_config_none_gives_defaults():
    p = Profile.from_config(None)
    assert p.owner == "the user"
    assert p.timezone == "UTC"
    assert p.kids == []
    assert p.monthly_income is None
    assert p.goals == []


def test_from_config_full():
    p = Profile.from_config({
        "owner": "Steven",
        "timezone": "America/New_York",
        "kids": [
            {"name": "  Ada ", "birth_year": 2018, "notes": "loves dinosaurs"},
            {"name": "Ben"},
        ],
        "monthly_income": 5000.0,
        "goals": ["debt-free in 2 years"],
    })
    assert p.owner == "Steven"
    assert p.timezone == "America/New_York"
    assert [k.name for k in p.kids] == ["Ada", "Ben"]
    assert p.kids[0].birth_year == 2018
    assert p.kids[0].notes == "loves dinosaurs"
    assert p.kids[1].birth_year is None
    assert p.monthly_income == 5000.0
    assert p.goals == ["debt-free in 2 years"]


def test_from_config_skips_nameless_kids():
    p = Profile.from_config({"kids": [{"birth_year": 2020}, {"name": ""}, {"name": "Zoe"}]})
    assert [k.name for k in p.kids] == ["Zoe"]


def test_kid_age():
    k = Kid(name="Ada", birth_year=2018)
    assert k.age(today=datetime.date(2026, 7, 2)) == 8


def test_kid_age_unknown_birth_year():
    assert Kid(name="Ben").age() is None


def test_kid_lookup_case_insensitive():
    p = Profile(kids=[Kid(name="Ada"), Kid(name="Ben")])
    assert p.kid("  ADA ") is p.kids[0]
    assert p.kid("ben") is p.kids[1]
    assert p.kid("nobody") is None


def test_system_prompt_fragment_full():
    p = Profile(
        owner="Steven",
        timezone="America/New_York",
        kids=[Kid(name="Ada", birth_year=2018, notes="loves dinosaurs"), Kid(name="Ben")],
        goals=["debt-free in 2 years", "save for a house"],
    )
    frag = p.system_prompt_fragment()
    assert "You assist Steven." in frag
    assert "Ada (" in frag  # age rendered
    assert "loves dinosaurs" in frag
    assert "Ben" in frag
    assert "(None)" not in frag  # no age shown for unknown birth year
    assert "Goals: debt-free in 2 years; save for a house." in frag
    assert "Timezone: America/New_York." in frag


def test_system_prompt_fragment_minimal():
    frag = Profile().system_prompt_fragment()
    assert frag == "You assist the user. Timezone: UTC."
    assert "Kids" not in frag
    assert "Goals" not in frag
