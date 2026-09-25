"""Going through ideas that have not been looked at for a while.

`due` picks the ideas; `run` asks what to do with each one, on top of a Prompter.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from metapet import fields, stages, wizard
from metapet.model import Idea, IdeaError
from metapet.schema import Field, Kind, Storage

# Used when a custom stages.toml has no excitement field.
EXCITEMENT = Field(
    key="excitement",
    label="Excitement",
    question="How excited are you about it?",
    stage="seed",
    kind=Kind.SCALE,
    storage=Storage.FRONTMATTER,
)


@dataclass
class ReviewResult:
    handled: int
    remaining: int
    stopped: bool = False  # True when Ctrl-C or Ctrl-D ended the review


def last_seen(idea: Idea) -> dt.date:
    """The latest of the reviewed, updated and created dates."""
    return max(d for d in (idea.reviewed, idea.updated, idea.created) if d)


def due(ideas: list[Idea], days: int, today: dt.date | None = None) -> list[Idea]:
    """Live ideas not seen for at least `days` days, oldest first."""
    today = today or dt.date.today()
    found = [
        idea
        for idea in ideas
        if not idea.status.terminal and (today - last_seen(idea)).days >= days
    ]
    return sorted(found, key=lambda idea: (last_seen(idea), idea.id))


def _excitement_field(s: wizard.Session) -> Field:
    try:
        return s.schema.field("excitement", labels=False)
    except KeyError:
        return EXCITEMENT


def _options(idea: Idea) -> list[tuple[str, str]]:
    target = idea.status.next()
    options = [("promote", f"Promote to {target.value}")] if target else []
    return [
        *options,
        ("refine", "Refine"),
        ("note", "Add a note"),
        ("excitement", "Set excitement"),
        ("shelve", "Shelve"),
        ("skip", "Skip"),
        ("quit", "Quit"),
    ]


def _act(s: wizard.Session, idea: Idea, action: str) -> None:
    """Run one menu action; saving is up to the caller."""
    p = s.prompter
    if action == "promote":
        target = idea.status.next()
        if target is not None:
            wizard.promote(s, idea, target, ask_about_gaps=True)
    elif action == "refine":
        wizard.refine(s, idea, None)
    elif action == "note":
        text = (p.text("What do you want to note?") or "").strip()
        if text:
            fields.add_note(idea, s.schema, text, today=s.today)
    elif action == "excitement":
        wizard.ask_field(s, idea, _excitement_field(s))
    elif action == "shelve":
        reason = (p.text("Why are you shelving it?") or "").strip()
        if reason:
            stages.shelve(idea, reason, s.schema, s.today)


def _review_one(s: wizard.Session, idea: Idea) -> bool:
    """Ask what to do until something changes or the user skips; False means quit."""
    while True:
        wizard.show_card(s, idea)
        action = s.prompter.select("What do you want to do?", _options(idea))
        if action == "quit":
            return False
        before = idea.to_markdown()
        _act(s, idea, action)
        if action == "skip" or idea.to_markdown() != before:
            idea.mark_reviewed(s.today)
            s.save(idea)
            return True


def _reload(idea: Idea) -> Idea | None:
    """The idea as it is on disk now, so changes made during the review are not overwritten."""
    if idea.path is None:
        return idea
    try:
        return Idea.load(idea.path)
    except (OSError, IdeaError):
        return None


def run(s: wizard.Session, ideas: list[Idea], today: dt.date | None = None) -> ReviewResult:
    """Go through the ideas one by one. Answers are saved as they are given."""
    if today is not None:
        s.today = today
    total = len(ideas)
    s.prompter.message(f"{total} idea{'' if total == 1 else 's'} to review.")
    handled = done = 0
    try:
        for idea in ideas:
            fresh = _reload(idea)
            if fresh is None:
                s.prompter.message(f"{idea.id}: skipped, its file is gone or cannot be read.")
                done += 1
                continue
            if not _review_one(s, fresh):
                break
            handled += 1
            done += 1
    except (KeyboardInterrupt, EOFError):
        return ReviewResult(handled, total - done, stopped=True)
    return ReviewResult(handled, total - done)
