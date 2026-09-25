from metapet import schema, views
from metapet.model import Effort, Idea, Status

S = schema.builtin()


def test_card_shows_filled_fields_in_schema_order():
    idea = Idea(
        id="x",
        title="Budget tracker",
        status=Status.SKETCH,
        tags=["money"],
        excitement=4,
        effort=Effort.S,
        body="Track stuff.\n\n## Rough solution\nA script.\n\n## Problem\n<!-- hint -->\n",
    )
    card = views.card(idea, S)
    assert (card.title, card.stage, card.summary) == ("Budget tracker", "sketch", "Track stuff.")
    assert card.answers == [
        ("Tags", "money"),
        ("Excitement", "4"),
        ("Rough solution", "A script."),
        ("Effort", "S"),
    ]


def test_card_without_summary():
    assert views.card(Idea(id="x", title="X", body="## Problem\np"), S).summary is None


def test_preview_markdown():
    idea = Idea(id="x", title="X", tags=["a"], excitement=3, impact=5, body="Body.")
    assert (
        views.preview_markdown(idea, S)
        == "# X\n\nx · seed · tags: a · excitement 3/5 · impact 5/5\n\nBody.\n"
    )


def test_preview_markdown_lists_empty_sections():
    idea = Idea(id="x", title="X", body="## Problem\n<!-- q -->\n\n## Value\nMoney.\n")
    assert views.preview_markdown(idea, S) == (
        "# X\n\nx · seed\n\n## Value\nMoney.\n\n*Empty: Problem\\**\n"
    )


def test_visible_body_hides_empty_sections():
    idea = Idea(
        id="x",
        title="X",
        body="Summary.\n\n## Problem\n<!-- What problem? -->\n\n## Who it's for\nMe.\n\n"
        "## Features\n- \n\n## Mine\n\n## Value\n",
    )
    body, empty = views.visible_body(idea, S)
    assert body == "Summary.\n\n## Who it's for\nMe.\n"
    assert empty == ["Problem*", "Features*", "Mine", "Value"]


def test_filter_ideas():
    ideas = [
        Idea(id="bot", title="Telegram bot", tags=["cli"], body="music"),
        Idea(id="game", title="Telegram game", status=Status.SPEC, tags=["fun"]),
        Idea(id="old", title="Old thing", status=Status.SHELVED, tags=["cli"]),
    ]

    def ids(query):
        return [i.id for i in views.filter_ideas(ideas, query)]

    assert ids("") == ["bot", "game"]
    assert ids("telegram") == ["bot", "game"]
    assert ids("TELEGRAM music") == ["bot"]
    assert ids("tag:cli") == ["bot"]
    assert ids("tag:cli tag:fun") == ["bot", "game"]
    assert ids("status:shelved") == ["old"]
    assert ids("status:seed status:shelved tag:cli") == ["bot", "old"]


def test_filter_ignores_comments():
    ideas = [Idea(id="x", title="X", body="## Problem\n<!-- What problem does it solve? -->\n")]
    assert views.filter_ideas(ideas, "what problem") == []
    assert views.filter_ideas(ideas, "problem") == ideas  # the heading is text


def test_parse_query_unknown_status():
    q = views.parse_query("status:bogus status:seed tag:CLI word")
    assert q.unknown_statuses == ["bogus"]
    assert q.statuses == {"bogus", "seed"} and q.tags == {"cli"} and q.words == ["word"]


def test_visible_body_uses_labels_and_lists_missing_sections():
    idea = Idea(
        id="x",
        title="X",
        status=Status.SKETCH,
        body="## problem\nToo slow.\n\n## solution\nCache.\n",
    )
    body, empty = views.visible_body(idea, S)
    assert "## Problem\nToo slow." in body and "## Rough solution\nCache." in body
    assert empty == ["Who it's for", "Value", "Why now"]


def test_visible_body_keeps_line_breaks():
    idea = Idea(
        id="x", title="X", body="## Problem\nline one\nline two\n\n```\ncode a\ncode b\n```\n"
    )
    body, _ = views.visible_body(idea, S)
    assert "line one  \nline two" in body
    assert "code a\ncode b" in body
