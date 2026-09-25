"""Moving ideas between stages, and checking which expected fields are still empty."""

from __future__ import annotations

from metapet import fields, sections
from metapet.model import Idea, Status
from metapet.schema import LIFECYCLE, Field, Schema, Storage

__all__ = ["LIFECYCLE", "before", "describe", "gaps", "move", "promote", "statuses_between"]


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


def move(idea: Idea, new: Status, schema: Schema) -> None:
    """Change an idea's status, adding an empty section for each newly reached section field."""
    body = sections.parse(idea.body)
    added = False
    for status in statuses_between(idea.status, new):
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
    if added:
        idea.body = sections.render(body)
    idea.status = new
    idea.touch()


def promote(idea: Idea, target: Status, schema: Schema) -> None:
    """Move an idea, forgetting the shelved reason when it comes back from the shelf."""
    old = idea.status
    move(idea, target, schema)
    if old == Status.SHELVED and target != Status.SHELVED:
        idea.shelved_reason = None


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
