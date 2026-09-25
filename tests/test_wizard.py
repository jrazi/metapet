import datetime as dt

import pytest

from metapet import fields, schema, stages, wizard
from metapet.model import Idea, Status
from metapet.prompter import ScriptedPrompter

S = schema.builtin()
TODAY = dt.date(2026, 1, 2)
SPEC_QUESTIONS = 7  # features, mvp, stack, risks, prior_art, effort, impact


def session(store, answers):
    prompter = ScriptedPrompter(answers)
    s = wizard.Session(S, prompter, store.save, store.all_tags(), today=TODAY)
    return s, prompter


def on_disk(store, idea) -> Idea:
    return Idea.load(store.home.ideas / f"{idea.id}.md")


def asked(prompter) -> list[str]:
    return [question for _, question, _ in prompter.calls]


def sketch_idea(store, **fields_) -> Idea:
    idea = store.create("Budget tracker")
    stages.move(idea, Status.SKETCH, S)
    for key, value in fields_.items():
        fields.put(idea, S.field(key), value, S.section_order)
    store.save(idea)
    return idea


def test_new_idea_asks_only_missing_seed_fields(store):
    idea = store.create("Budget tracker", tags=["money"])
    s, p = session(store, ["Track spending.", 4])
    wizard.new_idea(s, idea, {"title", "tags"})
    assert asked(p) == ["Describe it in one sentence.", "How excited are you about it?"]
    saved = on_disk(store, idea)
    assert saved.excitement == 4 and saved.body.strip() == "Track spending."
    assert p.cards[0].title == "Budget tracker"
    assert "pet set budget-tracker KEY=" in p.messages[0]


def test_answers_are_saved_before_ctrl_c(store):
    idea = store.create("Budget tracker")
    s, _ = session(store, ["Track spending.", KeyboardInterrupt()])
    with pytest.raises(KeyboardInterrupt):
        wizard.new_idea(s, idea, {"title"})
    assert on_disk(store, idea).body.strip() == "Track spending."


def test_skipped_fields_stay_empty(store):
    idea = store.create("Budget tracker")
    s, _ = session(store, [None, None, None])
    wizard.new_idea(s, idea, {"title"})
    saved = on_disk(store, idea)
    assert saved.excitement is None and saved.tags == [] and saved.body.strip() == ""
    assert saved.updated is None


def test_continuation_promotes_to_sketch_and_asks_its_questions(store):
    idea = store.create("Budget tracker")
    s, p = session(store, [True, "Money leaks.", None, "A small CLI.", None, None, False])
    wizard.continue_stages(s, idea)
    assert asked(p)[0] == "Promote to sketch and answer its questions now?"
    assert asked(p)[-1] == "Promote to spec and answer its questions now?"
    saved = on_disk(store, idea)
    assert saved.status == Status.SKETCH
    assert "## Problem\nMoney leaks." in saved.body
    assert "## Rough solution\nA small CLI." in saved.body


def test_continuation_warns_instead_of_asking_about_gaps(store):
    idea = sketch_idea(store)
    s, p = session(store, [True, *[None] * SPEC_QUESTIONS, False])
    wizard.continue_stages(s, idea)
    assert "Warning: still empty: Problem (sketch), Rough solution (sketch)" in p.messages
    assert on_disk(store, idea).status == Status.SPEC


def test_promote_with_gaps_can_be_cancelled(store):
    idea = sketch_idea(store)
    s, p = session(store, ["cancel"])
    assert wizard.promote(s, idea, Status.SPEC) is False
    assert "Still empty: Problem (sketch), Rough solution (sketch)" in p.messages
    method, _, kwargs = p.calls[0]
    assert method == "select"
    assert [label for _, label in kwargs["options"]] == [
        "Fill them now",
        "Promote anyway",
        "Cancel",
    ]
    assert on_disk(store, idea).status == Status.SKETCH


def test_promote_anyway_leaves_gaps_empty(store):
    idea = sketch_idea(store)
    s, p = session(store, ["anyway", *[None] * SPEC_QUESTIONS])
    assert wizard.promote(s, idea, Status.SPEC) is True
    saved = on_disk(store, idea)
    assert saved.status == Status.SPEC
    assert [f.key for f in stages.gaps(saved, S, Status.SKETCH)] == ["problem", "solution"]


def test_promote_can_fill_gaps_first(store):
    idea = sketch_idea(store)
    s, p = session(store, ["fill", "Money leaks.", "A small CLI.", *[None] * SPEC_QUESTIONS])
    assert wizard.promote(s, idea, Status.SPEC) is True
    saved = on_disk(store, idea)
    assert saved.status == Status.SPEC
    assert stages.gaps(saved, S, Status.SKETCH) == []
    assert asked(p)[1:3] == ["What problem does it solve?", "How could it work, roughly?"]


def test_promote_prefills_current_values(store):
    idea = sketch_idea(store, problem="P", solution="S", mvp="Just a script", effort="M")
    s, p = session(store, [None] * SPEC_QUESTIONS)
    wizard.promote(s, idea, Status.SPEC)
    by_question = {question: kwargs for _, question, kwargs in p.calls}
    assert by_question["What is the smallest version you would actually use?"]["current"] == (
        "Just a script"
    )
    assert by_question["How big is it?"]["default"] == "M"
    assert by_question["What should it do?"]["current"] == []
    assert "## MVP scope\nJust a script" in on_disk(store, idea).body


def test_promote_backwards_asks_nothing(store):
    idea = sketch_idea(store)
    s, p = session(store, [])
    assert wizard.promote(s, idea, Status.SEED) is True
    assert p.calls == [] and on_disk(store, idea).status == Status.SEED


def test_dated_list_items_get_todays_date(store):
    idea = store.create("Budget tracker")
    fields.put(idea, S.field("notes"), ["old note"], S.section_order)
    store.save(idea)
    s, _ = session(store, [["old note", "new note"]])
    wizard.refine(s, idea, S.field("notes"))
    assert "## Notes\n- old note\n- 2026-01-02: new note" in on_disk(store, idea).body


def test_refine_picker_markers_follow_answers(store):
    idea = store.create("Budget tracker")
    s, p = session(store, ["summary", "Track spending.", ""])
    wizard.refine(s, idea, None)
    first, second = (kwargs["options"] for method, _, kwargs in p.calls if method == "select")
    assert ("summary", "[ ] Summary  (seed)") in first
    assert ("summary", "[x] Summary  (seed)") in second
    assert ("title", "[x] Title  (seed)") in first
    assert ("notes", "[ ] Notes  (any stage)") in first
    assert first[-1] == ("", "Done")
    assert "problem" not in {value for value, _ in first}  # later stage
    assert on_disk(store, idea).body.strip() == "Track spending."


def test_refine_one_field(store):
    idea = sketch_idea(store, problem="Old problem")
    s, p = session(store, ["New problem"])
    wizard.refine(s, idea, S.field("problem"))
    assert p.calls[0][2]["current"] == "Old problem"
    assert "## Problem\nNew problem" in on_disk(store, idea).body


def test_ask_title_repeats_until_given(store):
    s, p = session(store, ["", "  ", "Budget tracker"])
    assert wizard.ask_title(s) == "Budget tracker"
    assert p.messages == ["A title is needed.", "A title is needed."]
