"""Question flows for new ideas, promotion and refining, on top of a Prompter.

Every answer is saved right away, so stopping with Ctrl-C keeps what was answered so far.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable
from dataclasses import dataclass, field

from metapet import fields, ids, stages, views
from metapet.model import Idea, Status, clean_title, is_long_title, short_title
from metapet.prompter import PartialAnswer, Prompter
from metapet.schema import LIFECYCLE, Field, Kind, Schema, Storage

TITLE_QUESTION = "Short name for the idea"
TITLE_HINT = "A few words, like Plant watering bot. The id is made from it."
LONG_TITLE_QUESTION = (
    "That is long for a name. Keep the full text as the summary and choose a shorter name?"
)
ID_QUESTION = "Id"
ID_HINT = "Lowercase letters, digits and hyphens. It is what you type in commands."
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
    exists: Callable[[str], bool] = lambda _: False  # whether an idea id is taken
    same_title: Callable[[str], list[Idea]] = lambda _: []  # ideas with the same title


@dataclass(frozen=True)
class Name:
    """What ask_name found out: the title, text to add to the summary, and the id."""

    title: str
    extra_summary: str | None
    id: str


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
            f"Press Enter to skip a question. Change answers later with pet refine {idea.id}."
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
        try:
            answer = p.items(f.question, hint=f.hint, current=existing)
        except PartialAnswer as exc:
            exc.value = _dated(s, f, existing, exc.value)
            raise
        return _dated(s, f, existing, answer)
    if f.kind == Kind.SCALE:
        return p.scale(f.question, hint=f.hint, default=current)
    if f.kind == Kind.CHOICE:
        return p.choice(f.question, list(f.choices), hint=f.hint, default=current)
    if f.kind == Kind.TAGS:
        return p.tags(f.question, hint=f.hint, current=list(current or []), known=s.known_tags)
    answer = p.text(f.question, hint=f.hint, default=str(current or ""))
    return (answer or "").strip() or None


def _dated(s: Session, f: Field, existing: list[str], answer: list[str] | None):
    """For a dated list, today's date before each new item."""
    if answer is None or not f.dated:
        return answer
    prefix = f"{s.today.isoformat()}: "
    return [item if item in existing else prefix + item for item in answer]


def _only_adds(f: Field, current: fields.Value, value: fields.Value) -> bool:
    """True when a list answer keeps the current items and adds new ones after them."""
    return (
        f.kind == Kind.LIST
        and f.storage == Storage.SECTION
        and isinstance(current, list)
        and isinstance(value, list)
        and bool(current)
        and value[: len(current)] == current
    )


def ask_field(s: Session, idea: Idea, f: Field) -> bool:
    """Ask one field; when the answer changes it, store it, touch the idea and save.

    Ctrl-C in a list question keeps the items entered so far, then stops.
    """
    try:
        value = _ask(s, idea, f)
    except PartialAnswer as exc:
        _store(s, idea, f, exc.value)
        raise KeyboardInterrupt from None
    return _store(s, idea, f, value)


def _store(s: Session, idea: Idea, f: Field, value: fields.Value) -> bool:
    current = fields.get(idea, f)
    if value is None or value == [] or value == current:
        return False
    if _only_adds(f, current, value):
        # Keep the section as written (nested items, numbering, paragraphs) and append.
        fields.add_items(idea, f, value[len(current) :], s.schema.section_order)
    else:
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
        f = s.schema.field("title", labels=False)
        question, hint = f.question, f.hint
    except KeyError:
        question, hint = TITLE_QUESTION, TITLE_HINT
    while True:
        title = " ".join((s.prompter.text(question, hint=hint) or "").split())
        if title:
            return title
        s.prompter.message("A name is needed (Ctrl-C to cancel).")


def _unique(s: Session, base: str) -> str:
    candidate, n = base, 2
    while s.exists(candidate):
        candidate, n = ids.with_suffix(base, n), n + 1
    return candidate


def ask_id(s: Session, suggested: str) -> str:
    """Ask for an id until the answer is valid and not in use."""
    while True:
        answer = s.prompter.text(ID_QUESTION, hint=ID_HINT, default=suggested) or suggested
        try:
            idea_id = ids.validate(answer)
        except ValueError as exc:
            s.prompter.message(f"{str(exc).capitalize()}.")
            continue
        if s.exists(idea_id):
            s.prompter.message(f"An idea with id '{idea_id}' already exists.")
            continue
        return idea_id


def ask_name(
    s: Session, supplied_title: str | None = None, supplied_id: str | None = None
) -> Name | None:
    """Ask for the title, a shorter one when it is long, and the id when it is not exact.

    Returns None when the user decides not to add an idea with the same name as another.
    """
    title = clean_title(supplied_title) if supplied_title else ask_title(s)
    extra = None
    if is_long_title(title) and s.prompter.confirm(LONG_TITLE_QUESTION, default=True):
        extra = title
        while True:
            answer = s.prompter.text(TITLE_QUESTION, default=short_title(title))
            short = " ".join((answer or "").split())
            if short:
                title = short
                break
            s.prompter.message("A name is needed (Ctrl-C to cancel).")
    same = s.same_title(title)
    if same:
        listed = ", ".join(f"{idea.id} ({idea.status.value})" for idea in same)
        question = (
            f"An idea with this name already exists: {listed}. Create another one anyway?"
        )
        if not s.prompter.confirm(question, default=False):
            s.prompter.message(f'Nothing added. Add to it with pet note {same[0].id} "..."')
            return None
    if supplied_id is not None:
        return Name(title, extra, supplied_id)
    suggestion = ids.suggest(title, s.today)
    unique = _unique(s, suggestion.id)
    return Name(title, extra, unique if suggestion.exact else ask_id(s, unique))


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
    # Fields already asked about in the gap step are not asked again below.
    answered: set[str] = set()
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
                answered = {f.key for f in gaps}
        else:
            s.prompter.message(f"Warning: still empty: {empty}")
    stages.promote(idea, target, s.schema)
    s.save(idea)
    for status in reached:
        stage = s.schema.stage(status)
        to_ask = [f for f in stage.fields if f.key not in answered]
        if not to_ask:
            continue
        show_card(s, idea)
        s.prompter.message(f"{status.value}: {stage.meaning}")
        ask_fields(s, idea, to_ask)
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
