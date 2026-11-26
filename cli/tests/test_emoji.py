import pytest

from deckdock.format.emoji import is_single_emoji

ACCEPTED = [
    "📚",
    "🇫🇷",
    "👩‍💻",
    "👨‍👩‍👧‍👦",
    "👍🏽",
    "1️⃣",
    "#⃣",
    "❤️",
    "🏴\U000e0067\U000e0062\U000e0073\U000e0063\U000e0074\U000e007f",
    "🗺️",
    "©",
]

REFUSED = [
    "",
    "a",
    "📚📚",
    "📚 ",
    " 📚",
    "🇫",
    "🇫🇷🇩🇪",
    "📚a",
    "‍📚",
    "📚‍",
    "🏽",
    "1",
    "️",
    "🇫🇷‍📚",
    "🏴\U000e0067",
]


@pytest.mark.parametrize("value", ACCEPTED)
def test_single_emoji_accepted(value: str):
    assert is_single_emoji(value)


@pytest.mark.parametrize("value", REFUSED)
def test_not_a_single_emoji_refused(value: str):
    assert not is_single_emoji(value)


def test_longer_than_64_bytes_refused():
    assert not is_single_emoji("‍".join(["👩"] * 20))
