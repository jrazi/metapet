"""Read, write and parse the value of a stage field on an idea."""

from __future__ import annotations

import datetime as dt
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from metapet import sections
from metapet.model import KNOWN_KEYS, Effort, Idea, clean_title
from metapet.schema import Field, Kind, Schema, Storage

Value = str | int | list[str] | None
Order = Callable[[str], int | None]

# Keys `set` refuses, with the reason.
NOT_SETTABLE = {
    "status": "use pet promote or pet shelve to change the status",
    "id": "use pet rename ID NEW_ID to change the id",
    **{
        key: f"'{key}' cannot be set" for key in ("created", "updated", "reviewed", "shelved_reason")
    },
}
SCALE_NUMBER = re.compile(r"\b([1-5])\b")
DISPLAY_WIDTH = 60


def _is_list(field: Field) -> bool:
    return field.kind in (Kind.LIST, Kind.TAGS)


# -- reading -------------------------------------------------------------------


def raw(idea: Idea, field: Field) -> str:
    """The text as written for a summary or section field (comments kept); "" if absent."""
    body = sections.parse(idea.body)
    if field.storage == Storage.SUMMARY:
        return body.preamble
    section = sections.find(body, field.matches_heading)
    return section.content if section else ""


def get(idea: Idea, field: Field) -> Value:
    if field.storage == Storage.FRONTMATTER:
        value = getattr(idea, field.key) if field.key in KNOWN_KEYS else idea.extra.get(field.key)
        return value.value if isinstance(value, Effort) else value
    text = raw(idea, field)
    if _is_list(field):
        return sections.items(text)
    text = sections.strip_comments(text).strip()
    if field.kind == Kind.SCALE:
        match = SCALE_NUMBER.search(text)
        return int(match.group(1)) if match else None
    return text or None


def is_filled(idea: Idea, field: Field) -> bool:
    if field.storage == Storage.FRONTMATTER:
        return get(idea, field) not in (None, "", [])
    return not sections.is_empty(raw(idea, field))


# -- writing -------------------------------------------------------------------


def put(idea: Idea, field: Field, value: Value, order: Order) -> None:
    """Store a value; None clears it. Does not touch() the idea."""
    if field.storage == Storage.FRONTMATTER:
        _put_frontmatter(idea, field, value)
    elif _is_list(field):
        put_text(idea, field, sections.render_items(list(value or [])), order)
    else:
        put_text(idea, field, "" if value is None else str(value), order)


def add_items(idea: Idea, field: Field, values: list[str], order: Order) -> None:
    """Add items to the end of a list section without rewriting what is already there."""
    put_text(idea, field, sections.extend_items(raw(idea, field), values), order)


def put_text(idea: Idea, field: Field, text: str, order: Order) -> None:
    """Write raw Markdown as a summary or section field's content."""
    body = sections.parse(idea.body)
    if field.storage == Storage.SUMMARY:
        body.preamble = text.strip()
    else:
        sections.upsert(body, field.label, text, field.matches_heading, order)
    idea.body = sections.render(body)


def _put_frontmatter(idea: Idea, field: Field, value: Value) -> None:
    if field.kind == Kind.SCALE and value is not None and not 1 <= int(value) <= 5:
        raise ValueError(f"{field.key} must be a number from 1 to 5")
    if field.key not in KNOWN_KEYS:
        if value is None:
            idea.extra.pop(field.key, None)
        else:
            idea.extra[field.key] = value
        return
    if field.key == "effort":
        value = Effort(str(value).upper()) if value else None
    elif field.key in ("tags", "related"):
        value = list(value or [])
    elif field.key == "title":
        try:
            value = clean_title(str(value or ""))
        except ValueError:
            raise ValueError("title cannot be empty") from None
    setattr(idea, field.key, value)


def add_note(idea: Idea, schema: Schema, text: str, today: dt.date | None = None) -> None:
    """Append a dated item to the Notes section, creating the section if needed."""
    text = " ".join(text.split())
    if not text:
        raise ValueError("the note is empty")
    try:
        field = schema.field("notes", labels=False)
    except KeyError:
        field = None
    if field is not None and field.storage == Storage.SECTION:
        heading, match = field.label, field.matches_heading
    else:
        heading, match = "Notes", lambda h: h.strip().casefold() == "notes"
    body = sections.parse(idea.body)
    existing = sections.find(body, match)
    item = f"{(today or dt.date.today()).isoformat()}: {text}"
    content = sections.append_item(existing.content if existing else "", item)
    sections.upsert(body, heading, content, match, schema.section_order)
    idea.body = sections.render(body)
    idea.touch()


# -- parsing and display -----------------------------------------------------------


def parse(field: Field, raw_value: str | list[str]) -> Value:
    """Turn user input into a value for this field; empty input means None (clear)."""
    if field.kind == Kind.LIST and field.storage == Storage.SECTION:
        parts = raw_value if isinstance(raw_value, list) else [raw_value]
        values = [" ".join(p.split()) for p in parts if p.strip()]
        return values or None
    text = " , ".join(raw_value) if isinstance(raw_value, list) else raw_value
    if _is_list(field):
        values = [part.strip() for part in text.split(",") if part.strip()]
        return values or None
    text = text.strip()
    if not text:
        return None
    if field.kind == Kind.SCALE:
        if text not in ("1", "2", "3", "4", "5"):
            raise ValueError(f"{field.key} must be a number from 1 to 5")
        return int(text)
    if field.kind == Kind.CHOICE:
        for choice in field.choices:
            if choice.casefold() == text.casefold():
                return choice
        raise ValueError(f"{field.key} must be one of {', '.join(field.choices)}")
    return text


def display(field: Field, value: Value) -> str:
    """One short line for cards and pickers."""
    if value is None:
        return ""
    text = ", ".join(value) if isinstance(value, list) else str(value)
    lines = text.strip().splitlines()
    text = lines[0] if lines else ""
    if len(text) > DISPLAY_WIDTH:
        text = text[: DISPLAY_WIDTH - 1].rstrip() + "…"
    return text


def placeholder(field: Field) -> str:
    return f"<!-- {field.question} -->"


# -- `pet set` changes ---------------------------------------------------------


@dataclass(frozen=True)
class Change:
    op: Literal["set", "add_tag", "remove_tag"]
    key: str
    value: str


def parse_changes(tokens: list[str]) -> list[Change]:
    changes = []
    for token in tokens:
        if "=" in token and not token.startswith(("+", "-")):
            key, value = token.split("=", 1)
            if key.strip():
                changes.append(Change("set", key.strip(), value))
                continue
        elif token[:1] in ("+", "-") and token[1:].strip():
            op = "add_tag" if token[0] == "+" else "remove_tag"
            changes.append(Change(op, "tags", token[1:].strip()))
            continue
        raise ValueError(f"expected key=value, +tag or -tag, got '{token}'")
    return changes


def apply_changes(idea: Idea, schema: Schema, changes: list[Change]) -> list[str]:
    """Validate every change, then apply them; returns a short description of each change.

    Raises ValueError listing every problem, without changing the idea.
    """
    problems: list[str] = []
    grouped: dict[str, tuple[Field, list[str]]] = {}
    for change in changes:
        if change.op != "set":
            continue
        key = change.key.lower().replace("-", "_")
        if key in NOT_SETTABLE:
            problems.append(NOT_SETTABLE[key])
            continue
        try:
            field = schema.field(key, labels=False)
        except KeyError:
            known = ", ".join(f.key for f in schema.all_fields())
            problems.append(f"unknown field '{change.key}'; known fields: {known}")
            continue
        if field.key in grouped and not (field.kind == Kind.LIST and field.storage == "section"):
            problems.append(f"'{field.key}' given more than once")
            continue
        grouped.setdefault(field.key, (field, []))[1].append(change.value)

    planned: dict[str, Value] = {}
    for key, (field, values) in grouped.items():
        is_section_list = field.kind == Kind.LIST and field.storage == Storage.SECTION
        try:
            value = parse(field, values if is_section_list else values[0])
        except ValueError as exc:
            problems.append(str(exc))
            continue
        if key == "title" and value is None:
            problems.append("title cannot be empty")
            continue
        planned[key] = value
    if problems:
        raise ValueError("\n".join(dict.fromkeys(problems)))

    done: list[str] = []
    for key, value in planned.items():
        field = grouped[key][0]
        if get(idea, field) == value or (value is None and not is_filled(idea, field)):
            continue
        put(idea, field, value, schema.section_order)
        done.append(f"{key}: {display(field, value)}" if value is not None else f"{key}: cleared")
    for change in changes:
        wanted = change.value.casefold()
        present = [t.casefold() for t in idea.tags]
        if change.op == "add_tag" and wanted not in present:
            idea.tags.append(change.value)
            done.append(f"tags: +{change.value}")
        elif change.op == "remove_tag" and wanted in present:
            idea.tags = [t for t in idea.tags if t.casefold() != wanted]
            done.append(f"tags: -{change.value}")
    if done:
        idea.touch()
    return done
