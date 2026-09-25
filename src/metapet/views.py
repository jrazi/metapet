"""Plain data views of ideas, shared by the command line and the terminal UI."""

from __future__ import annotations

from dataclasses import dataclass

from metapet import fields, sections
from metapet.model import Idea
from metapet.schema import Schema, Storage


@dataclass(frozen=True)
class Card:
    title: str
    stage: str
    summary: str | None
    answers: list[tuple[str, str]]  # (label, value) of filled fields, in schema order


def card(idea: Idea, schema: Schema) -> Card:
    summary = sections.strip_comments(sections.parse(idea.body).preamble).strip() or None
    answers = [
        (field.label, fields.display(field, fields.get(idea, field)))
        for field in schema.all_fields()
        if field.key != "title"
        and field.storage != Storage.SUMMARY
        and fields.is_filled(idea, field)
    ]
    return Card(idea.title, idea.status.value, summary, answers)


def preview_markdown(idea: Idea) -> str:
    """The idea as one Markdown document: title, a line of details, then the body."""
    meta = [idea.status.value]
    if idea.tags:
        meta.append("tags: " + ", ".join(idea.tags))
    for name in ("excitement", "impact"):
        if getattr(idea, name):
            meta.append(f"{name} {getattr(idea, name)}/5")
    if idea.effort:
        meta.append(f"effort {idea.effort.value}")
    parts = [f"# {idea.title}", " · ".join(meta)]
    if idea.body.strip():
        parts.append(idea.body.strip())
    return "\n\n".join(parts) + "\n"


def filter_ideas(ideas: list[Idea], query: str) -> list[Idea]:
    """Filter by words plus `status:NAME` and `tag:NAME` tokens.

    Tokens of the same kind are alternatives; everything else must all match. Shipped and
    shelved ideas are hidden unless a status: token asks for them.
    """
    statuses: set[str] = set()
    tags: set[str] = set()
    words: list[str] = []
    for token in query.split():
        name, _, value = token.partition(":")
        if name.lower() == "status" and value:
            statuses.add(value.lower())
        elif name.lower() == "tag" and value:
            tags.add(value.casefold())
        else:
            words.append(token.casefold())

    def keep(idea: Idea) -> bool:
        if statuses:
            if idea.status.value not in statuses:
                return False
        elif idea.status.terminal:
            return False
        if tags and not tags & {t.casefold() for t in idea.tags}:
            return False
        text = " ".join([idea.id, idea.title, *idea.tags, idea.body]).casefold()
        return all(word in text for word in words)

    return [idea for idea in ideas if keep(idea)]
