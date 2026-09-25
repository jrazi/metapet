import datetime as dt

import pytest

from metapet import fields, schema
from metapet.fields import Change
from metapet.model import Effort, Idea

S = schema.builtin()


def field(key):
    return S.field(key)


@pytest.mark.parametrize(
    "key, raw, expected",
    [
        ("problem", "  it hurts  ", "it hurts"),
        ("problem", "   ", None),
        ("excitement", "4", 4),
        ("excitement", "", None),
        ("effort", "xl", "XL"),
        ("tags", "a, b,,c ", ["a", "b", "c"]),
        ("related", "x,y", ["x", "y"]),
        ("features", ["one", " ", "two\nlines"], ["one", "two lines"]),
        ("features", "single", ["single"]),
    ],
)
def test_parse(key, raw, expected):
    assert fields.parse(field(key), raw) == expected


@pytest.mark.parametrize(
    "key, raw, message",
    [
        ("excitement", "9", "excitement must be a number from 1 to 5"),
        ("excitement", "high", "excitement must be a number from 1 to 5"),
        ("effort", "huge", "effort must be one of S, M, L, XL"),
    ],
)
def test_parse_errors(key, raw, message):
    with pytest.raises(ValueError, match=message):
        fields.parse(field(key), raw)


def test_get_and_put_attributes_and_extra():
    idea = Idea(id="x", title="X")
    fields.put(idea, field("effort"), "L", S.section_order)
    fields.put(idea, field("impact"), 5, S.section_order)
    assert idea.effort == Effort.L and fields.get(idea, field("effort")) == "L"
    assert fields.get(idea, field("impact")) == 5
    with pytest.raises(ValueError):
        fields.put(idea, field("impact"), 7, S.section_order)

    custom = schema.Field("mood", "Mood", "Q?", "any", storage=schema.Storage.FRONTMATTER)
    fields.put(idea, custom, "calm", S.section_order)
    assert idea.extra == {"mood": "calm"} and fields.is_filled(idea, custom)
    fields.put(idea, custom, None, S.section_order)
    assert idea.extra == {} and not fields.is_filled(idea, custom)


def test_get_and_put_summary_and_sections():
    idea = Idea(id="x", title="X", body="Old line.\n\n## Mine\nkeep\n")
    fields.put(idea, field("summary"), "New line.", S.section_order)
    fields.put(idea, field("features"), ["a", "b"], S.section_order)
    fields.put(idea, field("problem"), "It hurts.", S.section_order)
    assert idea.body == (
        "New line.\n\n## Mine\nkeep\n\n## Problem\nIt hurts.\n\n## Features\n- a\n- b\n"
    )
    assert fields.get(idea, field("features")) == ["a", "b"]
    assert fields.get(idea, field("summary")) == "New line."
    fields.put(idea, field("problem"), None, S.section_order)
    assert "## Problem\n\n" in idea.body and not fields.is_filled(idea, field("problem"))


def test_scale_in_a_section_reads_the_first_number():
    rating = schema.Field("fun", "Fun", "Q?", "any", kind=schema.Kind.SCALE)
    idea = Idea(id="x", title="X", body="## Fun\nabout 4 of 5\n")
    assert fields.get(idea, rating) == 4


def test_display_shortens():
    assert fields.display(field("tags"), ["a", "b"]) == "a, b"
    long = fields.display(field("problem"), "x" * 100 + "\nsecond")
    assert len(long) == 60 and long.endswith("…")
    assert fields.display(field("problem"), None) == ""


def test_parse_changes():
    assert fields.parse_changes(["excitement=4", "+cli", "-old", "summary="]) == [
        Change("set", "excitement", "4"),
        Change("add_tag", "tags", "cli"),
        Change("remove_tag", "tags", "old"),
        Change("set", "summary", ""),
    ]
    assert fields.parse_changes(["problem=a=b"])[0].value == "a=b"
    for bad in ("nothing", "=x", "+", "-"):
        with pytest.raises(ValueError, match="expected key=value, \\+tag or -tag"):
            fields.parse_changes([bad])


def apply(idea, *tokens):
    return fields.apply_changes(idea, S, fields.parse_changes(list(tokens)))


def test_apply_changes():
    idea = Idea(id="x", title="X", tags=["Old", "keep"], body="Line.")
    done = apply(idea, "excitement=4", "why-now=soon", "+cli", "+CLI", "-old", "summary=")
    assert done == [
        "excitement: 4",
        "why_now: soon",
        "summary: cleared",
        "tags: +cli",
        "tags: -old",
    ]
    assert idea.excitement == 4 and idea.tags == ["keep", "cli"]
    assert idea.updated == dt.date.today()
    assert fields.get(idea, field("why_now")) == "soon"
    assert fields.get(idea, field("summary")) is None


def test_apply_changes_lists_and_tags():
    idea = Idea(id="x", title="X", tags=["a"])
    apply(idea, "features=one", "features=two", "tags=b,c")
    assert fields.get(idea, field("features")) == ["one", "two"]
    assert idea.tags == ["b", "c"]
    apply(idea, "features=")
    assert fields.get(idea, field("features")) == []


def test_apply_changes_reports_no_change():
    idea = Idea(id="x", title="X", excitement=3)
    assert apply(idea, "excitement=3", "summary=", "-missing") == []
    assert idea.updated is None


def test_apply_changes_reports_every_problem_and_changes_nothing():
    idea = Idea(id="x", title="X", excitement=2)
    before = idea.to_markdown()
    with pytest.raises(ValueError) as exc:
        apply(
            idea,
            "excitement=5",
            "bogus=1",
            "status=spec",
            "created=2020-01-01",
            "title=",
            "effort=huge",
            "stack=a",
            "stack=b",
        )
    message = str(exc.value)
    for part in (
        "unknown field 'bogus'; known fields: title, summary",
        "use pet promote or pet shelve to change the status",
        "'created' cannot be set",
        "title cannot be empty",
        "effort must be one of S, M, L, XL",
        "'stack' given more than once",
    ):
        assert part in message
    assert idea.to_markdown() == before


def test_set_accepts_label():
    idea = Idea(id="x", title="X")
    assert apply(idea, "MVP scope=Daily message", "rough solution=A bot") == [
        "mvp: Daily message",
        "solution: A bot",
    ]
    assert fields.get(idea, field("mvp")) == "Daily message"


def test_add_note():
    idea = Idea(id="x", title="X", body="Line.\n\n## Problem\np\n")
    fields.add_note(idea, S, "first\nsecond", today=dt.date(2026, 1, 2))
    fields.add_note(idea, S, "again", today=dt.date(2026, 1, 3))
    assert idea.body.endswith("## Notes\n- 2026-01-02: first second\n- 2026-01-03: again\n")
    with pytest.raises(ValueError):
        fields.add_note(idea, S, "  ")


def test_set_title_collapses_whitespace():
    idea = Idea(id="x", title="X")
    apply(idea, "title=a   b")
    assert idea.title == "a b"


def test_set_appends_to_dated_list():
    idea = Idea(id="x", title="X")
    fields.add_note(idea, S, "one", today=dt.date(2026, 1, 2))
    done = apply(idea, "notes=two", "notes=three", "log=started")
    today = dt.date.today().isoformat()
    assert fields.get(idea, field("notes")) == [
        "2026-01-02: one",
        f"{today}: two",
        f"{today}: three",
    ]
    assert fields.get(idea, field("log")) == [f"{today}: started"]
    assert done == ["notes: added 2 items", "log: added 1 item"]


def test_set_empty_clears_dated_list():
    idea = Idea(id="x", title="X")
    fields.add_note(idea, S, "one")
    assert apply(idea, "notes=") == ["notes: cleared"]
    assert fields.get(idea, field("notes")) == []


def test_normalize_tags():
    assert fields.normalize_tags(["bot", "bot", "BOT"]) == ["bot"]
    assert fields.normalize_tags(["Bot", "bot", "Telegram", "", " a  b "], ["telegram"]) == [
        "Bot",
        "telegram",
        "a b",
    ]


def test_put_text_demotes_level_two_headings():
    idea = Idea(id="x", title="X", body="## Problem\nold\n\n## Value\nv\n")
    changed = fields.put_text(
        idea, field("problem"), "Score one\n\n## Stretch\nELO", S.section_order
    )
    assert changed is True
    assert "## Problem\nScore one\n\n### Stretch\nELO\n\n## Value\nv" in idea.body
    assert fields.put_text(idea, field("problem"), "plain\n### ok", S.section_order) is False
