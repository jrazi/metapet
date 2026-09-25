"""The terminal version of the Prompter, built on questionary.

Imported only when a command actually asks questions, to keep the other commands fast.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any

import click
import questionary
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.document import Document
from rich.console import Console
from rich.markup import escape
from rich.panel import Panel

from metapet.prompter import PartialAnswer
from metapet.views import Card

SKIP = "Skip"
QMARK_STYLE = "#5f819d"  # the colour questionary uses for the ? before a question
SCALE_KEYS = "(press 1-5 or use the arrows, then Enter)"
LONG_SKIP = "Enter skips; e opens your editor"
LONG_KEEP = "Enter keeps the current answer; e opens your editor"
LONG_SKIP_NO_EDITOR = "Enter skips"
LONG_KEEP_NO_EDITOR = "Enter keeps the current answer"


# Returned by resolve_long when the editor could not be opened: ask the question again.
ASK_AGAIN = object()


def resolve_long(
    raw: str,
    current: str,
    edit: Callable[..., str | None] | None = None,
    notify: Callable[[str], None] = lambda text: None,
) -> Any:
    """Turn the answer to a long question into the new text; None keeps the current text.

    Returns ASK_AGAIN, after telling the user through notify, when the editor fails.
    """
    answer = raw.strip()
    if answer.casefold() == "e":
        try:
            edited = (edit or click.edit)(text=current, extension=".md")
        except click.ClickException as exc:
            notify(
                f"Could not open the editor: {exc.format_message()}. Type the answer here instead."
            )
            return ASK_AGAIN
        if edited is None or not edited.strip() or edited.strip() == current.strip():
            return None
        return edited.strip()
    return answer or None


def _join(hint: str | None, instruction: str) -> str:
    """A field's hint followed by how to answer, for the question line."""
    return f"{hint} {instruction}" if hint else instruction


def _ask(question: questionary.Question) -> Any:
    """Ask, turning Ctrl-D (EOFError) into Ctrl-C so both stop the questions the same way."""
    try:
        return question.unsafe_ask()
    except EOFError:
        raise KeyboardInterrupt from None


class TagCompleter(Completer):
    """Completes the tag after the last comma from the tags already in use."""

    def __init__(self, known: list[str]):
        self.known = known

    def get_completions(self, document: Document, complete_event: Any) -> Iterable[Completion]:
        before = document.text_before_cursor
        *done, word = before.split(",")
        word = word.lstrip()
        entered = {part.strip().casefold() for part in done}
        for tag in self.known:
            folded = tag.casefold()
            if folded.startswith(word.casefold()) and folded not in entered:
                # The separator is added so the next tag can be typed at once.
                yield Completion(tag + ", ", start_position=-len(word), display=tag)


class QuestionaryPrompter:
    def __init__(self, console: Console, *, input: Any = None, output: Any = None):
        self.console = console
        self.io: dict[str, Any] = {}
        if input is not None:
            self.io["input"] = input
        if output is not None:
            self.io["output"] = output

    # -- output --------------------------------------------------------------

    def card(self, card: Card) -> None:
        lines = [f"[bold]{escape(card.title)}[/]", f"[dim]stage:[/] {escape(card.stage)}"]
        if card.summary:
            lines.append(escape(card.summary))
        if card.answers:
            lines.append("")
            lines += [f"[bold]{escape(label)}:[/] {escape(value)}" for label, value in card.answers]
        self.console.print(Panel("\n".join(lines), expand=False))

    def message(self, text: str) -> None:
        self.console.print(text, markup=False, highlight=False)

    # -- questions -------------------------------------------------------------

    def _hint(self, hint: str | None) -> None:
        """Print a hint on its own line, so it is not mixed up with the answer."""
        if hint:
            self.console.print(f"  [dim]{escape(hint)}[/]", highlight=False)

    def text(self, question: str, *, hint: str | None = None, default: str = "") -> str | None:
        self._hint(hint)
        answer = questionary.text(question, default=default, **self.io)
        return _ask(answer).strip() or None

    def long(self, question: str, *, hint: str | None = None, current: str = "") -> str | None:
        if current:
            self.console.print("[dim]Current answer:[/]")
            self.console.print(current, markup=False, highlight=False)
        editor = True
        while True:
            if editor:
                how = LONG_KEEP if current else LONG_SKIP
            else:
                how = LONG_KEEP_NO_EDITOR if current else LONG_SKIP_NO_EDITOR
            self._hint(_join(hint, how))
            raw = _ask(questionary.text(question, **self.io))
            answer = resolve_long(raw, current, notify=self.message)
            if answer is not ASK_AGAIN:
                return answer
            editor = False

    def items(
        self,
        question: str,
        *,
        hint: str | None = None,
        current: list[str],
        clear: str | None = None,
    ) -> list[str] | None:
        """Ask for list items one per line; `clear` is the command that clears the list."""
        line = f"[{QMARK_STYLE}]?[/] [bold]{escape(question)}[/]"
        if hint:
            line += f" [dim]{escape(hint)}[/]"
        self.console.print(line, highlight=False)
        result: list[str] = []
        dropped = False
        if current:
            for item in current:
                self.console.print(f"  - {escape(item)}", highlight=False)
            count = len(current)
            ask = "Keep this item?" if count == 1 else f"Keep these {count} items?"
            if _ask(questionary.confirm(ask, default=True, auto_enter=False, **self.io)):
                result = list(current)
            else:
                dropped = True
        kept = len(result)
        while True:
            prompt = f"  item {len(result) + 1} (Enter to finish)"
            try:
                item = _ask(questionary.text(prompt, qmark="", **self.io)).strip()
            except KeyboardInterrupt:
                if len(result) > kept:
                    raise PartialAnswer(result) from None
                raise
            if not item:
                break
            result.append(item)
        if dropped and not result:
            count = len(current)
            text = f"No items given; kept the {count} item{'' if count == 1 else 's'}."
            if clear:
                text += f" Clear the list with {clear}."
            self.message(text)
        # An empty list is a skip, not a request to clear: clearing is done with pet set.
        return None if not result or result == current else result

    def scale(
        self, question: str, *, hint: str | None = None, default: int | None = None
    ) -> int | None:
        choices = [
            questionary.Choice(SKIP, value="", shortcut_key="0"),
            *(questionary.Choice(str(n), value=str(n), shortcut_key=str(n)) for n in range(1, 6)),
        ]
        start = str(default) if default else ""
        answer = _ask(
            questionary.select(
                question,
                choices=choices,
                default=start,
                instruction=_join(hint, SCALE_KEYS),
                use_shortcuts=True,
                **self.io,
            )
        )
        return int(answer) if answer else None

    def choice(
        self,
        question: str,
        choices: list[str],
        *,
        hint: str | None = None,
        default: str | None = None,
    ) -> str | None:
        """A select with Skip first; returns None for Skip."""
        options = [questionary.Choice(SKIP, value=""), *choices]
        start = default if default in choices else ""
        answer = _ask(
            questionary.select(
                question, choices=options, default=start, instruction=hint, **self.io
            )
        )
        return answer or None

    def tags(
        self, question: str, *, hint: str | None = None, current: list[str], known: list[str]
    ) -> list[str] | None:
        self._hint(hint)
        raw = _ask(
            questionary.text(
                question,
                default=", ".join(current),
                completer=TagCompleter(known),
                **self.io,
            )
        )
        tags = [part.strip() for part in raw.split(",") if part.strip()]
        return tags or None

    def select(
        self, question: str, options: list[tuple[str, str]], *, default: str | None = None
    ) -> str:
        choices = [questionary.Choice(label, value=value) for value, label in options]
        values = [value for value, _ in options]
        start = default if default in values else None
        return _ask(questionary.select(question, choices=choices, default=start, **self.io))

    def confirm(self, question: str, *, default: bool = False) -> bool:
        return _ask(questionary.confirm(question, default=default, auto_enter=False, **self.io))
