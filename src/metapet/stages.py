"""Moving ideas between stages, and checking which expected fields are still empty."""

from __future__ import annotations

import datetime as dt

from metapet import fields, sections
from metapet.model import Idea, Status
from metapet.schema import LIFECYCLE, Field, Schema, Storage

__all__ = [
    "LIFECYCLE",
    "before",
    "describe",
    "gaps",
    "move",
    "promote",
    "shelve",
    "statuses_between",
]


def statuses_between(old: Status, new: Status) -> list[Status]:
    """Statuses newly reached when moving old → new (empty when moving back)."""
    if new == Status.SHELVED:
        return [Status.SHELVED]
    if old not in LIFECYCLE or LIFECYCLE.index(new) <= LIFECYCLE.index(old):
        return []
    return LIFECYCLE[LIFECYCLE.index(old) + 1 : LIFECYCLE.index(new) + 1]


def before(target: Status) -> Status | None:
    """The lifecycle stage just before target; None for seed and shelved."""
    if target not in LIFECYCLE or target == LIFECYCLE[0]:
        return None
    return LIFECYCLE[LIFECYCLE.index(target) - 1]


def _add_sections(body: sections.Body, statuses: list[Status], schema: Schema) -> bool:
    """Add an empty section for each section field of these stages that has none yet."""
    added = False
    for status in statuses:
        for field in schema.stage(status).fields:
            if field.storage != Storage.SECTION or sections.find(body, field.matches_heading):
                continue
            sections.upsert(
                body,
                field.label,
                fields.placeholder(field),
                field.matches_heading,
                schema.section_order,
            )
            added = True
    return added


def move(idea: Idea, new: Status, schema: Schema) -> None:
    """Change an idea's status, adding an empty section for each newly reached section field."""
    body = sections.parse(idea.body)
    if _add_sections(body, statuses_between(idea.status, new), schema):
        idea.body = sections.render(body)
    idea.status = new
    idea.touch()


def _move_back_to_lifecycle(idea: Idea, target: Status, schema: Schema) -> None:
    """Move a shipped or shelved idea back to a stage of the lifecycle.

    The idea gets the sections of every stage up to the target, like an idea promoted
    there step by step. Empty sections of fields the target stage does not have (such as
    the Retro that shelving added) are removed; filled ones are kept.
    """
    body = sections.parse(idea.body)
    changed = _add_sections(body, LIFECYCLE[: LIFECYCLE.index(target) + 1], schema)
    kept_keys = {f.key for f in schema.fields_upto(target)}
    for status in (Status.SHIPPED, Status.SHELVED):
        for field in schema.stage(status).fields:
            if field.key in kept_keys or field.storage != Storage.SECTION:
                continue
            section = sections.find(body, field.matches_heading)
            if section is not None and sections.is_empty(section.content):
                body.sections.remove(section)
                changed = True
    if changed:
        idea.body = sections.render(body)
    idea.status = target
    idea.touch()


def promote(idea: Idea, target: Status, schema: Schema, today: dt.date | None = None) -> None:
    """Move an idea. One that comes back from the shelf keeps its reason in a dated note."""
    old = idea.status
    if old == Status.SHELVED and target != Status.SHELVED:
        reason = idea.shelved_reason
        note = (
            f"Back from the shelf (it was shelved: {reason})" if reason else "Back from the shelf"
        )
        fields.add_note(idea, schema, note, today)
        idea.shelved_reason = None
    if old.terminal and target in LIFECYCLE:
        _move_back_to_lifecycle(idea, target, schema)
    else:
        move(idea, target, schema)


def shelve(idea: Idea, reason: str, schema: Schema, today: dt.date | None = None) -> str | None:
    """Shelve an idea with a reason, also kept as a dated note.

    Returns the previous reason when the idea was already shelved. Raises ValueError for a
    blank reason.
    """
    reason = " ".join(reason.split())
    if not reason:
        raise ValueError("give a reason")
    previous = idea.shelved_reason if idea.status == Status.SHELVED else None
    fields.add_note(idea, schema, f"Shelved: {reason}", today)
    move(idea, Status.SHELVED, schema)
    idea.shelved_reason = reason
    return previous


def gaps(idea: Idea, schema: Schema, upto: Status | None) -> list[Field]:
    """Required fields of the stages seed..upto that are still empty."""
    if upto is None or upto not in LIFECYCLE:
        return []
    result: list[Field] = []
    seen: set[str] = set()
    for status in LIFECYCLE[: LIFECYCLE.index(upto) + 1]:
        for field in schema.stage(status).fields:
            if field.required and field.key not in seen and not fields.is_filled(idea, field):
                result.append(field)
            seen.add(field.key)
    return result


def describe(schema: Schema) -> list[tuple[Status, str, list[Field]]]:
    """(status, meaning, fields) for every stage, in lifecycle order."""
    return [
        (status, schema.stage(status).meaning, list(schema.stage(status).fields))
        for status in [*LIFECYCLE, Status.SHELVED]
    ]
