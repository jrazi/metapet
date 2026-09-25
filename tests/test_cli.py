import json

from typer.testing import CliRunner

from metapet import cli
from metapet.cli import app

runner = CliRunner()


def pet(home, *args, input=None):
    result = runner.invoke(app, ["--home", str(home.path), *args], input=input)
    return result


def test_commands_require_init(home):
    result = pet(home, "ls")
    assert result.exit_code == 1
    assert "pet init" in result.output


def test_capture_browse_and_grow(home, tmp_path):
    assert pet(home, "init").exit_code == 0
    assert pet(home, "where").output.startswith(str(home.path))

    result = pet(
        home, "add", "Spotify downloader bot for Telegram", "-t", "bot", "-m", "Links in, MP3 out."
    )
    assert result.exit_code == 0, result.output
    assert (home.ideas / "spotify-downloader-bot-for-telegram.md").exists()

    result = pet(home, "new", "--no-edit", input="Budget tracker\nTrack stuff\nmoney, cli\n4\nm\n")
    assert result.exit_code == 0, result.output

    listing = pet(home, "ls", "--tag", "bot").output
    assert "spotify-downloader" in listing and "budget-tracker" not in listing

    assert "Links in, MP3 out." in pet(home, "show", "spotify").output
    assert "budget-tracker" in pet(home, "search", "money").output

    result = pet(home, "promote", "spotify")
    assert result.exit_code == 0, result.output
    assert "## Problem" in (home.ideas / "spotify-downloader-bot-for-telegram.md").read_text()

    assert pet(home, "shelve", "budget", "not now").exit_code == 0
    assert "budget-tracker" not in pet(home, "ls").output
    assert "budget-tracker" in pet(home, "ls", "--all").output

    assert "spotify" in pet(home, "next").output
    assert "2 ideas" in pet(home, "stats").output
    assert pet(home, "check").exit_code == 0

    out = tmp_path / "ideas.json"
    assert pet(home, "export", "--json", str(out)).exit_code == 0
    assert {i["id"] for i in json.loads(out.read_text())} == {
        "spotify-downloader-bot-for-telegram",
        "budget-tracker",
    }


def test_ambiguous_id_lists_candidates(home):
    pet(home, "init")
    pet(home, "add", "Telegram bot")
    pet(home, "add", "Telegram game")
    result = pet(home, "show", "telegram")
    assert result.exit_code == 1
    assert "telegram-bot" in result.output and "telegram-game" in result.output


def test_check_fails_on_broken_file(home):
    pet(home, "init")
    (home.ideas / "bad.md").write_text("no frontmatter here\n")
    assert pet(home, "check").exit_code == 1


def test_long_paths_are_never_wrapped(home, monkeypatch):
    monkeypatch.setattr(cli.console, "width", 20)
    pet(home, "init")
    assert pet(home, "where").output.startswith(str(home.path))
    added = pet(home, "add", "A very long idea title that makes a long path").output
    assert str(home.ideas / "a-very-long-idea-title-that-makes-a-long-path.md") in added
