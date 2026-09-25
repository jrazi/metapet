import datetime as dt
import json

from typer.testing import CliRunner

from metapet import cli
from metapet.cli import app
from metapet.prompter import ScriptedPrompter

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

    result = pet(
        home,
        "new",
        "Budget tracker",
        "-m",
        "Track stuff",
        "-t",
        "money",
        "-t",
        "cli",
        "-x",
        "4",
        "--set",
        "effort=m",
    )
    assert result.exit_code == 0, result.output
    budget = (home.ideas / "budget-tracker.md").read_text()
    assert "excitement: 4" in budget and "effort: M" in budget and "Track stuff" in budget

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
    added = pet(home, "add", "Long idea title that makes a long path", "-v").output
    assert str(home.ideas / "long-idea-title-that-makes-a-long-path.md") in added


def test_add_prints_id_and_title_without_path(home):
    pet(home, "init")
    assert pet(home, "add", "Budget tracker").output == "+ budget-tracker  Budget tracker\n"
    result = pet(home, "new", "x" * 55, "--id", "long", "--no-input")
    assert result.output == "+ long  " + "x" * 49 + "…\n"


def test_verbose_prints_path(home):
    pet(home, "init")
    added = pet(home, "add", "Budget tracker", "-v").output
    assert str(home.ideas / "budget-tracker.md") in added
    moved = pet(home, "promote", "budget", "-v").output
    assert moved.startswith("budget-tracker: seed → sketch")
    assert str(home.ideas / "budget-tracker.md") in moved
    assert "budget-tracker.md" not in pet(home, "promote", "budget").output


def test_set_prints_one_line_per_change(home):
    pet(home, "init")
    pet(home, "add", "Plant bot")
    pet(home, "promote", "plant")
    result = pet(home, "set", "plant", "problem=a b", "value=c")
    assert result.output.splitlines() == ["plant-bot: problem: a b", "  value: c"]


def complete(home, words):
    """Run pet's real bash completion for the given command line."""
    line = f"pet --home '{home.path}' {words}"  # quoted: Windows paths have backslashes
    # Index of the word being completed: a trailing space means a fresh, empty word.
    cword = len(line.split()) - (0 if line.endswith(" ") else 1)
    env = {"_PET_COMPLETE": "complete_bash", "COMP_WORDS": line, "COMP_CWORD": str(cword)}
    result = runner.invoke(app, [], env=env, prog_name="pet")
    return result.output.split()


def test_completes_idea_ids_from_the_selected_home(home):
    pet(home, "init")
    pet(home, "add", "Telegram bot")
    pet(home, "add", "Telegram game")
    pet(home, "add", "Budget tracker")
    assert complete(home, "show tel") == ["telegram-bot", "telegram-game"]
    assert complete(home, "promote bud") == ["budget-tracker"]
    assert complete(home, "edit ") == ["budget-tracker", "telegram-bot", "telegram-game"]


def test_completion_is_silent_without_a_store(home):
    assert complete(home, "show x") == []


def test_help_explains_the_lifecycle(home):
    for args in (["--help"], ["promote", "--help"]):
        output = runner.invoke(app, args, env={"COLUMNS": "200"}).output
        assert "seed → sketch → spec → building → shipped" in output
        assert "problem*, audience, solution*, value, why_now" in output
        assert "notes, links, related" in output
        assert "promote only warns" in output
        assert "stages.toml" in output


def test_lifecycle_help_rows_fit_in_80_columns(home):
    output = runner.invoke(app, ["--help"], env={"COLUMNS": "80"}).output
    assert "features*, mvp*, stack, risks, prior_art, effort, impact" in output
    assert "title*, summary, tags, excitement" in output


def idea_text(home, idea_id):
    return (home.ideas / f"{idea_id}.md").read_text(encoding="utf-8")


def test_new_needs_a_title(home):
    pet(home, "init")
    result = pet(home, "new", "--no-input")
    assert result.exit_code == 1
    assert 'a title is required: pet new "TITLE"' in result.output


def test_new_rejects_bad_values_without_creating_a_file(home):
    pet(home, "init")
    result = pet(home, "new", "Thing", "-x", "9", "--set", "bogus=1")
    assert result.exit_code == 1
    assert "excitement must be a number from 1 to 5" in result.output
    assert "unknown field 'bogus'" in result.output
    result = pet(home, "new", "Thing", "-x", "3", "--set", "excitement=4")
    assert result.exit_code == 1 and "both as a flag and with --set" in result.output
    assert list(home.ideas.iterdir()) == []


def test_new_can_fill_later_stage_fields(home):
    pet(home, "init")
    assert pet(home, "new", "Thing", "--set", "mvp=Just a script").exit_code == 0
    text = idea_text(home, "thing")
    assert "status: seed" in text and "## MVP scope\nJust a script" in text
    assert "updated:" not in text


def test_set_changes_fields_and_tags(home):
    pet(home, "init")
    pet(home, "add", "Budget tracker", "-t", "old", "-t", "keep")
    result = pet(home, "set", "budget", "excitement=4", "+cli", "-old", "features=a", "features=b")
    assert result.exit_code == 0, result.output
    assert result.output.splitlines() == [
        "budget-tracker: excitement: 4",
        "  features: a, b",
        "  tags: +cli",
        "  tags: -old",
    ]
    text = idea_text(home, "budget-tracker")
    assert "- keep\n- cli" in text and "## Features\n- a\n- b" in text
    assert pet(home, "set", "budget", "--", "-keep").exit_code == 0
    assert "keep" not in idea_text(home, "budget-tracker")


def test_set_with_a_bad_key_leaves_the_file_unchanged(home):
    pet(home, "init")
    pet(home, "add", "Budget tracker")
    before = idea_text(home, "budget-tracker")
    result = pet(home, "set", "budget", "excitement=4", "nope=1")
    assert result.exit_code == 1
    assert "unknown field 'nope'" in result.output
    assert idea_text(home, "budget-tracker") == before


def test_note_appends_a_dated_line(home):
    pet(home, "init")
    pet(home, "add", "Budget tracker", "-m", "Track stuff")
    assert pet(home, "note", "budget", "first\nthought").output.strip() == "budget-tracker: noted"
    pet(home, "note", "budget", "second")
    today = dt.date.today().isoformat()
    assert f"## Notes\n- {today}: first thought\n- {today}: second" in idea_text(
        home, "budget-tracker"
    )


def test_edit_one_field(home, monkeypatch):
    pet(home, "init")
    pet(home, "add", "Budget tracker")
    pet(home, "promote", "budget")
    seen = {}

    def fake_edit(text=None, **kwargs):
        seen["text"] = text
        return "It is hard to track money.\n"

    monkeypatch.setattr(cli.click, "edit", fake_edit)
    result = pet(home, "edit", "budget", "--field", "problem")
    assert result.exit_code == 0, result.output
    assert seen["text"] == "<!-- What problem does it solve? -->"
    text = idea_text(home, "budget-tracker")
    assert "## Problem\nIt is hard to track money.\n\n## Who it's for" in text

    monkeypatch.setattr(cli.click, "edit", lambda **kwargs: None)
    assert "no change" in pet(home, "edit", "budget", "--field", "Rough solution").output

    result = pet(home, "edit", "budget", "--field", "effort")
    assert result.exit_code == 1
    assert "use pet set ID effort=VALUE" in result.output


def test_promote_warns_about_empty_expected_fields(home):
    pet(home, "init")
    pet(home, "add", "Budget tracker")
    assert "warning" not in pet(home, "promote", "budget").output
    result = pet(home, "promote", "budget", "--no-input")
    assert result.exit_code == 0
    assert "sketch → spec" in result.output
    assert "warning: still empty: Problem, Rough solution" in result.output
    assert "status: spec" in idea_text(home, "budget-tracker")


def test_check_lists_readiness_and_warns(home):
    pet(home, "init")
    pet(home, "add", "Budget tracker")
    pet(home, "promote", "budget")
    home.templates.mkdir()
    result = pet(home, "check")
    assert result.exit_code == 0, result.output
    assert "i budget-tracker (sketch): empty: Problem, Rough solution" in result.output
    assert "templates/ is no longer used" in result.output
    assert "1 ideas OK" in result.output


def test_stages_shows_fields_from_the_stages_file(home):
    pet(home, "init")
    home.stages_file.write_text(
        '[sketch]\n\n[[sketch.fields]]\nkey = "vibe"\nlabel = "Vibe"\n'
        'question = "How should it feel?"\nrequired = true\n',
        encoding="utf-8",
    )
    result = pet(home, "stages")
    assert result.exit_code == 0, result.output
    assert "thought through for a few minutes" in result.output
    assert "vibe*" in result.output and "why_now" not in result.output
    assert "features*, mvp*" in result.output


def test_check_fails_on_bad_stages_file(home):
    pet(home, "init")
    home.stages_file.write_text("[nope]\n", encoding="utf-8")
    result = pet(home, "check")
    assert result.exit_code == 1
    assert "stages.toml:" in result.output and "unknown stage 'nope'" in result.output
    assert pet(home, "promote", "x").exit_code == 1


def interactive(monkeypatch, answers):
    """Make the CLI think it runs in a terminal, answering from a script."""
    prompter = ScriptedPrompter(answers)
    monkeypatch.setattr(cli, "_interactive", lambda no_input: not no_input)
    monkeypatch.setattr(cli, "_prompter", lambda: prompter)
    return prompter


def test_new_asks_questions_in_a_terminal(home, monkeypatch):
    pet(home, "init")
    pet(home, "add", "Old idea", "-t", "money")
    prompter = interactive(monkeypatch, ["", "Budget tracker", "Track spending.", 4, False])
    result = pet(home, "new", "-t", "money")
    assert result.exit_code == 0, result.output
    assert "budget-tracker" in result.output
    assert prompter.messages[0] == "A name is needed (Ctrl-C to cancel)."
    methods = [method for method, _, _ in prompter.calls]
    assert methods == ["text", "text", "text", "scale", "confirm"]  # tags were given
    text = idea_text(home, "budget-tracker")
    assert "excitement: 4" in text and "Track spending." in text and "- money" in text


def test_new_with_no_input_asks_nothing(home, monkeypatch):
    pet(home, "init")
    interactive(monkeypatch, [])
    assert pet(home, "new", "Thing", "--no-input").exit_code == 0
    assert pet(home, "new", "--no-input").exit_code == 1


def test_ctrl_c_keeps_answers_and_exits_130(home, monkeypatch):
    pet(home, "init")
    interactive(monkeypatch, ["Track spending.", KeyboardInterrupt()])
    result = pet(home, "new", "Budget tracker")
    assert result.exit_code == 130
    assert "Stopped. Answers so far are saved." in result.output
    assert "Track spending." in idea_text(home, "budget-tracker")


def test_ctrl_c_before_the_title_creates_nothing(home, monkeypatch):
    pet(home, "init")
    interactive(monkeypatch, [KeyboardInterrupt()])
    assert pet(home, "new").exit_code == 130
    assert list(home.ideas.iterdir()) == []


def test_refine_in_a_terminal(home, monkeypatch):
    pet(home, "init")
    pet(home, "add", "Budget tracker")
    interactive(monkeypatch, ["Track spending."])
    result = pet(home, "refine", "budget", "summary")
    assert result.exit_code == 0, result.output
    assert "Track spending." in idea_text(home, "budget-tracker")

    result = pet(home, "refine", "budget", "mvp")
    assert result.exit_code == 1
    assert "'mvp' belongs to the spec stage" in result.output


def test_promote_in_a_terminal_can_be_cancelled(home, monkeypatch):
    pet(home, "init")
    pet(home, "add", "Budget tracker")
    pet(home, "promote", "budget")
    interactive(monkeypatch, ["cancel"])
    result = pet(home, "promote", "budget")
    assert result.exit_code == 0 and "Not promoted." in result.output
    assert "status: sketch" in idea_text(home, "budget-tracker")


def test_without_a_terminal_nothing_is_asked(home, monkeypatch):
    monkeypatch.setattr(cli, "_prompter", lambda: ScriptedPrompter([]))
    pet(home, "init")
    result = pet(home, "add", "Budget tracker", "-i")
    assert result.exit_code == 0
    assert "note: not a terminal, skipping questions" in result.output
    assert pet(home, "promote", "budget").exit_code == 0
    result = pet(home, "refine", "budget")
    assert result.exit_code == 1
    assert "refine needs a terminal" in result.output


def make_old(home, idea_id):
    path = home.ideas / f"{idea_id}.md"
    text = path.read_text(encoding="utf-8")
    today = dt.date.today().isoformat()
    path.write_text(text.replace(f"created: {today}", "created: 2020-01-01"), encoding="utf-8")


def test_review_without_a_terminal_lists_due_ideas(home):
    pet(home, "init")
    pet(home, "add", "Budget tracker")
    pet(home, "add", "Recipe box")
    make_old(home, "budget-tracker")
    result = pet(home, "review")
    assert result.exit_code == 0, result.output
    assert "budget-tracker" in result.output and "recipe-box" not in result.output
    assert "last seen" in result.output and "2020-01-01" in result.output
    assert "Run pet review in a terminal to go through them." in result.output
    assert "reviewed:" not in idea_text(home, "budget-tracker")


def test_review_list_keeps_last_seen_whole_at_80_columns(home):
    pet(home, "init")
    pet(home, "add", "Budget tracker", "-t", "money", "-t", "finance")
    make_old(home, "budget-tracker")
    args = ["--home", str(home.path), "review"]
    output = runner.invoke(app, args, env={"COLUMNS": "80"}).output
    assert "2020-01-01" in output
    assert "created" not in output


def test_review_with_nothing_due(home):
    pet(home, "init")
    pet(home, "add", "Budget tracker")
    result = pet(home, "review", "--days", "7")
    assert result.exit_code == 0
    assert "Nothing to review. Everything was looked at in the last 7 days." in result.output


def test_review_in_a_terminal(home, monkeypatch):
    pet(home, "init")
    pet(home, "add", "Budget tracker")
    make_old(home, "budget-tracker")
    interactive(monkeypatch, ["skip"])
    result = pet(home, "review")
    assert result.exit_code == 0, result.output
    assert "Reviewed 1, 0 left." in result.output
    assert f"reviewed: {dt.date.today().isoformat()}" in idea_text(home, "budget-tracker")


def test_review_ctrl_c_exits_130(home, monkeypatch):
    pet(home, "init")
    pet(home, "add", "Budget tracker")
    make_old(home, "budget-tracker")
    interactive(monkeypatch, [KeyboardInterrupt()])
    result = pet(home, "review")
    assert result.exit_code == 130
    assert "Reviewed 0, 1 left." in result.output
    assert "Stopped. Answers so far are saved." in result.output


def test_bare_pet_without_a_terminal_prints_help(home):
    result = pet(home)
    assert result.exit_code == 0
    assert "Usage" in result.output and "Capture and grow" in result.output


def test_bare_pet_in_a_terminal_opens_the_ui(home, monkeypatch):
    from metapet.tui import PetApp

    opened = []
    monkeypatch.setattr(cli, "_interactive", lambda no_input: True)
    monkeypatch.setattr(PetApp, "run", lambda self: opened.append(self))
    assert pet(home).exit_code == 1  # no store yet
    pet(home, "init")
    assert pet(home).exit_code == 0
    assert pet(home, "ui").exit_code == 0
    assert len(opened) == 2


def test_ui_without_a_terminal_fails(home):
    pet(home, "init")
    result = pet(home, "ui")
    assert result.exit_code == 1
    assert "needs a terminal" in result.output


def test_brackets_in_titles_and_tags_are_shown_literally(home):
    pet(home, "init")
    pet(home, "add", "Regex tester [/]")
    pet(home, "add", "Todo [bold] app", "-t", "[red]")
    outputs = {}
    for args in (["ls"], ["next"], ["show", "regex"], ["show", "todo"], ["search", "todo"],
                 ["stats"], ["random"]):
        result = pet(home, *args)
        assert result.exit_code == 0, (args, result.output)
        outputs[args[0] + " " + " ".join(args[1:])] = result.output
    assert "[/]" in outputs["show regex"]
    assert "Todo [bold] app" in outputs["show todo"] and "[red]" in outputs["show todo"]
    assert "[red]" in outputs["search todo"]
    assert "[red] 1" in outputs["stats "]


def test_add_rejects_blank_title(home):
    pet(home, "init")
    for title in ("", "   "):
        result = pet(home, "add", title)
        assert result.exit_code == 1
        assert 'a title is required: pet add "TITLE"' in result.output
    assert list(home.ideas.iterdir()) == []


def test_add_and_new_accept_id(home):
    pet(home, "init")
    assert pet(home, "add", "Plant bot", "--id", "plants").exit_code == 0
    assert (home.ideas / "plants.md").exists()
    assert pet(home, "new", "Garden", "--id", "Garden-Two", "--no-input").exit_code == 0
    assert (home.ideas / "garden-two.md").exists()
    result = pet(home, "add", "X", "--id", "Bad Id")
    assert result.exit_code == 1 and "single hyphens" in result.output
    result = pet(home, "new", "X", "--id", "plants", "--no-input")
    assert result.exit_code == 1 and "an idea with id 'plants' already exists" in result.output
    assert sorted(p.name for p in home.ideas.iterdir()) == ["garden-two.md", "plants.md"]


def test_rename_without_new_id_uses_title(home):
    pet(home, "init")
    pet(home, "add", "Plant bot", "--id", "plants")
    pet(home, "add", "Other")
    pet(home, "set", "other", "related=plants")
    result = pet(home, "rename", "plants", "watering")
    assert result.exit_code == 0, result.output
    assert "plants → watering" in result.output
    assert "updated related in: other" in result.output
    assert "- watering" in idea_text(home, "other")
    pet(home, "set", "watering", "title=Garden helper")
    result = pet(home, "rename", "watering")
    assert "watering → garden-helper" in result.output
    assert "garden-helper: no change" in pet(home, "rename", "garden-helper").output


def test_set_id_points_to_rename(home):
    pet(home, "init")
    pet(home, "add", "Garden")
    result = pet(home, "set", "garden", "id=x")
    assert result.exit_code == 1
    assert "use pet rename ID NEW_ID to change the id" in result.output


LONG = (
    "A safe, reversible CLI that turns a messy folder of downloaded files into a clean, "
    "organized library: it detects duplicates and shows a dry-run plan first."
)


def test_add_long_title_is_shortened(home):
    pet(home, "init")
    result = pet(home, "add", LONG)
    assert result.exit_code == 0, result.output
    assert 'note: the title was long; kept "A safe, reversible CLI that turns a messy"' in (
        result.output
    )
    idea_id = "safe-reversible-cli-that-turns-a-messy"
    text = idea_text(home, idea_id)
    assert "title: A safe, reversible CLI that turns a messy\n" in text
    assert LONG in text


def test_add_long_title_with_id_is_kept(home):
    pet(home, "init")
    assert pet(home, "add", LONG, "--id", "tidy").exit_code == 0
    assert "note:" not in pet(home, "show", "tidy").output
    assert "organized library" in idea_text(home, "tidy").split("---")[1]


def test_new_long_title_in_a_terminal_goes_to_summary(home, monkeypatch):
    pet(home, "init")
    interactive(monkeypatch, [LONG, True, "Downloads tidier", None, None, False])
    result = pet(home, "new", "-m", "First line.")
    assert result.exit_code == 0, result.output
    text = idea_text(home, "downloads-tidier")
    assert "title: Downloads tidier" in text
    assert f"First line.\n\n{LONG}" in text
