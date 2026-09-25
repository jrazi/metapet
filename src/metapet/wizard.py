"""Question flows for new ideas, promotion and refining, on top of a Prompter.

Every answer is saved right away, so stopping with Ctrl-C keeps what was answered so far.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable
from dataclasses import dataclass, field

from metapet import fields, stages, views
from metapet.model import Idea, Status
from metapet.prompter import Prompter
from metapet.schema import LIFECYCLE, Field, Kind, Schema

TITLE_QUESTION = "What is the idea, in a few words?"
# Stages the continuation after `new` offers to move on to.
CONTINUE_TO = (Status.SKETCH, Status.SPEC, Status.BUILDING)


@dataclass
class Session:
    schema: Schema
    prompter: Prompter
    save: Callable[[Idea], None]
    known_tags: list[str]
    today: dt.date = field(default_factory=dt.date.today)
    last_card: views.Card | None = None
    started: bool = False


def show_card(s: Session, idea: Idea) -> None:
    """Show the idea's card, unless it is the same card as the one shown last."""
    card = views.card(idea, s.schema)
    if card != s.last_card:
        s.prompter.card(card)
        s.last_card = card


def _start(s: Session, idea: Idea) -> None:
    if not s.started:
        s.started = True
        s.prompter.message(
            f"Press Enter to skip a question. To clear a value later, run "
            f"pet set {idea.id} KEY= (for example: pet set {idea.id} summary=)."
        )
    show_card(s, idea)


# -- single fields ---------------------------------------------------------------


def _ask(s: Session, idea: Idea, f: Field) -> fields.Value:
    p = s.prompter
    current = fields.get(idea, f)
    if f.kind == Kind.LONG:
        return p.long(f.question, hint=f.hint, current=current or "")
    if f.kind == Kind.LIST:
        existing = list(current or [])
        answer = p.items(f.question, hint=f.hint, current=existing)
        if answer is not None and f.dated:
            prefix = f"{s.today.isoformat()}: "
            answer = [item if item in existing else prefix + item for item in answer]
        return answer
    if f.kind == Kind.SCALE:
        return p.scale(f.question, hint=f.hint, default=current)
    if f.kind == Kind.CHOICE:
        return p.choice(f.question, list(f.choices), hint=f.hint, default=current)
    if f.kind == Kind.TAGS:
        return p.tags(f.question, hint=f.hint, current=list(current or []), known=s.known_tags)
    answer = p.text(f.question, hint=f.hint, default=str(current or ""))
    return (answer or "").strip() or None


def ask_field(s: Session, idea: Idea, f: Field) -> bool:
    """Ask one field; when the answer changes it, store it, touch the idea and save."""
    value = _ask(s, idea, f)
    if value is None or value == fields.get(idea, f):
        return False
    fields.put(idea, f, value, s.schema.section_order)
    idea.touch()
    s.save(idea)
    return True


def ask_fields(s: Session, idea: Idea, fields_to_ask: list[Field]) -> None:
    for f in fields_to_ask:
        ask_field(s, idea, f)


# -- flows -----------------------------------------------------------------------


def ask_title(s: Session) -> str:
    try:
        question = s.schema.field("title", labels=False).question
    except KeyError:
        question = TITLE_QUESTION
    while True:
        title = (s.prompter.text(question) or "").strip()
        if title:
            return title
        s.prompter.message("A title is needed.")


def new_idea(s: Session, idea: Idea, supplied: set[str]) -> None:
    """Ask the seed fields that were not supplied and are still empty."""
    _start(s, idea)
    ask_fields(
        s,
        idea,
        [
            f
            for f in s.schema.stage(Status.SEED).fields
            if f.key not in supplied and not fields.is_filled(idea, f)
        ],
    )


def continue_stages(s: Session, idea: Idea) -> None:
    """Offer to move on to the next stage and answer its questions, one stage at a time."""
    while (target := idea.status.next()) in CONTINUE_TO:
        question = f"Promote to {target.value} and answer its questions now?"
        if not s.prompter.confirm(question, default=False):
            return
        if not promote(s, idea, target, ask_about_gaps=False):
            return


def promote(s: Session, idea: Idea, target: Status, *, ask_about_gaps: bool = True) -> bool:
    """Promote with questions; returns False when the user cancels.

    Backward moves and moves from shelved ask nothing.
    """
    reached = stages.statuses_between(idea.status, target)
    if idea.status not in LIFECYCLE or target not in LIFECYCLE or not reached:
        stages.promote(idea, target, s.schema)
        s.save(idea)
        return True
    _start(s, idea)
    gaps = stages.gaps(idea, s.schema, stages.before(target))
    if gaps:
        empty = ", ".join(f"{f.label} ({f.stage})" for f in gaps)
        if ask_about_gaps:
            s.prompter.message(f"Still empty: {empty}")
            action = s.prompter.select(
                "What do you want to do?",
                [("fill", "Fill them now"), ("anyway", "Promote anyway"), ("cancel", "Cancel")],
            )
            if action == "cancel":
                return False
            if action == "fill":
                ask_fields(s, idea, gaps)
        else:
            s.prompter.message(f"Warning: still empty: {empty}")
    stages.promote(idea, target, s.schema)
    s.save(idea)
    for status in reached:
        stage = s.schema.stage(status)
        if not stage.fields:
            continue
        show_card(s, idea)
        s.prompter.message(f"{status.value}: {stage.meaning}")
        ask_fields(s, idea, list(stage.fields))
    return True


def _where(f: Field) -> str:
    return "any stage" if f.stage == "any" else f.stage


def refine(s: Session, idea: Idea, f: Field | None) -> None:
    """Ask one field, or let the user pick fields from a list until Done."""
    _start(s, idea)
    if f is not None:
        ask_field(s, idea, f)
        return
    available = s.schema.fields_upto(idea.status)
    while True:
        options = [
            (
                item.key,
                f"[{'x' if fields.is_filled(idea, item) else ' '}] {item.label}  ({_where(item)})",
            )
            for item in available
        ]
        # Field keys start with a letter, so "" cannot clash with one.
        choice = s.prompter.select("Which field?", [*options, ("", "Done")])
        if not choice:
            return
        ask_field(s, idea, next(item for item in available if item.key == choice))
