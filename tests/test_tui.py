import asyncio

from textual.widgets import DataTable, Footer, Input

from metapet import schema, stages
from metapet.model import Idea, Status
from metapet.prompter import ScriptedPrompter
from metapet.tui import EMPTY_STORE, PetApp, TextPrompt

S = schema.builtin()


def make_app(store, answers=None, outside=None):
    prompter = ScriptedPrompter(answers or [])
    calls = outside if outside is not None else []

    def run_outside(fn):
        calls.append(fn)
        fn()

    app = PetApp(store, S, prompter=lambda: prompter, run_outside=run_outside)
    return app, prompter


def rows(app) -> list[str]:
    """The keys of the rows in order: the file names without .md."""
    table = app.query_one("#ideas", DataTable)
    return [row.key.value for row in table.ordered_rows]


def on_disk(store, idea_id) -> Idea:
    return Idea.load(store.home.ideas / f"{idea_id}.md")


def run(app, test):
    async def main():
        async with app.run_test() as pilot:
            await pilot.pause()
            await test(pilot)

    asyncio.run(main())


def seeded(store):
    store.create("Budget tracker", tags=["money"])
    store.create("Telegram bot", tags=["cli"])
    old = store.create("Old game")
    stages.move(old, Status.SHELVED, S)
    old.shelved_reason = "no time"
    store.save(old)


def test_lists_live_ideas(store):
    seeded(store)
    app, _ = make_app(store)

    async def test(pilot):
        assert sorted(rows(app)) == ["budget-tracker", "telegram-bot"]

    run(app, test)


def test_empty_store_says_how_to_add(store):
    app, _ = make_app(store)

    async def test(pilot):
        assert rows(app) == []
        assert app.query_one("#preview").source == EMPTY_STORE

    run(app, test)


def test_filter_narrows_and_shows_shelved(store):
    seeded(store)
    app, _ = make_app(store)

    async def test(pilot):
        await pilot.press("slash")
        assert app.focused is app.query_one("#filter", Input)
        await pilot.press(*"money")
        assert rows(app) == ["budget-tracker"]
        app.query_one("#filter", Input).value = "status:shelved"
        await pilot.pause()
        assert rows(app) == ["old-game"]
        await pilot.press("escape")
        assert sorted(rows(app)) == ["budget-tracker", "telegram-bot"]
        assert not app.query_one("#filter", Input).display

    run(app, test)


def select(app, idea_id):
    table = app.query_one("#ideas", DataTable)
    table.move_cursor(row=table.get_row_index(idea_id))


def test_note_is_added_to_the_file(store):
    seeded(store)
    app, _ = make_app(store)

    async def test(pilot):
        select(app, "telegram-bot")
        await pilot.press("n")
        await pilot.press(*"try inline mode")
        await pilot.press("enter")
        await pilot.pause()
        assert "try inline mode" in on_disk(store, "telegram-bot").body

    run(app, test)


def test_note_dialog_says_how_to_save_and_hides_main_keys(store):
    seeded(store)
    app, _ = make_app(store)

    async def test(pilot):
        await pilot.press("n")
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, TextPrompt)
        hints = [str(label.render()) for label in screen.query(".hint")]
        assert hints == ["Enter to save, Escape to cancel."]
        shown = {b.binding.description for b in screen.active_bindings.values() if b.binding.show}
        assert "Promote" not in shown
        screen.query_one(Footer)

    run(app, test)


def test_excitement_is_set_with_a_key(store):
    seeded(store)
    app, _ = make_app(store)

    async def test(pilot):
        select(app, "budget-tracker")
        await pilot.press("x", "4")
        await pilot.pause()
        assert on_disk(store, "budget-tracker").excitement == 4
        await pilot.press("x", "escape")
        await pilot.pause()
        assert on_disk(store, "budget-tracker").excitement == 4

    run(app, test)


def test_shelve_with_a_reason(store):
    seeded(store)
    app, _ = make_app(store)

    async def test(pilot):
        select(app, "budget-tracker")
        await pilot.press("s")
        await pilot.press(*"too big")
        await pilot.press("enter")
        await pilot.pause()
        idea = on_disk(store, "budget-tracker")
        assert idea.status == Status.SHELVED and idea.shelved_reason == "too big"
        assert rows(app) == ["telegram-bot"]

    run(app, test)


def test_shelve_cancelled_with_escape(store):
    seeded(store)
    app, _ = make_app(store)

    async def test(pilot):
        select(app, "budget-tracker")
        await pilot.press("s", "escape")
        await pilot.pause()
        assert on_disk(store, "budget-tracker").status == Status.SEED

    run(app, test)


def test_promote_runs_the_questions_outside_the_ui(store):
    seeded(store)
    calls = []
    # Sketch questions: problem, audience, solution, value, why_now.
    app, prompter = make_app(store, ["Hard to see spending.", None, None, None, None], calls)

    async def test(pilot):
        select(app, "budget-tracker")
        await pilot.press("p")
        await pilot.pause()
        assert len(calls) == 1
        idea = on_disk(store, "budget-tracker")
        assert idea.status == Status.SKETCH
        assert "Hard to see spending." in idea.body
        table = app.query_one("#ideas", DataTable)
        assert str(table.get_row("budget-tracker")[1]) == "sketch"
        assert app.current_id() == "budget-tracker"

    run(app, test)


def test_add_selects_the_new_idea(store):
    seeded(store)
    # Title, summary, tags, excitement, then no to the next stage.
    app, _ = make_app(store, ["Plant waterer", "Waters plants.", None, 3, False])

    async def test(pilot):
        await pilot.press("a")
        await pilot.pause()
        assert app.current_id() == "plant-waterer"
        assert on_disk(store, "plant-waterer").excitement == 3

    run(app, test)


def test_ctrl_c_in_questions_keeps_the_ui_running(store):
    seeded(store)
    app, _ = make_app(store, [KeyboardInterrupt()])

    async def test(pilot):
        await pilot.press("a")
        await pilot.pause()
        assert app.is_running
        assert sorted(rows(app)) == ["budget-tracker", "telegram-bot"]

    run(app, test)


def test_q_quits(store):
    app, _ = make_app(store)

    async def test(pilot):
        await pilot.press("q")
        await pilot.pause()
        assert not app.is_running

    run(app, test)


def test_preview_hides_empty_sections(store):
    idea = store.create("Budget tracker")
    stages.move(idea, Status.SKETCH, S)
    store.save(idea)
    app, _ = make_app(store)

    async def test(pilot):
        source = app.query_one("#preview").source
        assert "budget-tracker · sketch" in source
        assert "Empty: Problem" in source
        assert "## Problem" not in source

    run(app, test)


def test_empty_note_keeps_dialog_open(store):
    seeded(store)
    app, _ = make_app(store)

    async def test(pilot):
        await pilot.press("n", "enter")
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, TextPrompt)
        hints = [str(label.render()) for label in screen.query(".hint")]
        assert hints == ["Type something, or press Escape to cancel."]
        await pilot.press("escape")
        await pilot.pause()
        assert not isinstance(app.screen, TextPrompt)

    run(app, test)


def notices(app) -> list[str]:
    return [n.message for n in app._notifications]


def test_add_cancelled_says_nothing_added(store):
    seeded(store)
    app, _ = make_app(store, [KeyboardInterrupt()])

    async def test(pilot):
        await pilot.press("a")
        await pilot.pause()
        assert notices(app) == ["Nothing added."]

    run(app, test)


def test_empty_store_keys_say_how_to_add(store):
    app, _ = make_app(store)

    async def test(pilot):
        await pilot.press("n", "p", "s")
        await pilot.pause()
        assert notices(app) == [EMPTY_STORE]

    run(app, test)


def test_unreadable_file_is_listed_and_editable(store, monkeypatch):
    seeded(store)
    path = store.home.ideas / "pomo.md"
    path.write_text("---\ntitle: [unclosed\n---\n")
    edited = []
    monkeypatch.setattr(
        "metapet.tui.click.edit", lambda filename=None, **kw: edited.append(filename)
    )
    app, _ = make_app(store)

    async def test(pilot):
        select(app, "pomo")
        table = app.query_one("#ideas", DataTable)
        assert str(table.get_row("pomo")[1]) == "unreadable"
        assert "cannot be read" in app.query_one("#preview").source
        await pilot.press("n")
        await pilot.pause()
        assert notices(app)[-1] == "Fix this file first (press e)."
        await pilot.press("e")
        await pilot.pause()
        assert edited == [str(path)]
        assert app.current_id() == "pomo"

    run(app, test)


def test_list_shows_title_and_status_at_80_columns(store):
    store.create("Telegram bot that downloads music from Spotify links and sends back files")
    app, _ = make_app(store)

    async def test(pilot):
        table = app.query_one("#ideas", DataTable)
        labels = [str(column.label) for column in table.ordered_columns]
        assert labels == ["title", "status", "exc", "imp", "effort"]
        title, status = (str(cell) for cell in table.get_row_at(0)[:2])
        assert title.startswith("Telegram bot") and title.endswith("…")
        assert status == "seed"
        total = sum(column.get_render_width(table) for column in table.ordered_columns)
        assert total <= table.size.width

    async def main():
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            await test(pilot)

    asyncio.run(main())


def test_new_idea_is_first(store):
    seeded(store)
    app, _ = make_app(store, ["Zeta idea", None, None, None, False])

    async def test(pilot):
        await pilot.press("a")
        await pilot.pause()
        assert rows(app)[0] == "zeta-idea"

    run(app, test)


def test_footer_shows_filter_and_quit_at_80(store):
    seeded(store)
    app, _ = make_app(store)

    async def test(pilot):
        shown = [
            b.binding.description for b in app.screen.active_bindings.values() if b.binding.show
        ]
        assert shown[:2] == ["Filter", "Quit"]
        assert not app.ENABLE_COMMAND_PALETTE

    async def main():
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            await test(pilot)

    asyncio.run(main())


def test_escape_clears_filter(store):
    seeded(store)
    app, _ = make_app(store)

    async def test(pilot):
        await pilot.press("slash", *"money", "enter")
        await pilot.pause()
        assert rows(app) == ["budget-tracker"]
        assert app.focused is app.query_one("#ideas", DataTable)
        await pilot.press("escape")
        await pilot.pause()
        assert sorted(rows(app)) == ["budget-tracker", "telegram-bot"]

    run(app, test)


def test_unknown_status_is_reported(store):
    seeded(store)
    app, _ = make_app(store)

    async def test(pilot):
        app.query_one("#filter", Input).value = "status:bogus"
        await pilot.pause()
        source = app.query_one("#preview").source
        assert source.startswith("Unknown status: bogus (seed, sketch, spec")

    run(app, test)


def test_excitement_dialog_shows_current_value(store):
    seeded(store)
    idea = on_disk(store, "budget-tracker")
    idea.excitement = 3
    store.save(idea)
    app, _ = make_app(store)

    async def test(pilot):
        select(app, "budget-tracker")
        await pilot.press("x")
        await pilot.pause()
        labels = [str(label.render()) for label in app.screen.query("Label")]
        assert labels[0] == "How excited are you about Budget tracker? (now 3)"

    run(app, test)


def test_promote_shelved_idea_moves_back(store):
    seeded(store)
    app, _ = make_app(store)

    async def test(pilot):
        app.query_one("#filter", Input).value = "status:shelved"
        await pilot.pause()
        select(app, "old-game")
        await pilot.press("p")
        await pilot.pause()
        labels = [str(label.render()) for label in app.screen.query("Label")]
        assert labels[0] == "Move Old game back to: 1 seed, 2 sketch, 3 spec, 4 building"
        await pilot.press("2")
        await pilot.pause()
        idea = on_disk(store, "old-game")
        assert idea.status == Status.SKETCH
        assert "Back from the shelf (it was shelved: no time)" in idea.body
        assert notices(app)[-1] == "old-game: shelved → sketch"

    run(app, test)


def test_title_column_follows_every_resize(store):
    store.create("Telegram bot that downloads music from Spotify links and sends back files")
    app, _ = make_app(store)

    def widths(table):
        columns = table.ordered_columns
        return sum(column.get_render_width(table) for column in columns), table.size.width

    async def main():
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            table = app.query_one("#ideas", DataTable)
            for size in [(160, 45), (80, 24), (120, 30)]:
                await pilot.resize_terminal(*size)
                await pilot.pause()
                await pilot.pause()
                total, available = widths(table)
                # The columns fill the pane, leaving only room for a scrollbar.
                assert available - 6 <= total <= available, (size, total, available)

    asyncio.run(main())

