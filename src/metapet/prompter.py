"""The questions interface used by the wizards, and a scripted version for tests.

Every method that asks something returns None when the user skips the question; the wizard
then keeps the current value. Ctrl-C raises KeyboardInterrupt, or PartialAnswer when a list
question already has new items.
"""

from __future__ import annotations

from typing import Any, Protocol

from metapet.views import Card


class PartialAnswer(KeyboardInterrupt):
    """Ctrl-C during a list question after some items were entered; `value` holds the list."""

    def __init__(self, value: list[str]):
        super().__init__()
        self.value = value


class Prompter(Protocol):
    def card(self, card: Card) -> None: ...

    def message(self, text: str) -> None: ...

    def text(self, question: str, *, hint: str | None = None, default: str = "") -> str | None: ...

    def long(self, question: str, *, hint: str | None = None, current: str = "") -> str | None: ...

    def items(
        self,
        question: str,
        *,
        hint: str | None = None,
        current: list[str],
        clear: str | None = None,
    ) -> list[str] | None: ...

    def scale(
        self, question: str, *, hint: str | None = None, default: int | None = None
    ) -> int | None: ...

    def choice(
        self,
        question: str,
        choices: list[str],
        *,
        hint: str | None = None,
        default: str | None = None,
    ) -> str | None: ...

    def tags(
        self, question: str, *, hint: str | None = None, current: list[str], known: list[str]
    ) -> list[str] | None: ...

    def select(
        self, question: str, options: list[tuple[str, str]], *, default: str | None = None
    ) -> str: ...

    def confirm(self, question: str, *, default: bool = False) -> bool: ...


class ScriptedPrompter:
    """Answers questions from a list, recording every call; for tests.

    An answer that is an exception instance is raised instead of returned.
    """

    def __init__(self, answers: list[Any]):
        self.answers = list(answers)
        self.calls: list[tuple[str, str, dict[str, Any]]] = []
        self.cards: list[Card] = []
        self.messages: list[str] = []

    def _answer(self, method: str, question: str, **kwargs: Any) -> Any:
        self.calls.append((method, question, kwargs))
        if not self.answers:
            raise AssertionError(f"unexpected question: {question}")
        answer = self.answers.pop(0)
        if isinstance(answer, BaseException):
            raise answer
        return answer

    def card(self, card: Card) -> None:
        self.cards.append(card)

    def message(self, text: str) -> None:
        self.messages.append(text)

    def text(self, question: str, *, hint: str | None = None, default: str = "") -> str | None:
        return self._answer("text", question, hint=hint, default=default)

    def long(self, question: str, *, hint: str | None = None, current: str = "") -> str | None:
        return self._answer("long", question, hint=hint, current=current)

    def items(
        self,
        question: str,
        *,
        hint: str | None = None,
        current: list[str],
        clear: str | None = None,
    ) -> list[str] | None:
        return self._answer("items", question, hint=hint, current=current)

    def scale(
        self, question: str, *, hint: str | None = None, default: int | None = None
    ) -> int | None:
        return self._answer("scale", question, hint=hint, default=default)

    def choice(
        self,
        question: str,
        choices: list[str],
        *,
        hint: str | None = None,
        default: str | None = None,
    ) -> str | None:
        return self._answer("choice", question, choices=choices, hint=hint, default=default)

    def tags(
        self, question: str, *, hint: str | None = None, current: list[str], known: list[str]
    ) -> list[str] | None:
        return self._answer("tags", question, hint=hint, current=current, known=known)

    def select(
        self, question: str, options: list[tuple[str, str]], *, default: str | None = None
    ) -> str:
        return self._answer("select", question, options=options, default=default)

    def confirm(self, question: str, *, default: bool = False) -> bool:
        return self._answer("confirm", question, default=default)
