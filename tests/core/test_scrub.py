from pa.core.scrub import restore, scrub


def test_email_scrubbed_and_restorable():
    clean, restore_map = scrub("Mail steve@example.com about the bill.")
    assert "steve@example.com" not in clean
    assert "[EMAIL_1]" in clean
    assert restore_map == {"[EMAIL_1]": "steve@example.com"}


def test_same_token_gets_stable_placeholder():
    clean, restore_map = scrub("steve@example.com wrote to steve@example.com")
    assert clean == "[EMAIL_1] wrote to [EMAIL_1]"
    assert len(restore_map) == 1


def test_distinct_tokens_get_numbered_placeholders():
    clean, restore_map = scrub("cc a@x.com and b@y.com")
    assert "[EMAIL_1]" in clean and "[EMAIL_2]" in clean
    assert set(restore_map.values()) == {"a@x.com", "b@y.com"}


def test_phone_scrubbed():
    clean, restore_map = scrub("Call me at 555-123-4567 tomorrow.")
    assert "555-123-4567" not in clean
    assert "[PHONE_1]" in clean


def test_card_scrubbed():
    clean, restore_map = scrub("Card: 4111 1111 1111 1111 expires soon")
    assert "4111 1111 1111 1111" not in clean
    assert "[CARD_1]" in clean


def test_ssn_scrubbed():
    clean, _ = scrub("SSN 123-45-6789 on file")
    assert "123-45-6789" not in clean
    assert "[SSN_1]" in clean


def test_account_fragment_scrubbed():
    clean, _ = scrub("the checking account ending in 4321")
    assert "4321" not in clean
    assert "[ACCT_1]" in clean


def test_clean_text_untouched():
    text = "What should we cook for dinner tonight?"
    clean, restore_map = scrub(text)
    assert clean == text
    assert restore_map == {}


def test_restore_round_trip():
    original = "Email steve@example.com or call 555-123-4567."
    clean, restore_map = scrub(original)
    reply = f"I will contact them. ({clean})"
    assert restore(reply, restore_map) == f"I will contact them. ({original})"


def test_restore_with_empty_map_is_identity():
    assert restore("no placeholders here", {}) == "no placeholders here"


def test_mixed_kinds_all_scrubbed():
    text = "steve@example.com, card 4111 1111 1111 1111, acct ending in 9876"
    clean, restore_map = scrub(text)
    assert "steve@example.com" not in clean
    assert "1111" not in clean
    assert "9876" not in clean
    assert len(restore_map) == 3
