import datetime as dt

import pytest

from metapet.model import Effort, Idea, IdeaError, Status
from metapet.store import IdeaLookupError, slugify


def test_slugify():
    assert slugify("Spotify downloader bot for Telegram!") == "spotify-downloader-bot-for-telegram"
    assert slugify("Café ☕ app") == "cafe-app"
    assert slugify("!!!") == "idea"


def test_slug_collisions_get_suffixes(store):
    ids = [store.create("Same idea").id for _ in range(3)]
    assert ids == ["same-idea", "same-idea-2", "same-idea-3"]


def test_round_trip_preserves_fields_and_unknown_keys(store):
    idea = store.create(
        "Round trip",
        tags=["a", "b"],
        excitement=4,
        effort=Effort.L,
        body="Some *body*.",
    )
    text = idea.path.read_text()
    text = text.replace("---\n", "---\ncustom: kept\n", 1)
    idea.path.write_text(text)

    loaded = Idea.load(idea.path)
    assert (loaded.title, loaded.status, loaded.tags) == ("Round trip", Status.SEED, ["a", "b"])
    assert (loaded.excitement, loaded.effort) == (4, Effort.L)
    assert loaded.created == dt.date.today()
    assert loaded.body.strip() == "Some *body*."
    assert loaded.extra == {"custom": "kept"}
    store.save(loaded)
    assert "custom: kept" in idea.path.read_text()


def test_frontmatter_key_order_is_stable(store):
    idea = store.create("Ordered", tags=["x"], excitement=2)
    keys = [
        line.split(":")[0] for line in idea.path.read_text().split("---")[1].strip().splitlines()
    ]
    assert keys[:4] == ["id", "title", "status", "created"]


@pytest.mark.parametrize(
    "text, message",
    [
        ("---\ntitle: x\n---\n", "missing required"),
        ("---\nid: x\ntitle: x\nstatus: nope\ncreated: 2026-01-01\n---\n", "nope"),
        ("---\nid: x\ntitle: x\nstatus: seed\ncreated: 2026-01-01\nexcitement: 9\n---\n", "1-5"),
        ("---\nid: [unclosed\n---\n", "unreadable"),
    ],
)
def test_invalid_files_raise(text, message):
    with pytest.raises(IdeaError, match=message):
        Idea.from_markdown(text)


def test_scan_reports_broken_files(store):
    store.create("Good")
    (store.home.ideas / "bad.md").write_text("---\ntitle: only\n---\n")
    ideas, broken = store.scan()
    assert [i.id for i in ideas] == ["good"]
    assert [b.path.name for b in broken] == ["bad.md"]


def test_find_tiers_and_ambiguity(store):
    store.create("Telegram bot")
    store.create("Telegram bot for music")
    store.create("Budget tracker")
    assert store.find("telegram-bot").id == "telegram-bot"  # exact beats prefix
    assert store.find("budget").id == "budget-tracker"  # prefix
    assert store.find("tracker").id == "budget-tracker"  # substring
    with pytest.raises(IdeaLookupError) as exc:
        store.find("telegram")
    assert len(exc.value.candidates) == 2
    with pytest.raises(IdeaLookupError):
        store.find("nothing-like-this")


def test_status_next():
    assert Status.SEED.next() == Status.SKETCH
    assert Status.BUILDING.next() == Status.SHIPPED
    assert Status.SHELVED.next() is None


def test_impact_and_reviewed_round_trip(store):
    idea = store.create("Scored", excitement=2, impact=4)
    idea.mark_reviewed(dt.date(2026, 1, 2))
    store.save(idea)
    loaded = Idea.load(idea.path)
    assert (loaded.impact, loaded.reviewed, loaded.updated) == (4, dt.date(2026, 1, 2), None)
    keys = [
        line.split(":")[0] for line in idea.path.read_text().split("---")[1].strip().splitlines()
    ]
    assert keys == ["id", "title", "status", "created", "reviewed", "excitement", "impact"]


def test_impact_out_of_range_is_rejected():
    text = "---\nid: x\ntitle: x\nstatus: seed\ncreated: 2026-01-01\nimpact: 9\n---\n"
    with pytest.raises(IdeaError, match="impact must be 1-5, got 9"):
        Idea.from_markdown(text)
