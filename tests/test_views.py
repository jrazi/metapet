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
        views.preview_markdown(idea)
        == "# X\n\nseed · tags: a · excitement 3/5 · impact 5/5\n\nBody.\n"
    )


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
