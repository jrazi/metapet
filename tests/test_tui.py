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
    table = app.query_one("#ideas", DataTable)
    return [str(table.get_row_at(i)[0]) for i in range(table.row_count)]


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
        assert str(table.get_row("budget-tracker")[2]) == "sketch"
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
