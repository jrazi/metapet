import pytest

from metapet import schema
from metapet.model import Status
from metapet.schema import Kind, SchemaError, Storage


def write_stages(home, text):
    home.path.mkdir(parents=True, exist_ok=True)
    home.stages_file.write_text(text, encoding="utf-8")


def test_builtin_has_every_stage_and_seed_fields_in_order():
    built_in = schema.builtin()
    assert set(built_in.stages) == {s.value for s in Status} | {"any"}
    assert [f.key for f in built_in.stage("seed").fields] == [
        "title",
        "summary",
        "tags",
        "excitement",
    ]
    problem = built_in.field("problem")
    assert (problem.kind, problem.storage, problem.required) == (Kind.LONG, Storage.SECTION, True)
    assert built_in.field("effort").choices == ("S", "M", "L", "XL")


def test_load_without_user_file_is_builtin(home):
    assert schema.load(home) is schema.builtin()
    assert schema.load(None) is schema.builtin()


def test_user_file_replaces_one_stage_and_keeps_the_others(home):
    write_stages(
        home,
        '[sketch]\nmeaning = "mine"\n\n[[sketch.fields]]\n'
        'key = "vibe"\nlabel = "Vibe"\nquestion = "How does it feel?"\n',
    )
    loaded = schema.load(home)
    assert loaded.stage("sketch").meaning == "mine"
    assert [f.key for f in loaded.stage("sketch").fields] == ["vibe"]
    assert loaded.stage("spec") == schema.builtin().stage("spec")


def test_missing_meaning_falls_back_and_no_fields_means_none(home):
    write_stages(home, "[sketch]\n")
    sketch = schema.load(home).stage("sketch")
    assert sketch.meaning == schema.builtin().stage("sketch").meaning
    assert sketch.fields == ()


FIELD = '[[sketch.fields]]\nkey = "vibe"\nlabel = "Vibe"\nquestion = "Q?"\n'


@pytest.mark.parametrize(
    "text, message",
    [
        ("[nope]\n", "unknown stage"),
        (FIELD + "colour = 1\n", "unknown option"),
        ('[[sketch.fields]]\nkey = "vibe"\nlabel = "Vibe"\n', "'question' is required"),
        ('[[sketch.fields]]\nlabel = "Vibe"\nquestion = "Q?"\n', "'key' is required"),
        ('[[sketch.fields]]\nkey = "vibe"\nquestion = "Q?"\n', "'label' is required"),
        (FIELD.replace('"vibe"', '"Bad-Key"'), "lowercase letters"),
        (FIELD + 'kind = "blob"\n', "kind must be one of"),
        (FIELD + 'store = "cloud"\n', "store must be one of"),
        (FIELD + 'kind = "choice"\n', "needs a 'choices' list"),
        (FIELD + 'choices = ["a"]\n', "only works with kind 'choice'"),
        (FIELD + "dated = true\n", "'dated' only works"),
        (FIELD + FIELD, "defined more than once"),
        (
            FIELD + 'store = "summary"\n' + FIELD.replace("vibe", "other") + 'store = "summary"\n',
            "only one field",
        ),
        ("[sketch\n", "invalid TOML"),
        (FIELD.replace('"vibe"', '"status"'), "managed by metapet"),
        (FIELD.replace('"vibe"', '"reviewed"'), "managed by metapet"),
        (FIELD.replace('"vibe"', '"impact"') + 'store = "frontmatter"\n', "kind 'scale'"),
        (
            FIELD.replace('"vibe"', '"effort"')
            + 'store = "frontmatter"\nkind = "choice"\nchoices = ["small", "big"]\n',
            "effort choices",
        ),
    ],
)
def test_invalid_user_files_name_the_file(home, text, message):
    write_stages(home, text)
    with pytest.raises(SchemaError, match=message) as exc:
        schema.load(home)
    assert str(home.stages_file) in str(exc.value)


def test_summary_field_counts_across_stages(home):
    write_stages(
        home,
        '[seed]\n[[seed.fields]]\nkey = "title"\nlabel = "Title"\nquestion = "Q?"\n'
        'store = "frontmatter"\n\n'
        '[any]\n[[any.fields]]\nkey = "pitch"\nlabel = "Pitch"\nquestion = "Q?"\n'
        'store = "summary"\n',
    )
    # the built-in seed summary is gone, so one summary field is fine
    assert schema.load(home).field("pitch").storage == Storage.SUMMARY
    write_stages(home, '[any]\n[[any.fields]]\nkey = "pitch"\nlabel = "P"\nquestion = "Q?"\n')
    home.stages_file.write_text(
        home.stages_file.read_text() + 'store = "summary"\n', encoding="utf-8"
    )
    with pytest.raises(SchemaError, match="only one field"):
        schema.load(home)


def test_field_lookup_by_key_hyphen_and_label():
    built_in = schema.builtin()
    assert built_in.field("why_now").key == "why_now"
    assert built_in.field("why-now").key == "why_now"
    assert built_in.field("rough  SOLUTION").key == "solution"
    assert built_in.field("retro").stage == "shipped"
    with pytest.raises(KeyError):
        built_in.field("Rough solution", labels=False)
    with pytest.raises(KeyError):
        built_in.field("nothing")


def test_fields_upto():
    built_in = schema.builtin()
    sketch = [f.key for f in built_in.fields_upto(Status.SKETCH)]
    assert sketch[:5] == ["title", "summary", "tags", "excitement", "problem"]
    assert sketch[-3:] == ["notes", "links", "related"]
    assert "features" not in sketch
    shelved = [f.key for f in built_in.fields_upto(Status.SHELVED)]
    assert "repo" in shelved and shelved.count("retro") == 1


def test_matches_heading_uses_label_and_aliases():
    why_now = schema.builtin().field("why_now")
    assert why_now.matches_heading("Why now")
    assert why_now.matches_heading("why me /  why now")
    assert not why_now.matches_heading("Why")


def test_duplicate_key_across_stages_rejected(home):
    write_stages(
        home,
        '[sketch]\n[[sketch.fields]]\nkey = "notes"\nlabel = "Scribbles"\nquestion = "Q?"\n',
    )
    with pytest.raises(
        SchemaError, match=r"field 'notes' is defined in both \[sketch\] and \[any\]"
    ):
        schema.load(home)


def test_same_field_in_two_stages_is_allowed():
    built_in = schema.builtin()
    assert built_in.stage("shipped").fields[0] == schema.builtin().field("retro")
    assert [f.key for f in built_in.stage("shelved").fields] == ["retro"]


def test_duplicate_heading_rejected(home):
    write_stages(
        home,
        '[sketch]\n[[sketch.fields]]\nkey = "notes_two"\nlabel = "Problem"\nquestion = "Q?"\n'
        '[[sketch.fields]]\nkey = "problem"\nlabel = "Problem"\nquestion = "Q?"\n',
    )
    with pytest.raises(SchemaError) as exc:
        schema.load(home)
    message = str(exc.value)
    assert "[sketch] 'notes_two' and [sketch] 'problem' both use the heading 'Problem'" in message
    assert message.count(str(home.stages_file)) == 1


def test_key_matches_heading():
    solution = schema.builtin().field("solution")
    assert solution.matches_heading("solution")
    assert schema.builtin().field("why_now").matches_heading("why now")
