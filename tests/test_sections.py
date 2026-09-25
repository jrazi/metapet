from metapet import schema, sections
from metapet.sections import Body, Section

# What the old sketch and spec templates wrote into a body.
OLD_TEMPLATES = """One-liner.

## Problem
<!-- What's annoying, missing, or fun here? Who has this problem? -->

## Rough solution
<!-- The shape of the thing, in a few sentences. -->

## Why me / why now
<!-- What makes this worth your time right now? -->

## Features
-

## MVP scope
<!-- The smallest version you'd actually use. -->
"""


def upsert(body, heading, content):
    field = schema.builtin().field(heading)
    order = schema.builtin().section_order
    sections.upsert(body, field.label, content, field.matches_heading, order)


def test_parse_and_render_round_trip():
    text = "Intro line.\n\n## Problem\nIt hurts.\n\n### Detail\nkept\n\n## Empty\n"
    body = sections.parse(text)
    assert body.preamble == "Intro line."
    assert [s.heading for s in body.sections] == ["Problem", "Empty"]
    assert body.sections[0].content == "It hurts.\n\n### Detail\nkept"
    assert sections.render(body) == text


def test_render_normalises_blank_lines_only():
    body = sections.parse("\n\nIntro\n## A\n\n\ntext\n\n\n\n## B\nmore\n")
    assert sections.render(body) == "Intro\n\n## A\ntext\n\n## B\nmore\n"
    assert sections.render(Body("", [])) == ""


def test_setting_the_preamble_keeps_sections():
    body = sections.parse("old\n\n## Problem\nx\n")
    body.preamble = "new"
    assert sections.render(body) == "new\n\n## Problem\nx\n"


def test_upsert_replaces_only_the_matching_section():
    body = sections.parse("## Problem\nold\n\n## Rough solution\nkeep\n")
    upsert(body, "problem", "new")
    assert sections.render(body) == "## Problem\nnew\n\n## Rough solution\nkeep\n"


def test_upsert_inserts_in_schema_order_and_keeps_own_headings():
    body = sections.parse("intro\n\n## Problem\np\n\n## My thoughts\nmine\n\n## Features\n- f\n")
    upsert(body, "solution", "s")
    upsert(body, "notes", "- n")
    upsert(body, "audience", "a")
    assert [s.heading for s in body.sections] == [
        "Problem",
        "My thoughts",
        "Who it's for",
        "Rough solution",
        "Features",
        "Notes",
    ]


def test_upsert_matches_aliases_and_keeps_the_heading_as_written():
    body = sections.parse("## Why me / why now\nold\n")
    upsert(body, "why_now", "new")
    assert body.sections == [Section("Why me / why now", "new")]


def test_is_empty():
    assert sections.is_empty("")
    assert sections.is_empty("<!-- a\nhint -->\n")
    assert sections.is_empty("- \n* \n1.\n")
    assert not sections.is_empty("<!-- hint -->\ntext")
    assert not sections.is_empty("- item")


def test_items_and_render_items():
    text = "<!-- hint -->\n- one\n* two\n3. three\nplain line\n- \n"
    assert sections.items(text) == ["one", "two", "three", "plain line"]
    assert sections.render_items(["a", "b\nc"]) == "- a\n- b c"


def test_append_item():
    assert sections.append_item("", "x") == "- x"
    assert sections.append_item("<!-- hint -->", "x") == "- x"
    assert sections.append_item("- a", "b") == "- a\n- b"


def test_old_template_placeholders_read_as_empty():
    from metapet import fields
    from metapet.model import Idea

    idea = Idea(id="x", title="X", body=OLD_TEMPLATES)
    built_in = schema.builtin()
    for key in ("problem", "solution", "why_now", "features", "mvp"):
        assert not fields.is_filled(idea, built_in.field(key)), key
    assert fields.get(idea, built_in.field("summary")) == "One-liner."


def test_extend_items_keeps_the_text_as_written():
    text = "- search\n  - fuzzy\n1. export\n\nA paragraph."
    assert sections.extend_items(text, ["new one"]) == text + "\n- new one"
    assert sections.extend_items("<!-- What? -->", ["a", "b"]) == "- a\n- b"
