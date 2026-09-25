import datetime as dt

import pytest

from metapet import ids

TODAY = dt.date(2026, 9, 25)


@pytest.mark.parametrize(
    "title, expected, exact",
    [
        ("Spotify downloader bot for Telegram", "spotify-downloader-bot-for-telegram", True),
        (
            "A safe, reversible CLI that turns a messy folder of downloaded files into a clean "
            "library",
            "safe-reversible-cli-that-turns-a-messy",
            False,
        ),
        ("C++ / C# port of make", "cpp-csharp-port-of-make", True),
        ("Телеграм бот для погоды", "telegram-bot-dlya-pogody", False),
        (
            "Music library tagger that fixes ID3 tags from MusicBrainz and renames files",
            "music-library-tagger-that-fixes-id3-tags",
            False,
        ),
        ("!!!", "idea-20260925", False),
        ("x" * 50, "x" * 40, False),
        ("The budget tracker", "budget-tracker", True),
        ("Tom & Jerry", "tom-and-jerry", True),
        ("Café app", "cafe-app", False),
    ],
)
def test_suggest(title, expected, exact):
    suggestion = ids.suggest(title, TODAY)
    assert suggestion == ids.Suggestion(expected, exact)
    assert len(suggestion.id) <= ids.ID_MAX


def test_suggest_makes_latin_ids_for_other_scripts():
    suggestion = ids.suggest("داشبورد خانگی برای رزبری پای", TODAY)
    assert ids.ID_PATTERN.match(suggestion.id)
    assert not suggestion.id.startswith("idea")


def test_cut_ids_drop_trailing_stop_words():
    title = "Telegram bot for downloading music from and to the"
    assert ids.suggest(title + " very long words here", TODAY).id == (
        "telegram-bot-for-downloading-music"
    )


@pytest.mark.parametrize("text, expected", [("plant-bot", "plant-bot"), ("Plant-Bot", "plant-bot")])
def test_validate_accepts(text, expected):
    assert ids.validate(text) == expected


@pytest.mark.parametrize("text", ["plant bot", "-x", "a--b", "x" * 41, "", "x-"])
def test_validate_rejects(text):
    with pytest.raises(ValueError, match="lowercase letters, digits and single hyphens"):
        ids.validate(text)


def test_with_suffix_keeps_whole_words():
    base = "one-two-three-four-five-six-seven-eight"
    assert ids.with_suffix(base, 2) == "one-two-three-four-five-six-seven-2"
    assert ids.with_suffix("short", 3) == "short-3"
    assert ids.with_suffix("x" * 40, 2) == "x" * 38 + "-2"
    assert len(ids.with_suffix("apps-for-the-" + "y" * 30, 12)) <= ids.ID_MAX
