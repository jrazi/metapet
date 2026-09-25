from metapet import stages
from metapet.model import Idea, Status


def test_promote_appends_without_clobbering():
    idea = Idea(id="x", title="X", body="My one-liner.\n\n## Problem\nAlready written.")
    stages.move(idea, Status.SKETCH)
    assert idea.body.startswith("My one-liner.")
    assert idea.body.count("## Problem") == 1
    assert "Already written." in idea.body
    assert "## Rough solution" in idea.body
    assert idea.status == Status.SKETCH and idea.updated is not None


def test_skipping_stages_adds_each_template():
    idea = Idea(id="x", title="X", body="seed")
    stages.move(idea, Status.SPEC)
    assert "## Problem" in idea.body and "## MVP scope" in idea.body


def test_moving_back_adds_nothing():
    idea = Idea(id="x", title="X", status=Status.SPEC, body="kept")
    stages.move(idea, Status.SEED)
    assert idea.body == "kept" and idea.status == Status.SEED


def test_user_template_override(home):
    home.templates.mkdir(parents=True)
    (home.templates / "sketch.md").write_text("## Vibe\nhow it feels\n")
    idea = Idea(id="x", title="X", body="seed")
    stages.move(idea, Status.SKETCH, home)
    assert "## Vibe" in idea.body and "## Problem" not in idea.body
