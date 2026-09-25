import io

import pytest
from prompt_toolkit.document import Document
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.output import DummyOutput
from rich.console import Console

from metapet.prompter import PartialAnswer, ScriptedPrompter
from metapet.questionary_prompter import QuestionaryPrompter, TagCompleter, resolve_long
from metapet.views import Card

DOWN = "j"  # questionary select also moves down with j
ENTER = "\r"
CTRL_C = "\x03"


def test_scripted_prompter_pops_answers_and_records_calls():
    p = ScriptedPrompter(["hello", 3])
    p.card(Card("T", "seed", None, []))
    p.message("hi")
    assert p.text("Name?", hint="h") == "hello"
    assert p.scale("How much?", default=2) == 3
    assert p.calls == [
        ("text", "Name?", {"hint": "h", "default": ""}),
        ("scale", "How much?", {"hint": None, "default": 2}),
    ]
    assert p.messages == ["hi"] and p.cards[0].title == "T"


def test_scripted_prompter_raises_exceptions_and_unexpected_questions():
    p = ScriptedPrompter([KeyboardInterrupt()])
    with pytest.raises(KeyboardInterrupt):
        p.confirm("Go on?")
    with pytest.raises(AssertionError, match="unexpected question: Again?"):
        p.confirm("Again?")


def test_resolve_long():
    def editor(result):
        return lambda text=None, **kwargs: result

    assert resolve_long("", "current") is None
    assert resolve_long("  new text ", "current") == "new text"
    assert resolve_long("E", "old", edit=editor("written\n\nin the editor\n")) == (
        "written\n\nin the editor"
    )
    assert resolve_long("e", "old", edit=editor(None)) is None
    assert resolve_long("e", "old", edit=editor("old\n")) is None
    assert resolve_long("e", "", edit=editor("  ")) is None


def ask(keys: str, method: str, *args, **kwargs):
    with create_pipe_input() as pipe:
        pipe.send_text(keys)
        prompter = QuestionaryPrompter(
            Console(file=io.StringIO()), input=pipe, output=DummyOutput()
        )
        return getattr(prompter, method)(*args, **kwargs)


def test_text():
    assert ask("  a budget app " + ENTER, "text", "Title?") == "a budget app"
    assert ask(ENTER, "text", "Title?") is None
    assert ask(ENTER, "text", "Title?", default="kept") == "kept"


def test_scale():
    assert ask(DOWN + DOWN + ENTER, "scale", "How much?") == 2
    assert ask(ENTER, "scale", "How much?") is None
    assert ask(ENTER, "scale", "How much?", default=4) == 4


def test_tags():
    assert ask("cli, web ,, " + ENTER, "tags", "Tags?", current=[], known=[]) == ["cli", "web"]
    assert ask(ENTER, "tags", "Tags?", current=["a", "b"], known=[]) == ["a", "b"]
    assert ask(ENTER, "tags", "Tags?", current=[], known=[]) is None


def test_tag_completion_uses_the_part_after_the_last_comma():
    completer = TagCompleter(["cli", "Client", "web"])
    found = [c.text for c in completer.get_completions(Document("web, CL"), None)]
    assert found == ["cli", "Client"]
    found = [c.text for c in completer.get_completions(Document("cli, "), None)]
    assert found == ["Client", "web"]


def test_items_dropping_all_and_adding_none_is_a_skip():
    assert ask("n" + ENTER, "items", "Features?", current=["a", "b"]) is None
    assert ask("y" + "c" + ENTER + ENTER, "items", "Features?", current=["a"]) == ["a", "c"]
    assert ask("n" + "c" + ENTER + ENTER, "items", "Features?", current=["a"]) == ["c"]


def test_items_ctrl_c_keeps_the_items_entered():
    with pytest.raises(PartialAnswer) as exc:
        ask("a" + ENTER + "b" + ENTER + CTRL_C, "items", "Features?", current=[])
    assert exc.value.value == ["a", "b"]
    with pytest.raises(KeyboardInterrupt) as exc:
        ask(CTRL_C, "items", "Features?", current=[])
    assert not isinstance(exc.value, PartialAnswer)
