import datetime as dt
import io
import json

from rich.console import Console
from typer.testing import CliRunner

from metapet import cli
from metapet.cli import app
from metapet.model import Idea
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


def test_ctrl_c_before_title_says_nothing_saved(home, monkeypatch):
    pet(home, "init")
    for stop in (KeyboardInterrupt(), EOFError()):
        interactive(monkeypatch, [stop])
        result = pet(home, "new")
        assert result.exit_code == 130
        assert "Cancelled. Nothing was saved." in result.output
        assert "Answers so far" not in result.output
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
    assert "2020-01-01" in result.output
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


def wide_ideas():
    return [
        Idea(id="x" * 60, title="T" * 200, tags=[f"tag{n}" for n in range(8)], excitement=3),
        Idea(id="short", title="Short one"),
    ]


def render(table, width):
    out = io.StringIO()
    Console(width=width, file=out, force_terminal=True, color_system=None).print(table)
    return out.getvalue().splitlines()


def test_table_one_line_per_idea_at_80(monkeypatch):
    ideas = wide_ideas()
    lines = render(cli._ideas_table(ideas, width=80), 80)
    assert len(lines) == len(ideas) + 1
    assert "title" in lines[0] and "status" in lines[0]
    assert all("seed" in line for line in lines[1:])
    assert "…" in lines[1]
    assert all(len(line) <= 80 for line in lines)


def test_table_drops_low_priority_columns_first():
    ideas = wide_ideas()
    narrow = render(cli._ideas_table(ideas, width=80), 80)[0]
    assert "created" not in narrow and "exc" in narrow
    wide = render(cli._ideas_table(ideas, width=160), 160)[0]
    for name in ("id", "title", "status", "exc", "tags", "imp", "effort", "created"):
        assert name in wide


def test_ls_piped_is_tab_separated(home):
    pet(home, "init")
    pet(home, "add", "Telegram bot that forwards RSS feeds", "-t", "telegram", "-t", "bot")
    lines = pet(home, "ls").output.splitlines()
    assert len(lines) == 1
    parts = lines[0].split("\t")
    assert len(parts) == 8
    assert parts[:4] == [
        "telegram-bot-that-forwards-rss-feeds",
        "seed",
        "Telegram bot that forwards RSS feeds",
        "telegram,bot",
    ]
    scored = pet(home, "ls", "--sort", "score").output.splitlines()[0].split("\t")
    assert len(scored) == 9


def test_check_reports_long_ids(home):
    pet(home, "init")
    long_id = "a" * 60
    (home.ideas / f"{long_id}.md").write_text(
        f"---\nid: {long_id}\ntitle: Long\nstatus: seed\ncreated: 2026-01-01\n---\n"
    )
    result = pet(home, "check")
    assert f"{long_id}.md: id is longer than 40 characters; shorten it with pet rename" in (
        result.output
    )


def test_show_prints_full_title_and_id(home):
    pet(home, "init")
    title = " ".join(["word"] * 40)  # 199 characters
    pet(home, "add", title, "--id", "flash")
    pet(home, "promote", "flash", "--no-input")
    result = runner.invoke(app, ["--home", str(home.path), "show", "flash"], env={"COLUMNS": "80"})
    assert result.exit_code == 0, result.output
    assert " ".join(result.output.split()).count(title) == 1
    assert "flash · sketch" in result.output
    assert "## Problem" not in result.output and "Problem" not in result.output.split("Empty:")[0]
    assert "Empty: Problem*, Who it's for, Rough solution*, Value, Why now" in result.output
    pet(home, "set", "flash", "problem=Hard to review")
    output = pet(home, "show", "flash").output
    assert "Problem" in output.split("Empty:")[0] and "Hard to review" in output
    assert "Empty: Who it's for" in output


class FakeContext:
    def __init__(self, home):
        self.params = {"home": str(home.path)}

    def find_root(self):
        return self


def test_completion_descriptions_are_one_line(home):
    pet(home, "init")
    pet(home, "add", "word " * 30, "--id", "spec")
    [(idea_id, description)] = cli._complete_ids(FakeContext(home), "s")
    assert idea_id == "spec"
    assert "\n" not in description and len(description) <= 50 and description.endswith("…")


def test_completion_falls_back_to_fragments(home):
    pet(home, "init")
    pet(home, "add", "داشبورد خانگی", "--id", "dashboard")
    pet(home, "add", "Telegram bot")
    assert [i for i, _ in cli._complete_ids(FakeContext(home), "خانگی")] == ["dashboard"]
    assert [i for i, _ in cli._complete_ids(FakeContext(home), "bot")] == ["telegram-bot"]
    assert [i for i, _ in cli._complete_ids(FakeContext(home), "tel")] == ["telegram-bot"]


def test_list_and_find_aliases(home):
    pet(home, "init")
    pet(home, "add", "Budget tracker")
    assert pet(home, "list").output == pet(home, "ls").output
    assert pet(home, "find", "budget").output == pet(home, "search", "budget").output
    assert "budget-tracker" in pet(home, "find", "budget").output
    help_text = runner.invoke(app, ["--help"], env={"COLUMNS": "200"}).output
    assert "│ list " not in help_text and "│ find " not in help_text
    assert "│ ls " in help_text


def test_rm_needs_yes_outside_terminal(home):
    pet(home, "init")
    pet(home, "add", "A")
    result = pet(home, "rm", "a")
    assert result.exit_code == 1
    assert "pass --yes to delete without asking" in result.output
    assert (home.ideas / "a.md").exists()


def test_rm_deletes_and_cleans_related(home, monkeypatch):
    pet(home, "init")
    pet(home, "add", "A")
    pet(home, "add", "B")
    pet(home, "add", "C")
    pet(home, "set", "b", "related=a,c")
    result = pet(home, "rm", "a", "--yes")
    assert result.exit_code == 0, result.output
    assert "- a" in result.output and "updated related in: b" in result.output
    assert sorted(p.name for p in home.ideas.iterdir()) == ["b.md", "c.md"]
    assert "- a\n" not in idea_text(home, "b") and "- c" in idea_text(home, "b")
    monkeypatch.setattr(cli, "_interactive", lambda no_input: True)
    assert "Not deleted." in pet(home, "rm", "c", input="n\n").output
    assert pet(home, "delete", "c", input="y\n").exit_code == 0
    assert pet(home, "delete", "b", "--yes").exit_code == 0
    assert list(home.ideas.iterdir()) == []


def test_add_duplicate_prints_note(home, monkeypatch):
    pet(home, "init")
    pet(home, "add", "Budget tracker")
    result = pet(home, "add", "budget  tracker!")
    assert "note: budget-tracker has the same name" in result.output
    assert (home.ideas / "budget-tracker-2.md").exists()
    prompter = interactive(monkeypatch, [False])
    result = pet(home, "new", "Budget tracker")
    assert result.exit_code == 0
    assert prompter.messages[-1].startswith("Nothing added.")
    assert len(list(home.ideas.iterdir())) == 2


def failing_edit(*args, **kwargs):
    raise cli.click.ClickException("/nonexistent: Editing failed")


def test_edit_with_failing_editor_is_one_line(home, monkeypatch):
    pet(home, "init")
    pet(home, "add", "Budget tracker")
    pet(home, "promote", "budget")
    monkeypatch.setattr(cli.click, "edit", failing_edit)
    for args in (["edit", "budget"], ["edit", "budget", "--field", "problem"]):
        result = pet(home, *args)
        assert result.exit_code == 1
        assert result.output.splitlines() == [
            "error: /nonexistent: Editing failed (set $EDITOR or $VISUAL)"
        ]


def test_edit_reports_broken_frontmatter(home, monkeypatch):
    pet(home, "init")
    pet(home, "add", "Budget tracker")
    path = home.ideas / "budget-tracker.md"

    def breaking_edit(filename=None, **kwargs):
        text = path.read_text(encoding="utf-8")
        path.write_text(text.replace("title: Budget tracker", "title: Budget: x: y"))

    monkeypatch.setattr(cli.click, "edit", breaking_edit)
    result = pet(home, "edit", "budget")
    assert result.exit_code == 1
    assert "budget-tracker.md cannot be read" in result.output
    assert "pet check" in result.output


def test_ls_warns_about_unreadable_files(home):
    pet(home, "init")
    pet(home, "add", "Budget tracker")
    (home.ideas / "pomo.md").write_text("---\ntitle: [unclosed\n---\n")
    for args in (["ls"], ["next"], ["search", "budget"], ["stats"], ["review"]):
        result = pet(home, *args)
        assert result.exit_code == 0, (args, result.output)
        assert (
            "warning: 1 idea file could not be read (pet check shows why): pomo.md"
            in result.output
        ), args
    result = pet(home, "show", "pomo")
    assert result.exit_code == 1
    assert "pomo.md cannot be read" in result.output
    assert "fix it with pet edit pomo" in result.output


def test_edit_opens_unreadable_file(home, monkeypatch):
    pet(home, "init")
    path = home.ideas / "pomo.md"
    path.write_text("---\ntitle: [unclosed\n---\n")
    opened = []

    def fixing_edit(filename=None, **kwargs):
        opened.append(filename)
        path.write_text("---\nid: pomo\ntitle: Pomodoro\nstatus: seed\ncreated: 2026-01-01\n---\n")

    monkeypatch.setattr(cli.click, "edit", fixing_edit)
    result = pet(home, "edit", "pomo")
    assert result.exit_code == 0, result.output
    assert opened == [str(path)]
    assert "Pomodoro" in pet(home, "show", "pomo").output


def test_add_dedupes_tags(home):
    pet(home, "init")
    pet(home, "add", "T", "-t", "bot", "-t", "bot", "-t", "BOT")
    assert idea_text(home, "t").lower().count("bot") == 1
    pet(home, "add", "Old", "-t", "telegram")
    pet(home, "add", "U", "-t", "Telegram")
    assert "- telegram" in idea_text(home, "u") and "Telegram" not in idea_text(home, "u")
    pet(home, "new", "V", "-t", "TELEGRAM", "-t", "telegram", "--no-input")
    assert idea_text(home, "v").count("telegram") == 1
    assert "bot 1" in pet(home, "stats").output


def test_check_warns_duplicate_sections(home):
    pet(home, "init")
    pet(home, "add", "Budget tracker", "-m", "x")
    path = home.ideas / "budget-tracker.md"
    path.write_text(path.read_text() + "\n## Problem\none\n\n## problem\ntwo\n")
    result = pet(home, "check")
    assert result.exit_code == 0
    assert "budget-tracker.md: two 'Problem' sections; only the first is used" in result.output


def test_check_prints_stages_path_once(home):
    pet(home, "init")
    home.stages_file.write_text(
        '[sketch]\n[[sketch.fields]]\nkey = "notes"\nlabel = "Problem"\nquestion = "Q?"\n'
        '[[sketch.fields]]\nkey = "problem"\nlabel = "Problem"\nquestion = "Q?"\n',
        encoding="utf-8",
    )
    result = pet(home, "check")
    assert result.exit_code == 1
    assert "✗" in result.output and "'notes'" in result.output
    assert " ".join(result.output.split()).count(str(home.stages_file)) == 1


def test_key_heading_is_not_empty(home):
    pet(home, "init")
    pet(home, "add", "Budget tracker")
    pet(home, "promote", "budget")
    path = home.ideas / "budget-tracker.md"
    path.write_text(path.read_text().replace("## Rough solution\n<!--", "## solution\nA CLI\n<!--"))
    assert "Rough solution" not in pet(home, "check").output
