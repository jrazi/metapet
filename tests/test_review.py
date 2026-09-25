import datetime as dt

from metapet import fields, review, schema, stages, wizard
from metapet.model import Idea, Status
from metapet.prompter import ScriptedPrompter

S = schema.builtin()
TODAY = dt.date(2026, 3, 1)
OLD = dt.date(2026, 1, 1)


def session(store, answers):
    prompter = ScriptedPrompter(answers)
    s = wizard.Session(S, prompter, store.save, store.all_tags(), today=TODAY)
    return s, prompter


def on_disk(store, idea) -> Idea:
    return Idea.load(store.home.ideas / f"{idea.id}.md")


def selects(prompter) -> int:
    return sum(1 for method, _, _ in prompter.calls if method == "select")


def old_idea(store, title="Budget tracker", status=Status.SEED) -> Idea:
    idea = store.create(title, created=OLD)
    if status != Status.SEED:
        stages.move(idea, status, S)
        idea.updated = None
    store.save(idea)
    return idea


# -- due -------------------------------------------------------------------------


def test_due_uses_the_latest_of_reviewed_updated_and_created():
    ideas = [
        Idea(id="created", title="a", created=OLD),
        Idea(id="updated", title="b", created=OLD, updated=dt.date(2026, 2, 20)),
        Idea(id="reviewed", title="c", created=OLD, reviewed=dt.date(2026, 2, 25)),
    ]
    assert [i.id for i in review.due(ideas, 14, TODAY)] == ["created"]
    assert review.last_seen(ideas[2]) == dt.date(2026, 2, 25)


def test_due_excludes_shipped_and_shelved():
    ideas = [
        Idea(id="shipped", title="a", created=OLD, status=Status.SHIPPED),
        Idea(id="shelved", title="b", created=OLD, status=Status.SHELVED),
        Idea(id="spec", title="c", created=OLD, status=Status.SPEC),
    ]
    assert [i.id for i in review.due(ideas, 14, TODAY)] == ["spec"]


def test_due_counts_whole_days():
    ideas = [
        Idea(id="exactly", title="a", created=TODAY - dt.timedelta(days=14)),
        Idea(id="one-short", title="b", created=TODAY - dt.timedelta(days=13)),
    ]
    assert [i.id for i in review.due(ideas, 14, TODAY)] == ["exactly"]
    assert len(review.due(ideas, 0, TODAY)) == 2


def test_due_sorts_oldest_first_then_by_id():
    ideas = [
        Idea(id="b", title="b", created=OLD),
        Idea(id="newer", title="c", created=dt.date(2026, 1, 10)),
        Idea(id="a", title="a", created=OLD),
    ]
    assert [i.id for i in review.due(ideas, 14, TODAY)] == ["a", "b", "newer"]


# -- run -------------------------------------------------------------------------


def test_skip_marks_the_idea_reviewed_without_other_changes(store):
    idea = old_idea(store)
    s, p = session(store, ["skip"])
    result = review.run(s, [idea])
    assert (result.handled, result.remaining, result.stopped) == (1, 0, False)
    saved = on_disk(store, idea)
    assert saved.reviewed == TODAY and saved.updated is None
    assert p.messages[0] == "1 idea to review."
    assert p.cards[0].title == "Budget tracker"


def test_menu_offers_promote_to_the_next_stage(store):
    idea = old_idea(store, status=Status.BUILDING)
    s, p = session(store, ["skip"])
    review.run(s, [idea])
    labels = [label for _, label in p.calls[0][2]["options"]]
    assert labels == [
        "Promote to shipped",
        "Refine",
        "Add a note",
        "Set excitement",
        "Shelve",
        "Skip",
        "Quit",
    ]


def test_promote_asks_the_new_stage_questions(store):
    idea = old_idea(store)
    s, _ = session(store, ["promote", "Too many tabs.", None, None, None, None])
    assert review.run(s, [idea]).handled == 1
    saved = on_disk(store, idea)
    assert saved.status == Status.SKETCH and saved.reviewed == TODAY
    assert fields.get(saved, S.field("problem")) == "Too many tabs."


def test_cancelled_promote_shows_the_menu_again(store):
    idea = old_idea(store, status=Status.SKETCH)
    s, p = session(store, ["promote", "cancel", "skip"])
    review.run(s, [idea])
    assert selects(p) == 3  # menu, gaps menu, menu again
    assert on_disk(store, idea).status == Status.SKETCH


def test_refine_uses_the_field_picker(store):
    idea = old_idea(store)
    s, _ = session(store, ["refine", "summary", "Track spending.", ""])
    review.run(s, [idea])
    saved = on_disk(store, idea)
    assert saved.body.strip() == "Track spending." and saved.reviewed == TODAY


def test_empty_note_shows_the_menu_again(store):
    idea = old_idea(store)
    s, p = session(store, ["note", "", "note", "Try the bank API"])
    review.run(s, [idea])
    assert selects(p) == 2
    saved = on_disk(store, idea)
    assert "- 2026-03-01: Try the bank API" in saved.body
    assert saved.reviewed == TODAY


def test_set_excitement(store):
    idea = old_idea(store)
    s, p = session(store, ["excitement", None, "excitement", 4])
    review.run(s, [idea])
    assert selects(p) == 2  # skipping the scale changes nothing
    assert on_disk(store, idea).excitement == 4


def test_shelve_sets_reason_and_status(store):
    idea = old_idea(store)
    s, p = session(store, ["shelve", "No time this year"])
    review.run(s, [idea])
    assert p.calls[1][1] == "Why are you shelving it?"
    saved = on_disk(store, idea)
    assert saved.status == Status.SHELVED
    assert saved.shelved_reason == "No time this year"
    assert "## Retro" in saved.body


def test_quit_leaves_the_rest_unmarked(store):
    first = old_idea(store, "First idea")
    second = old_idea(store, "Second idea")
    s, _ = session(store, ["skip", "quit"])
    result = review.run(s, [first, second])
    assert (result.handled, result.remaining) == (1, 1)
    assert on_disk(store, first).reviewed == TODAY
    assert on_disk(store, second).reviewed is None


def test_ctrl_c_stops_like_quit(store):
    first = old_idea(store, "First idea")
    second = old_idea(store, "Second idea")
    s, _ = session(store, ["note", "Keep this", KeyboardInterrupt()])
    result = review.run(s, [first, second])
    assert (result.handled, result.remaining, result.stopped) == (1, 1, True)
    assert "Keep this" in on_disk(store, first).body
    assert on_disk(store, second).reviewed is None
