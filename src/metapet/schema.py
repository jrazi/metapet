"""Stage definitions: which fields each stage asks for, and where their answers are stored.

The built-in definitions live in ``stages.toml`` inside the package. A user file at
``<data home>/stages.toml`` can replace whole stages (see ``merge``).
"""

from __future__ import annotations

import functools
import re
import tomllib
from dataclasses import dataclass
from enum import StrEnum
from importlib import resources
from typing import TYPE_CHECKING, Any

from metapet.model import Status

if TYPE_CHECKING:
    from metapet.paths import DataHome

ANY = "any"
STAGE_NAMES = [status.value for status in Status] + [ANY]
LIFECYCLE = [Status.SEED, Status.SKETCH, Status.SPEC, Status.BUILDING, Status.SHIPPED]
KEY_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")
FIELD_OPTIONS = {
    "key",
    "label",
    "question",
    "hint",
    "kind",
    "required",
    "store",
    "choices",
    "aliases",
    "dated",
}
# Frontmatter keys the program manages itself; they cannot be fields.
OWNED_KEYS = {"id", "status", "created", "updated", "reviewed", "shelved_reason"}


class Kind(StrEnum):
    TEXT = "text"
    LONG = "long"
    LIST = "list"
    SCALE = "scale"
    CHOICE = "choice"
    TAGS = "tags"


class Storage(StrEnum):
    SECTION = "section"
    FRONTMATTER = "frontmatter"
    SUMMARY = "summary"


# Frontmatter keys with a fixed type in the model; a field using one must keep that kind.
TYPED_KEYS = {
    "title": Kind.TEXT,
    "tags": Kind.TAGS,
    "excitement": Kind.SCALE,
    "impact": Kind.SCALE,
    "effort": Kind.CHOICE,
    "repo": Kind.TEXT,
    "related": Kind.LIST,
}
EFFORT_CHOICES = ("S", "M", "L", "XL")


class SchemaError(ValueError):
    """A stage definition file is invalid."""


def _normalize(text: str) -> str:
    return " ".join(text.split()).casefold()


@dataclass(frozen=True)
class Field:
    key: str
    label: str
    question: str
    stage: str
    kind: Kind = Kind.TEXT
    required: bool = False
    storage: Storage = Storage.SECTION
    hint: str | None = None
    choices: tuple[str, ...] = ()
    aliases: tuple[str, ...] = ()
    dated: bool = False

    def matches_heading(self, heading: str) -> bool:
        wanted = _normalize(heading)
        return any(_normalize(name) == wanted for name in (self.label, *self.aliases))


@dataclass(frozen=True)
class Stage:
    name: str
    meaning: str
    fields: tuple[Field, ...]


@dataclass(frozen=True)
class Schema:
    stages: dict[str, Stage]

    def stage(self, name: str | Status) -> Stage:
        return self.stages[str(name)]

    def any_fields(self) -> tuple[Field, ...]:
        return self.stages[ANY].fields

    def fields_upto(self, status: Status) -> list[Field]:
        """Fields of the stages an idea at this status has passed through, then `any`."""
        if status == Status.SHELVED:
            names = [*LIFECYCLE[: LIFECYCLE.index(Status.BUILDING) + 1], Status.SHELVED]
        else:
            names = LIFECYCLE[: LIFECYCLE.index(status) + 1]
        return _unique(f for name in [*names, ANY] for f in self.stage(name).fields)

    def all_fields(self) -> list[Field]:
        return _unique(f for name in STAGE_NAMES for f in self.stages[name].fields)

    def field(self, name: str, *, labels: bool = True) -> Field:
        """Look a field up by key ("-" works as "_"), then by label."""
        key = name.strip().lower().replace("-", "_")
        fields = self.all_fields()
        for f in fields:
            if f.key == key:
                return f
        if labels:
            for f in fields:
                if _normalize(f.label) == _normalize(name):
                    return f
        raise KeyError(name)

    def section_fields(self) -> list[Field]:
        return [f for f in self.all_fields() if f.storage == Storage.SECTION]

    def section_order(self, heading: str) -> int | None:
        """Where a heading belongs among the schema's sections; None for the user's own."""
        for index, f in enumerate(self.section_fields()):
            if f.matches_heading(heading):
                return index
        return None


def _unique(fields) -> list[Field]:
    seen: set[str] = set()
    result = []
    for f in fields:
        if f.key not in seen:
            seen.add(f.key)
            result.append(f)
    return result


# -- loading -------------------------------------------------------------------


def parse(text: str, source: str, *, require_meaning: bool = False) -> dict[str, Stage]:
    """Validate one stage definition file; `source` names it in error messages."""

    def fail(problem: str) -> SchemaError:
        return SchemaError(f"{source}: {problem}")

    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise fail(f"invalid TOML: {exc}") from exc
    stages: dict[str, Stage] = {}
    for name, table in data.items():
        if name not in STAGE_NAMES:
            raise fail(f"unknown stage '{name}'; stages are: {', '.join(STAGE_NAMES)}")
        if not isinstance(table, dict):
            raise fail(f"'{name}' must be a table")
        unknown = set(table) - {"meaning", "fields"}
        if unknown:
            raise fail(f"[{name}]: unknown option '{sorted(unknown)[0]}'")
        meaning = table.get("meaning", "")
        if not isinstance(meaning, str) or (require_meaning and not meaning):
            raise fail(f"[{name}]: 'meaning' must be a line of text")
        raw_fields = table.get("fields", [])
        if not isinstance(raw_fields, list):
            raise fail(f"[{name}]: 'fields' must be a list of [[{name}.fields]] tables")
        fields = tuple(_parse_field(name, raw, fail) for raw in raw_fields)
        keys = [f.key for f in fields]
        for key in keys:
            if keys.count(key) > 1:
                raise fail(f"[{name}]: field '{key}' is defined more than once")
        stages[name] = Stage(name, meaning, fields)
    return stages


def _parse_field(stage: str, raw: Any, fail) -> Field:
    if not isinstance(raw, dict):
        raise fail(f"[{stage}]: each field must be a [[{stage}.fields]] table")
    where = f"[{stage}] field '{raw.get('key', '?')}'"
    unknown = set(raw) - FIELD_OPTIONS
    if unknown:
        raise fail(f"{where}: unknown option '{sorted(unknown)[0]}'")
    for option in ("key", "label", "question"):
        if not isinstance(raw.get(option), str) or not raw[option].strip():
            raise fail(f"{where}: '{option}' is required")
    key = raw["key"]
    if not KEY_PATTERN.match(key):
        raise fail(f"{where}: key must use lowercase letters, digits and _, starting with a letter")
    try:
        kind = Kind(raw.get("kind", Kind.TEXT))
    except ValueError:
        raise fail(f"{where}: kind must be one of {', '.join(Kind)}") from None
    try:
        storage = Storage(raw.get("store", Storage.SECTION))
    except ValueError:
        raise fail(f"{where}: store must be one of {', '.join(Storage)}") from None
    for option in ("choices", "aliases"):
        value = raw.get(option, [])
        if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
            raise fail(f"{where}: '{option}' must be a list of strings")
    choices = raw.get("choices")
    if kind == Kind.CHOICE and not choices:
        raise fail(f"{where}: kind 'choice' needs a 'choices' list")
    if kind != Kind.CHOICE and choices is not None:
        raise fail(f"{where}: 'choices' only works with kind 'choice'")
    if raw.get("dated") and kind != Kind.LIST:
        raise fail(f"{where}: 'dated' only works with kind 'list'")
    if storage == Storage.SUMMARY and kind not in (Kind.TEXT, Kind.LONG):
        raise fail(f"{where}: store 'summary' only works with kind 'text' or 'long'")
    if key in OWNED_KEYS:
        raise fail(f"{where}: '{key}' is managed by metapet and cannot be a field")
    if key in TYPED_KEYS:
        if storage != Storage.FRONTMATTER or kind != TYPED_KEYS[key]:
            raise fail(
                f"{where}: '{key}' must use store 'frontmatter' and kind '{TYPED_KEYS[key]}'"
            )
        if key == "effort" and tuple(choices) != EFFORT_CHOICES:
            raise fail(f"{where}: effort choices must be {', '.join(EFFORT_CHOICES)}")
    return Field(
        key=key,
        label=raw["label"].strip(),
        question=raw["question"].strip(),
        stage=stage,
        kind=kind,
        required=bool(raw.get("required", False)),
        storage=storage,
        hint=raw.get("hint") or None,
        choices=tuple(choices or ()),
        aliases=tuple(raw.get("aliases", ())),
        dated=bool(raw.get("dated", False)),
    )


def _check_summary(stages: dict[str, Stage], source: str) -> None:
    summary = [f for stage in stages.values() for f in stage.fields if f.storage == "summary"]
    if len({f.key for f in summary}) > 1:
        raise SchemaError(f"{source}: only one field can use store 'summary'")


@functools.cache
def builtin() -> Schema:
    text = resources.files("metapet").joinpath("stages.toml").read_text(encoding="utf-8")
    stages = parse(text, "built-in stages.toml", require_meaning=True)
    missing = [name for name in STAGE_NAMES if name not in stages]
    if missing:
        raise SchemaError(f"built-in stages.toml: missing {', '.join(missing)}")
    _check_summary(stages, "built-in stages.toml")
    return Schema(stages)


def merge(base: Schema, user: dict[str, Stage]) -> Schema:
    """A user stage replaces the built-in one wholly; only a missing meaning falls back."""
    stages = dict(base.stages)
    for name, stage in user.items():
        stages[name] = Stage(name, stage.meaning or base.stages[name].meaning, stage.fields)
    return Schema(stages)


def load(home: DataHome | None) -> Schema:
    """The built-in stages, changed by <home>/stages.toml when that file exists."""
    base = builtin()
    if home is None or not home.stages_file.is_file():
        return base
    source = str(home.stages_file)
    merged = merge(base, parse(home.stages_file.read_text(encoding="utf-8"), source))
    _check_summary(merged.stages, source)
    return merged
