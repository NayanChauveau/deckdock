from deckdock.guid import card_guid, guid_for


def test_pinned_vectors():
    assert card_guid("hello-deck", "hello-001", "fr") == "x^#+V>S%em"
    assert card_guid("hello-deck", "hello-001", "en") == "kCwaq3>(Jd"


def test_guid_is_deterministic_and_anki_safe():
    g = guid_for("a", "b")
    assert g == guid_for("a", "b") and g != guid_for("a", "c")
    assert g and not any(ch.isspace() or ch in "\"'\\" for ch in g)
