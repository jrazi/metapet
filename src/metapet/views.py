"""Plain data views of ideas, shared by the command line and the terminal UI."""

from __future__ import annotations

from dataclasses import dataclass

from metapet import fields, sections
from metapet.model import Idea, Status
from metapet.schema import LIFECYCLE, Field, Schema, Storage


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


def visible_body(idea: Idea, schema: Schema) -> tuple[str, list[str]]:
    """The body for display, without its empty sections, and the names of the empty ones.

    A section counts as empty when it holds only whitespace, comments or bare list markers.
    Expected sections of the idea's stages that are missing from the file count as empty too.
    Headings of known fields are shown with their label. Required fields are marked with *.
    """
    body = sections.parse(idea.body)
    kept: list[sections.Section] = []
    empty: list[str] = []
    present: set[str] = set()

    def name(field: Field) -> str:
        return f"{field.label}*" if field.required else field.label

    for section in body.sections:
        field = next(
            (f for f in schema.section_fields() if f.matches_heading(section.heading)), None
        )
        if field is not None:
            present.add(field.key)
        if not sections.is_empty(section.content):
            heading = field.label if field is not None else section.heading
            kept.append(sections.Section(heading, section.content))
        else:
            empty.append(name(field) if field is not None else section.heading)
    if idea.status in LIFECYCLE:
        for status in LIFECYCLE[: LIFECYCLE.index(idea.status) + 1]:
            for field in schema.stage(status).fields:
                if field.storage == Storage.SECTION and field.key not in present:
                    empty.append(name(field))
                    present.add(field.key)
    preamble = sections.strip_comments(body.preamble).strip()
    return hard_breaks(sections.render(sections.Body(preamble, kept))), empty


def hard_breaks(markdown: str) -> str:
    """Keep the line breaks the user typed: Markdown would join single lines into one."""
    lines = markdown.split("\n")
    out: list[str] = []
    fenced = False
    for index, line in enumerate(lines):
        if line.lstrip().startswith(("```", "~~~")):
            fenced = not fenced
        following = lines[index + 1] if index + 1 < len(lines) else ""
        if not fenced and line.strip() and following.strip() and not line.startswith("#"):
            line = line.rstrip() + "  "
        out.append(line)
    return "\n".join(out)


def empty_line(empty: list[str]) -> str:
    return "Empty: " + ", ".join(empty) if empty else ""


def preview_markdown(idea: Idea, schema: Schema) -> str:
    """The idea as one Markdown document: title, a line of details, then the body."""
    meta = [idea.id, idea.status.value]
    if idea.tags:
        meta.append("tags: " + ", ".join(idea.tags))
    for name in ("excitement", "impact"):
        if getattr(idea, name):
            meta.append(f"{name} {getattr(idea, name)}/5")
    if idea.effort:
        meta.append(f"effort {idea.effort.value}")
    parts = [f"# {idea.title}", " · ".join(meta)]
    body, empty = visible_body(idea, schema)
    if body.strip():
        parts.append(body.strip())
    if empty:
        escaped = empty_line(empty).replace("\\", "\\\\").replace("*", "\\*").replace("_", "\\_")
        parts.append(f"*{escaped}*")
    return "\n\n".join(parts) + "\n"


@dataclass(frozen=True)
class Query:
    statuses: set[str]
    tags: set[str]
    words: list[str]
    unknown_statuses: list[str]  # status: names that are not statuses


def parse_query(query: str) -> Query:
    """Split a filter into status:NAME and tag:NAME tokens and plain words."""
    statuses: set[str] = set()
    tags: set[str] = set()
    words: list[str] = []
    unknown: list[str] = []
    names = {status.value for status in Status}
    for token in query.split():
        name, _, value = token.partition(":")
        if name.lower() == "status" and value:
            statuses.add(value.lower())
            if value.lower() not in names and value.lower() not in unknown:
                unknown.append(value.lower())
        elif name.lower() == "tag" and value:
            tags.add(value.casefold())
        else:
            words.append(token.casefold())
    return Query(statuses, tags, words, unknown)


def filter_ideas(ideas: list[Idea], query: str, *, everything: bool = False) -> list[Idea]:
    """Filter by words plus `status:NAME` and `tag:NAME` tokens.

    Tokens of the same kind are alternatives; everything else must all match, in the id,
    title, tags or text (comments left out). Shipped and shelved ideas are hidden unless a
    status: token asks for them, or `everything` is True.
    """
    q = parse_query(query)

    def keep(idea: Idea) -> bool:
        if q.statuses:
            if idea.status.value not in q.statuses:
                return False
        elif idea.status.terminal and not everything:
            return False
        if q.tags and not q.tags & {t.casefold() for t in idea.tags}:
            return False
        body = sections.strip_comments(idea.body)
        text = " ".join([idea.id, idea.title, *idea.tags, body]).casefold()
        return all(word in text for word in q.words)

    return [idea for idea in ideas if keep(idea)]
