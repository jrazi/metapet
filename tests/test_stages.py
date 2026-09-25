from metapet import schema, stages
from metapet.model import Idea, Status
from metapet.schema import Field

S = schema.builtin()


def labels(found: list[Field]) -> list[str]:
    return [f.label for f in found]


def test_promote_adds_placeholders_without_clobbering():
    idea = Idea(id="x", title="X", body="My one-liner.\n\n## Problem\nAlready written.")
    stages.move(idea, Status.SKETCH, S)
    assert idea.body.startswith("My one-liner.")
    assert idea.body.count("## Problem") == 1
    assert "Already written." in idea.body
    assert "## Rough solution\n<!-- How could it work, roughly? -->" in idea.body
    assert idea.status == Status.SKETCH and idea.updated is not None


def test_old_alias_heading_is_not_added_twice():
    idea = Idea(id="x", title="X", body="## Why me / why now\nnow")
    stages.move(idea, Status.SKETCH, S)
    assert "## Why now" not in idea.body


def test_skipping_stages_adds_each_stage():
    idea = Idea(id="x", title="X", body="seed")
    stages.move(idea, Status.SPEC, S)
    assert "## Problem" in idea.body and "## MVP scope" in idea.body
    assert "## Effort" not in idea.body  # frontmatter fields get no section


def test_moving_back_adds_nothing():
    idea = Idea(id="x", title="X", status=Status.SPEC, body="kept")
    stages.move(idea, Status.SEED, S)
    assert idea.body == "kept" and idea.status == Status.SEED


def test_promote_from_shelved_clears_the_reason():
    idea = Idea(id="x", title="X", status=Status.SHELVED, shelved_reason="later")
    stages.promote(idea, Status.SKETCH, S)
    assert idea.shelved_reason is None and idea.status == Status.SKETCH
    assert "## Problem" not in idea.body


def test_before():
    assert stages.before(Status.SPEC) == Status.SKETCH
    assert stages.before(Status.SEED) is None
    assert stages.before(Status.SHELVED) is None


def test_gaps():
    idea = Idea(id="x", title="X", body="seed")
    assert stages.gaps(idea, S, None) == []
    assert stages.gaps(idea, S, Status.SEED) == []
    stages.move(idea, Status.SPEC, S)
    assert labels(stages.gaps(idea, S, Status.SKETCH)) == ["Problem", "Rough solution"]
    assert labels(stages.gaps(idea, S, Status.SPEC)) == [
        "Problem",
        "Rough solution",
        "Features",
        "MVP scope",
    ]
    idea.body = idea.body.replace("<!-- What problem does it solve? -->", "It hurts.")
    assert labels(stages.gaps(idea, S, Status.SKETCH)) == ["Rough solution"]


def test_gaps_with_old_placeholders():
    idea = Idea(
        id="x",
        title="X",
        body="## Problem\n<!-- old hint -->\n\n## Rough solution\nWritten.\n\n## Features\n- \n",
    )
    assert labels(stages.gaps(idea, S, Status.SPEC)) == ["Problem", "Features", "MVP scope"]


def test_user_stages_file_changes_what_move_adds(home):
    home.path.mkdir(parents=True)
    home.stages_file.write_text(
        '[sketch]\n[[sketch.fields]]\nkey = "vibe"\nlabel = "Vibe"\nquestion = "How?"\n',
        encoding="utf-8",
    )
    idea = Idea(id="x", title="X", body="seed")
    stages.move(idea, Status.SKETCH, schema.load(home))
    assert "## Vibe\n<!-- How? -->" in idea.body and "## Problem" not in idea.body


def test_describe():
    described = stages.describe(S)
    assert [status for status, _, _ in described][-1] == Status.SHELVED
    assert described[1][1] == "thought through for a few minutes"
    assert [f.key for f in described[1][2]][:2] == ["problem", "audience"]
