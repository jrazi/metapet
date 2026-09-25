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

from metapet.views import Card

SKIP = "Skip"
LONG_INSTRUCTION = "Enter to skip, or type e and Enter to write in your editor"


def resolve_long(
    raw: str, current: str, edit: Callable[..., str | None] = click.edit
) -> str | None:
    """Turn the answer to a long question into the new text; None keeps the current text."""
    answer = raw.strip()
    if answer.casefold() == "e":
        edited = edit(text=current, extension=".md")
        if edited is None or not edited.strip() or edited.strip() == current.strip():
            return None
        return edited.strip()
    return answer or None


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
                yield Completion(tag, start_position=-len(word))


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

    def text(self, question: str, *, hint: str | None = None, default: str = "") -> str | None:
        answer = questionary.text(question, default=default, instruction=hint, **self.io)
        return answer.unsafe_ask().strip() or None

    def long(self, question: str, *, hint: str | None = None, current: str = "") -> str | None:
        if hint:
            self.console.print(f"[dim]{escape(hint)}[/]")
        if current:
            self.console.print(f"[dim]{escape(current)}[/]")
            self.console.print("[dim]Enter keeps it.[/]")
        raw = questionary.text(question, instruction=LONG_INSTRUCTION, **self.io).unsafe_ask()
        return resolve_long(raw, current)

    def items(
        self, question: str, *, hint: str | None = None, current: list[str]
    ) -> list[str] | None:
        self.console.print(f"[bold]{escape(question)}[/]")
        if hint:
            self.console.print(f"[dim]{escape(hint)}[/]")
        result: list[str] = []
        if current:
            for item in current:
                self.console.print(f"  - {escape(item)}")
            keep = questionary.confirm(f"Keep these {len(current)} items?", default=True, **self.io)
            if keep.unsafe_ask():
                result = list(current)
        while True:
            prompt = f"  item {len(result) + 1} (Enter to finish)"
            item = questionary.text(prompt, qmark="", **self.io).unsafe_ask().strip()
            if not item:
                break
            result.append(item)
        # An empty list is a skip, not a request to clear: clearing is done with pet set.
        return None if not result or result == current else result

    def scale(
        self, question: str, *, hint: str | None = None, default: int | None = None
    ) -> int | None:
        options = [str(n) for n in range(1, 6)]
        answer = self._pick(question, options, hint, str(default) if default else None)
        return int(answer) if answer else None

    def choice(
        self,
        question: str,
        choices: list[str],
        *,
        hint: str | None = None,
        default: str | None = None,
    ) -> str | None:
        return self._pick(question, list(choices), hint, default)

    def _pick(
        self, question: str, options: list[str], hint: str | None, default: str | None
    ) -> str | None:
        """A select with Skip first; returns None for Skip."""
        choices = [questionary.Choice(SKIP, value=""), *options]
        start = default if default in options else ""
        answer = questionary.select(
            question, choices=choices, default=start, instruction=hint, **self.io
        ).unsafe_ask()
        return answer or None

    def tags(
        self, question: str, *, hint: str | None = None, current: list[str], known: list[str]
    ) -> list[str] | None:
        raw = questionary.text(
            question,
            default=", ".join(current),
            instruction=hint,
            completer=TagCompleter(known),
            **self.io,
        ).unsafe_ask()
        tags = [part.strip() for part in raw.split(",") if part.strip()]
        return tags or None

    def select(self, question: str, options: list[tuple[str, str]]) -> str:
        choices = [questionary.Choice(label, value=value) for value, label in options]
        return questionary.select(question, choices=choices, **self.io).unsafe_ask()

    def confirm(self, question: str, *, default: bool = False) -> bool:
        return questionary.confirm(question, default=default, **self.io).unsafe_ask()
