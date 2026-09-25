"""The `pet` command-line interface."""

from __future__ import annotations

import datetime as dt
import importlib
import inspect
import random
import sys
from collections import Counter
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Literal, NoReturn, TypeVar

import click
import typer
from rich.console import Console
from rich.markdown import Markdown
from rich.markup import escape
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from typer.core import TyperArgument, TyperCommand

from metapet import (
    export,
    fields,
    ids,
    paths,
    schema,
    scoring,
    sections,
    stages,
    sync,
    views,
    wizard,
)
from metapet import review as review_
from metapet.model import Idea, IdeaError, Status, clean_title, is_long_title, short_title
from metapet.prompter import Prompter
from metapet.schema import Schema, SchemaError, Storage
from metapet.store import BrokenFile, IdeaLookupError, Store

T = TypeVar("T")


def _stage_rows(idea_schema: Schema) -> list[str]:
    """Each stage with its meaning, and its field keys on the next line (* = expected)."""

    def keys(stage_fields) -> str:
        return ", ".join(f"{f.key}*" if f.required else f.key for f in stage_fields)

    described = [
        (status.value, meaning, stage_fields)
        for status, meaning, stage_fields in stages.describe(idea_schema)
    ]
    described.append(("any stage", "can be filled at any stage", idea_schema.any_fields()))
    name_w = max(len(name) for name, _, _ in described)
    rows = []
    for name, meaning, stage_fields in described:
        rows.append(f"  {name:<{name_w}}  {meaning}".rstrip())
        if stage_fields:
            rows.append(f"  {'':<{name_w}}  {keys(stage_fields)}")
    return rows


def _lifecycle_help() -> str:
    return (
        "[bold]Lifecycle:[/] seed → sketch → spec → building → shipped, or shelved at any point.\n"
        + "\n".join(_stage_rows(schema.builtin()))
        + "\n\n"
        "Fields marked * are expected before moving on; promote only warns when they are empty, "
        "and any question can be skipped. Change the stages in <data home>/stages.toml (see the "
        "README): a stage defined there replaces the built-in stage of the same name. "
        "pet stages shows the stages in use."
    )


LIFECYCLE_HELP = _lifecycle_help()

# Newer Typer versions build commands on their own copy of click; parameter types and
# completion items must come from the same copy.
_click_package = TyperCommand.__mro__[1].__module__.rpartition(".")[0]
_click_types = importlib.import_module(_click_package + ".types")
_click_completion = importlib.import_module(_click_package + ".shell_completion")


class _Text(_click_types.StringParamType):
    """Plain text argument; help shows only its name, not a `<str>` type."""

    def get_metavar(self, param: TyperArgument, ctx: typer.Context | None = None) -> str:
        return ""


class _IdText(_Text):
    """An idea id argument that completes ids.

    Typer's own `autocompletion` keeps only values that start with the typed text,
    which would drop matches on a fragment of the id or title.
    """

    def shell_complete(self, ctx: typer.Context, param: TyperArgument, incomplete: str) -> list:
        return [
            _click_completion.CompletionItem(idea_id, help=help_)
            for idea_id, help_ in _complete_ids(ctx, incomplete)
        ]


class _Command(TyperCommand):
    """A command whose help shows arguments as NAME and [NAME], without types or braces."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        for param in self.params:
            if (
                isinstance(param, TyperArgument)
                and type(param.type) is _click_types.StringParamType
            ):
                param.type = _Text()

    def collect_usage_pieces(self, ctx: typer.Context) -> list[str]:
        pieces = [self.options_metavar] if self.options_metavar else []
        for param in self.get_params(ctx):
            if not isinstance(param, TyperArgument):
                pieces.extend(param.get_usage_pieces(ctx))
                continue
            name = param.make_metavar(ctx)
            if not param.required and not name.startswith("["):
                name = f"[{name}]"
            pieces.append(name)
        return pieces


class _App(typer.Typer):
    def command(self, *args, **kwargs):
        kwargs.setdefault("cls", _Command)
        return super().command(*args, **kwargs)


app = _App(
    help="Capture and grow pet-project ideas.\n\n"
    + LIFECYCLE_HELP
    + "\n\n[bold]Tab completion[/] (commands and idea ids): pet --install-completion, "
    "then open a new shell.\n\n"
    "Run pet on its own in a terminal to open the full-screen view (same as pet ui).",
    rich_markup_mode="rich",
)
console = Console()
err = Console(stderr=True)

STATUS_STYLE = {
    Status.SEED: "green",
    Status.SKETCH: "cyan",
    Status.SPEC: "blue",
    Status.BUILDING: "magenta",
    Status.SHIPPED: "bold yellow",
    Status.SHELVED: "dim",
}


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    home: Annotated[
        str | None,
        typer.Option(
            "--home", metavar="PATH", help="Data directory to use (overrides $METAPET_HOME)."
        ),
    ] = None,
) -> None:
    ctx.obj = paths.resolve(home)
    if ctx.invoked_subcommand is not None or ctx.resilient_parsing:
        return
    if _interactive(False):
        _run_ui(ctx)
        return
    help_text = ctx.get_help()  # rich help prints itself and returns ""
    if help_text:
        typer.echo(help_text)
    raise typer.Exit(0)


# -- helpers -----------------------------------------------------------------


def _store(ctx: typer.Context, *, must_exist: bool = True) -> Store:
    store = Store(ctx.obj)
    if must_exist and not ctx.obj.exists:
        _fail(
            f"No idea store at [bold]{ctx.obj.path}[/] (from {ctx.obj.source}).\n"
            "Run [bold]pet init[/] first."
        )
    return store


def _fail(message: str) -> NoReturn:
    err.print(f"[red]error:[/] {message}", soft_wrap=True, highlight=False)
    raise typer.Exit(1)


def _warn_broken(broken: list[BrokenFile]) -> None:
    """One line on stderr naming the idea files that could not be read."""
    if not broken:
        return
    count = len(broken)
    files = ", ".join(b.path.name for b in broken)
    what = "1 idea file" if count == 1 else f"{count} idea files"
    err.print(
        f"[yellow]warning:[/] {what} could not be read (pet check shows why): {escape(files)}",
        soft_wrap=True,
    )


def _find(store: Store, query: str) -> Idea:
    return _lookup(store.find, query)


def _lookup(find: Callable[[str], T], query: str) -> T:
    try:
        return find(query)
    except IdeaLookupError as exc:
        if exc.candidates:
            ids = "\n".join(
                f"  • {escape(i.id)}  [dim]{escape(i.title)}[/]" for i in exc.candidates
            )
            _fail(f"{escape(str(exc))}; be more specific:\n{ids}")
        _fail(escape(str(exc)))


def _schema(ctx: typer.Context) -> Schema:
    try:
        return schema.load(ctx.obj)
    except SchemaError as exc:
        _fail(escape(str(exc)))


def _interactive(no_input: bool) -> bool:
    """Whether questions can be asked: not turned off, and both ends are a terminal."""
    return not no_input and sys.stdin.isatty() and sys.stdout.isatty()


def _prompter() -> Prompter:
    from metapet.questionary_prompter import QuestionaryPrompter

    return QuestionaryPrompter(console)


def _session(store: Store, idea_schema: Schema) -> wizard.Session:
    return wizard.Session(
        idea_schema,
        _prompter(),
        store.save,
        store.all_tags(),
        exists=store.exists,
        same_title=store.same_title,
    )


@contextmanager
def _stoppable(created: Callable[[], bool] = lambda: True) -> Iterator[None]:
    """Turn Ctrl-C or Ctrl-D during questions into a short message and exit code 130.

    `created` tells whether an idea exists yet, and so whether anything was saved.
    """
    try:
        yield
    except (KeyboardInterrupt, EOFError):
        if created():
            err.print("Stopped. Answers so far are saved.")
        else:
            err.print("Cancelled. Nothing was saved.")
        raise typer.Exit(130) from None


def _field(idea_schema: Schema, name: str) -> schema.Field:
    try:
        return idea_schema.field(name)
    except KeyError:
        known = ", ".join(f.key for f in idea_schema.all_fields())
        _fail(f"unknown field '{escape(name)}'; known fields: {known}")


def _complete_ids(ctx: click.Context, incomplete: str) -> list[tuple[str, str]]:
    """Shell completion for idea ids; completion must never fail loudly."""
    try:
        home = paths.resolve(ctx.find_root().params.get("home"))
        ideas = Store(home).all()
    except Exception:
        return []
    # Ids that start with the typed text; if there are none, ideas whose id or title
    # contains it (bash and fish show these; zsh may hide what does not start with it).
    typed = incomplete.casefold()
    matches = [i for i in ideas if i.id.startswith(typed)] or [
        i for i in ideas if typed in i.id or typed in i.title.casefold()
    ]
    return [
        (idea.id, _cut(" ".join(idea.title.split()), 50))
        for idea in sorted(matches, key=lambda i: i.id)
    ]


HEADINGS_NOTE = "## headings inside a field were changed to ###"
TITLE_HELP = "Short name for the idea, a few words (the id is made from it)."

Verbose = Annotated[
    bool, typer.Option("--verbose", "-v", help="Also print the path of the idea file.")
]

IdOption = Annotated[
    str | None,
    typer.Option(
        "--id",
        metavar="ID",
        help="Use this id instead of one made from the title (lowercase letters, digits and "
        "hyphens).",
    ),
]


class SortKey(StrEnum):
    CREATED = "created"
    EXCITEMENT = "excitement"
    IMPACT = "impact"
    SCORE = "score"
    TITLE = "title"


NoInput = Annotated[
    bool, typer.Option("--no-input", help="Never ask questions; use only the values given.")
]

IdArg = Annotated[
    str,
    typer.Argument(
        metavar="ID",
        help="Idea id; any unique prefix or fragment of the id or title works.",
        click_type=_IdText(),
    ),
]


def _status(status: Status) -> str:
    return f"[{STATUS_STYLE[status]}]{status.value}[/]"


TITLE_MIN = 16
TAGS_MAX = 20
COLUMN_GAP = 2
# Columns left out, in this order, when the table is wider than the terminal.
DROP_ORDER = ("created", "effort", "imp", "tags", "exc")


@dataclass
class _Column:
    name: str
    cells: list[Text]
    justify: Literal["left", "right"] = "left"
    style: str = ""
    cap: int | None = None

    def natural(self) -> int:
        """The width it needs for its longest cell, within its cap; title counts as TITLE_MIN."""
        if self.name == "title":
            return TITLE_MIN
        width = max([len(self.name), *(cell.cell_len for cell in self.cells)])
        return min(width, self.cap) if self.cap else width


def _idea_columns(
    ideas: list[Idea], extra: dict[str, list[str]] | None, created: bool
) -> list[_Column]:
    def column(name: str, values: list[str], **kwargs) -> _Column:
        return _Column(name, [Text(value) for value in values], **kwargs)

    columns = [
        column("id", [i.id for i in ideas], style="bold", cap=ids.ID_MAX),
        column("title", [i.title for i in ideas]),
        _Column("status", [Text(i.status.value, style=STATUS_STYLE[i.status]) for i in ideas]),
        *(column(name, values, justify="right") for name, values in (extra or {}).items()),
        column("exc", [str(i.excitement or "") for i in ideas], justify="right"),
        column("tags", [", ".join(i.tags) for i in ideas], style="dim", cap=TAGS_MAX),
        column("imp", [str(i.impact or "") for i in ideas], justify="right"),
        column("effort", [i.effort.value if i.effort else "" for i in ideas]),
    ]
    if created:
        columns.append(column("created", [i.created.isoformat() for i in ideas], style="dim"))
    return columns


def _total(columns: list[_Column]) -> int:
    return sum(c.natural() for c in columns) + COLUMN_GAP * (len(columns) - 1)


def _fit_columns(columns: list[_Column], width: int) -> list[_Column]:
    """Leave out low-priority columns until the rest fit in width."""
    kept = list(columns)
    for name in DROP_ORDER:
        if _total(kept) <= width:
            break
        kept = [c for c in kept if c.name != name]
    return kept


def _ideas_table(
    ideas: list[Idea],
    extra: dict[str, list[str]] | None = None,
    *,
    created: bool = True,
    width: int | None = None,
) -> Table:
    """A table of ideas with one line per idea, fitted to the terminal width."""
    width = width or console.width
    columns = _fit_columns(_idea_columns(ideas, extra, created), width)
    table = Table(box=None, header_style="bold", pad_edge=False)
    for col in columns:
        size = col.natural()
        if col.name == "title":
            longest = max([len(col.name), *(cell.cell_len for cell in col.cells)])
            size = min(longest, max(TITLE_MIN, width - (_total(columns) - TITLE_MIN)))
        table.add_column(
            col.name,
            justify=col.justify,
            style=col.style,
            no_wrap=True,
            overflow="ellipsis",
            width=size,
        )
    for row in range(len(ideas)):
        table.add_row(*(col.cells[row] for col in columns))
    return table


def _print_ideas(
    ideas: list[Idea], extra: dict[str, list[str]] | None = None, *, created: bool = True
) -> None:
    """A table in a terminal; otherwise one tab-separated line per idea, for scripts."""
    if console.is_terminal:
        console.print(_ideas_table(ideas, extra, created=created))
        return
    for row, idea in enumerate(ideas):
        values = [
            idea.id,
            idea.status.value,
            idea.title,
            ",".join(idea.tags),
            str(idea.excitement or ""),
            str(idea.impact or ""),
            idea.effort.value if idea.effort else "",
            idea.created.isoformat(),
            *(values[row] for values in (extra or {}).values()),
        ]
        typer.echo("\t".join(" ".join(value.split()) for value in values))


def _stars(value: int) -> str:
    return f"{'★' * value}{'☆' * (5 - value)}"


def _print_idea(idea: Idea, idea_schema: Schema) -> None:
    console.print(Text(idea.title, style="bold"))
    first = f"{escape(idea.id)} · {_status(idea.status)} · [dim]created {idea.created}[/]"
    if idea.updated:
        first += f" [dim]· updated {idea.updated}[/]"
    if idea.reviewed:
        first += f" [dim]· reviewed {idea.reviewed}[/]"
    meta = [first]
    details = []
    if idea.excitement:
        details.append(f"excitement {_stars(idea.excitement)}")
    if idea.impact:
        details.append(f"impact {_stars(idea.impact)}")
    if idea.effort:
        details.append(f"effort {idea.effort.value}")
    if idea.tags:
        details.append("tags " + escape(", ".join(idea.tags)))
    if details:
        meta.append("  ·  ".join(details))
    if idea.repo:
        meta.append(f"repo {escape(idea.repo)}")
    if idea.related:
        meta.append("related " + escape(", ".join(idea.related)))
    if idea.shelved_reason:
        meta.append(f"[dim]shelved: {escape(idea.shelved_reason)}[/]")
    console.print(Panel("\n".join(meta), expand=False))
    body, empty = views.visible_body(idea, idea_schema)
    if body.strip():
        console.print(Markdown(body))
    if empty:
        console.print(Text(views.empty_line(empty), style="dim"))


def _cut(text: str, width: int) -> str:
    """text shortened to width characters, ending with … when cut."""
    return text if len(text) <= width else text[: width - 1].rstrip() + "…"


def _print_added(idea: Idea, verbose: bool) -> None:
    line = f"[green]+[/] {escape(idea.id)}  [dim]{escape(_cut(idea.title, 50))}[/]"
    if verbose:
        line += f"  [dim]{escape(str(idea.path))}[/]"
    console.print(line, soft_wrap=True, highlight=False)


def _print_moved(idea: Idea, old: Status, new: Status, verbose: bool) -> None:
    line = f"{escape(idea.id)}: {_status(old)} → {_status(new)}"
    lifecycle = stages.LIFECYCLE
    if old in lifecycle and new in lifecycle and lifecycle.index(new) < lifecycle.index(old):
        line += " (moved back)"
    if verbose:
        line += f"  [dim]{escape(str(idea.path))}[/]"
    console.print(line, soft_wrap=True, highlight=False)


# -- setup -------------------------------------------------------------------


@app.command()
def init(
    ctx: typer.Context,
    local: Annotated[
        bool, typer.Option("--local", help="Store ideas in ./data inside this checkout.")
    ] = False,
    git: Annotated[
        bool, typer.Option("--git", help="Make the store a git repo, for `pet sync` backups.")
    ] = False,
    remote: Annotated[
        str | None,
        typer.Option("--remote", metavar="URL", help="Git remote URL for backups (implies --git)."),
    ] = None,
) -> None:
    """Create the idea store."""
    home: paths.DataHome = ctx.obj
    if local:
        portable = paths.portable_dir()
        if portable is None:
            _fail("--local only works when running from a source checkout.")
        home = paths.DataHome(portable, "portable ./data in checkout")
        ctx.obj = home
    store = Store(home)
    already = home.exists
    store.init()
    verb = "Using existing" if already else "Created"
    console.print(
        f"{verb} idea store at [bold]{home.path}[/] [dim]({home.source})[/]", soft_wrap=True
    )
    if git or remote:
        try:
            sync.init_repo(home.path, remote)
        except sync.SyncError as exc:
            _fail(str(exc))
        target = f" → {remote}" if remote else ""
        console.print(f"Git backup enabled{target}; run [bold]pet sync[/] to back up.")


@app.command()
def where(ctx: typer.Context) -> None:
    """Show which data directory is in use, and why."""
    home: paths.DataHome = ctx.obj
    state = "" if home.exists else "  [yellow](not initialized — run `pet init`)[/]"
    console.print(f"{home.path}  [dim]← {home.source}[/]{state}", soft_wrap=True)


# -- capture -----------------------------------------------------------------


@app.command()
def add(
    ctx: typer.Context,
    title: Annotated[str, typer.Argument(metavar="TITLE", help=TITLE_HELP)],
    tag: Annotated[
        list[str] | None, typer.Option("--tag", "-t", metavar="TAG", help="Tag (repeatable).")
    ] = None,
    note: Annotated[
        str | None, typer.Option("--note", "-m", metavar="TEXT", help="One-line description.")
    ] = None,
    interactive: Annotated[
        bool,
        typer.Option(
            "--interactive", "-i", help="Then ask the other seed questions (in a terminal only)."
        ),
    ] = False,
    id_: IdOption = None,
    verbose: Verbose = False,
) -> None:
    """Capture a seed instantly, without opening an editor.

    Grow it later with pet promote ID (see pet promote --help for the stages).
    """
    store = _store(ctx)
    idea_schema = _schema(ctx) if interactive else None
    try:
        title, note = _shorten_long_title(title, note, id_ is not None)
    except ValueError:
        _fail('a title is required: pet add "TITLE"')
    same = store.same_title(title)
    try:
        idea = store.create(
            title, id=id_, tags=list(tag or []), body=fields.summary_text(note or "")
        )
    except ValueError as exc:
        _fail(escape(str(exc)))
    _note_same(same)
    _print_added(idea, verbose)
    if idea_schema is None:
        return
    if not _interactive(False):
        err.print("note: not a terminal, skipping questions")
        return
    supplied = {"title"}
    if tag:
        supplied.add("tags")
    if note:
        supplied.add(_summary_key(idea_schema))
    session = _session(store, idea_schema)
    with _stoppable():
        wizard.new_idea(session, idea, supplied)
        wizard.continue_stages(session, idea)


def _summary_key(idea_schema: Schema) -> str:
    return next(
        (f.key for f in idea_schema.all_fields() if f.storage == Storage.SUMMARY), "summary"
    )


@app.command()
def new(
    ctx: typer.Context,
    title: Annotated[str | None, typer.Argument(metavar="[TITLE]", help=TITLE_HELP)] = None,
    summary: Annotated[
        str | None,
        typer.Option("--summary", "-m", metavar="TEXT", help="Describe it in one sentence."),
    ] = None,
    tag: Annotated[
        list[str] | None, typer.Option("--tag", "-t", metavar="TAG", help="Tag (repeatable).")
    ] = None,
    excitement: Annotated[
        int | None,
        typer.Option(
            "--excitement", "-x", min=1, max=5, metavar="1-5", help="How excited you are."
        ),
    ] = None,
    set_: Annotated[
        list[str] | None,
        typer.Option(
            "--set",
            "-s",
            metavar="KEY=VALUE",
            help="Any other field, e.g. --set effort=M (repeatable; see pet set --help).",
        ),
    ] = None,
    id_: IdOption = None,
    no_input: NoInput = False,
    verbose: Verbose = False,
) -> None:
    """Capture an idea with its seed fields.

    In a terminal, asks for the title if it is not given, then for the seed fields you did not
    pass as options, and offers to go on to the next stages. Every question can be skipped.
    Fields of later stages can be filled right away with --set.
    """
    store = _store(ctx)
    idea_schema = _schema(ctx)
    if id_ is not None:
        try:
            id_ = store.check_new_id(id_)
        except ValueError as exc:
            _fail(escape(str(exc)))
    summary_key = _summary_key(idea_schema)
    flagged = {
        summary_key: summary,
        "tags": ",".join(fields.normalize_tags(tag, store.all_tags())) if tag else None,
        "excitement": str(excitement) if excitement is not None else None,
    }
    try:
        extra = fields.parse_changes(list(set_ or []))
        clashes = [
            c.key
            for c in extra
            if c.key.lower().replace("-", "_")
            in {"title", *(k for k, v in flagged.items() if v is not None)}
        ]
        if clashes:
            raise ValueError(f"'{clashes[0]}' is given both as a flag and with --set")
        # Check every value before asking anything.
        fields.apply_changes(Idea(id="x", title="x"), idea_schema, _changes(flagged) + extra)
    except ValueError as exc:
        _fail(escape(str(exc)))
    session = _session(store, idea_schema) if _interactive(no_input) else None
    if session is None:
        if not title or not title.strip():
            _fail('a title is required: pet new "TITLE"')
        title, flagged[summary_key] = _shorten_long_title(title, summary, id_ is not None)
        idea_id = id_ or store.unique_id(title)
        _note_same(store.same_title(title))
    else:
        with _stoppable(created=lambda: False):
            name = wizard.ask_name(session, title if title and title.strip() else None, id_)
        if name is None:
            return
        title, idea_id = name.title, name.id
        if name.extra_summary:
            flagged[summary_key] = _join_summary(summary, name.extra_summary)
    idea = Idea(id=idea_id, title=clean_title(title))
    fields.apply_changes(idea, idea_schema, _changes(flagged) + extra, store.all_tags())
    idea.updated = None  # just created
    store.save(idea)
    _print_added(idea, verbose)
    if session is None:
        return
    supplied = {"title", *(key for key, value in flagged.items() if value is not None)}
    supplied |= {c.key.lower().replace("-", "_") for c in extra}
    with _stoppable():
        wizard.new_idea(session, idea, supplied)
        wizard.continue_stages(session, idea)


def _note_same(same: list[Idea]) -> None:
    if same:
        verb = "has" if len(same) == 1 else "have"
        listed = ", ".join(i.id for i in same)
        err.print(f"note: {escape(listed)} {verb} the same name", soft_wrap=True, highlight=False)


def _changes(flagged: dict[str, str | None]) -> list[fields.Change]:
    return [fields.Change("set", key, value) for key, value in flagged.items() if value is not None]


def _join_summary(summary: str | None, extra: str) -> str:
    """The summary with extra text added as another paragraph."""
    return f"{summary.strip()}\n\n{extra}" if summary and summary.strip() else extra


def _shorten_long_title(title: str, summary: str | None, keep: bool) -> tuple[str, str | None]:
    """Without questions, a long title becomes a short one and the summary keeps the text."""
    title = clean_title(title)
    if keep or not is_long_title(title, count_words=False):
        return title, summary
    short = short_title(title)
    err.print(
        f'note: the title was long; kept "{escape(short)}" as the title and the full text as '
        "the summary",
        soft_wrap=True,
    )
    return short, _join_summary(summary, title)


# -- browsing ----------------------------------------------------------------


@app.command("ls")
def list_ideas(
    ctx: typer.Context,
    status: Annotated[
        list[Status] | None,
        typer.Option("--status", "-s", help="Only ideas at this status (repeatable)."),
    ] = None,
    tag: Annotated[
        list[str] | None,
        typer.Option(
            "--tag",
            "-t",
            metavar="TAG",
            help="Only ideas with this tag (repeat for any of several).",
        ),
    ] = None,
    sort: Annotated[
        SortKey,
        typer.Option(help="Sort order (newest, highest or A-Z first)."),
    ] = SortKey.CREATED,
    all_: Annotated[
        bool, typer.Option("--all", "-a", help="Include shipped and shelved ideas.")
    ] = False,
) -> None:
    """List ideas.

    Shipped and shelved ideas are hidden unless you pass --all or filter by --status.
    """
    everything, broken = _store(ctx).scan()
    ideas = everything
    if tag:
        wanted = {t.casefold() for t in tag}
        ideas = [i for i in ideas if wanted & {t.casefold() for t in i.tags}]
    hidden = 0
    if status:
        ideas = [i for i in ideas if i.status in status]
    elif not all_:
        hidden = sum(1 for i in ideas if i.status.terminal)
        ideas = [i for i in ideas if not i.status.terminal]
    keys = {
        SortKey.CREATED: lambda i: (i.created, i.id),
        SortKey.EXCITEMENT: lambda i: (i.excitement or 0, i.created),
        SortKey.IMPACT: lambda i: (i.impact or 0, i.created),
        SortKey.SCORE: lambda i: (scoring.score(i), i.created),
        SortKey.TITLE: lambda i: i.title.lower(),
    }
    ideas.sort(key=keys[sort], reverse=sort != SortKey.TITLE)
    if not everything:
        console.print('No ideas yet. Capture one with pet add "..."', markup=False)
    elif not ideas:
        console.print("No ideas match these filters." if status or tag else "No live ideas.")
    else:
        extra = (
            {"score": [f"{scoring.score(i):.2f}" for i in ideas]} if sort == SortKey.SCORE else None
        )
        _print_ideas(ideas, extra)
    if hidden and console.is_terminal:
        what = "idea" if hidden == 1 else "ideas"
        console.print(f"[dim]{hidden} shipped or shelved {what} hidden (use -a)[/]")
    _warn_broken(broken)


@app.command()
def show(ctx: typer.Context, idea_id: IdArg) -> None:
    """Show one idea."""
    _print_idea(_find(_store(ctx), idea_id), _schema(ctx))


@app.command()
def edit(
    ctx: typer.Context,
    idea_id: IdArg,
    field_name: Annotated[
        str | None,
        typer.Option(
            "--field", "-f", metavar="FIELD", help="Edit only this field (key or heading)."
        ),
    ] = None,
) -> None:
    """Open an idea in $EDITOR, or just one of its fields with --field."""
    store = _store(ctx)
    if field_name is None:
        # Files that cannot be read are opened too, so they can be fixed.
        _edit_file(_lookup(store.find_path, idea_id))
        return
    idea = _find(store, idea_id)
    idea_schema = _schema(ctx)
    field = _field(idea_schema, field_name)
    if field.storage == Storage.FRONTMATTER:
        _fail(f"'{field.key}' is stored in the frontmatter; use pet set ID {field.key}=VALUE")
    current = fields.raw(idea, field)
    edited = _editor(text=current, extension=".md")
    if edited is not None and sections.is_empty(current):
        edited = sections.strip_comments(edited)
    if edited is None or edited.strip() == current.strip() or not edited.strip():
        console.print(f"{escape(idea.id)}: no change")
        return
    demoted = fields.put_text(idea, field, edited, idea_schema.section_order)
    idea.touch()
    store.save(idea)
    console.print(f"{escape(idea.id)}: {escape(field.label)} updated")
    if demoted:
        err.print(f"note: {HEADINGS_NOTE}", markup=False)


def _editor(**kwargs) -> str | None:
    """click.edit, with a failing or missing editor reported in one line."""
    try:
        return click.edit(**kwargs)
    except click.ClickException as exc:
        _fail(f"{escape(exc.format_message())} (set $EDITOR or $VISUAL)")


def _edit_file(path: Path) -> None:
    """Open an idea file in the editor, then check that it can still be read."""
    while True:
        _editor(filename=str(path))
        try:
            idea = Idea.load(path)
        except IdeaError as exc:
            problem = f"{escape(path.name)} cannot be read: {escape(str(exc))}"
            hint = f"Fix it with pet edit {escape(path.stem)}; pet check lists the problems."
            if _interactive(False):
                err.print(f"[red]error:[/] {problem}", soft_wrap=True)
                if click.confirm("Open it again to fix it?", default=True):
                    continue
                err.print(hint, soft_wrap=True)
                raise typer.Exit(1) from None
            _fail(f"{problem}\n{hint}")
        if idea.id != path.stem:
            err.print(
                f"[yellow]warning:[/] the id in {escape(path.name)} is '{escape(idea.id)}', "
                "which does not match the file name; use pet rename to change an id",
                soft_wrap=True,
            )
        return


@app.command(
    "set",
    context_settings={"ignore_unknown_options": True},
    help="Change fields without any questions.\n\n"
    "Each CHANGE is key=value, +tag or -tag, for example: pet set ID excitement=4 effort=S "
    "+cli -old. Keys are the field keys shown by pet stages; a field's heading works too "
    '("MVP scope=..."). An empty value clears a field (summary=). tags=a,b replaces all '
    "tags. For a list field, repeat the key, one item each: features=search "
    "features=export. For a dated list (notes, log), each value is added as a new dated "
    "item and the old items are kept; notes= clears the list. If a -tag is taken as an "
    "option, put -- before the changes.",
)
def set_(
    ctx: typer.Context,
    idea_id: IdArg,
    changes: Annotated[
        list[str],
        typer.Argument(
            metavar="CHANGE...",
            help="key=value, +tag or -tag; see above.",
            show_default=False,
        ),
    ],
) -> None:
    store = _store(ctx)
    idea = _find(store, idea_id)
    try:
        done = fields.apply_changes(
            idea, _schema(ctx), fields.parse_changes(changes), store.all_tags()
        )
    except ValueError as exc:
        _fail(escape(str(exc)))
    if not done:
        console.print(f"{escape(idea.id)}: no change")
        return
    store.save(idea)
    lines = [f"{idea.id}: {done[0]}", *(f"  {change}" for change in done[1:])]
    console.print("\n".join(lines), soft_wrap=True, markup=False, highlight=False)


@app.command()
def note(
    ctx: typer.Context,
    idea_id: IdArg,
    text: Annotated[
        str, typer.Argument(metavar="TEXT", help="The note; it is dated and added to Notes.")
    ],
) -> None:
    """Add a dated line to an idea's Notes section."""
    store = _store(ctx)
    idea = _find(store, idea_id)
    try:
        fields.add_note(idea, _schema(ctx), text)
    except ValueError as exc:
        _fail(escape(str(exc)))
    store.save(idea)
    console.print(f"{escape(idea.id)}: noted")


@app.command()
def rename(
    ctx: typer.Context,
    idea_id: IdArg,
    new_id: Annotated[
        str | None,
        typer.Argument(
            metavar="NEW_ID",
            help="The new id (lowercase letters, digits and hyphens). Leave it out to make one "
            "from the title.",
        ),
    ] = None,
) -> None:
    """Change an idea's id and file name.

    Other ideas that list the old id under related are updated. After changing the title
    with pet set ID title=..., run pet rename ID to make the id match it.
    """
    store = _store(ctx)
    idea = _find(store, idea_id)
    old_id = idea.id
    if new_id is None:
        suggested = ids.suggest(idea.title).id
        new_id = old_id if suggested == old_id else store.unique(suggested)
    if new_id.strip().lower() == old_id:
        console.print(f"{escape(old_id)}: no change")
        return
    try:
        changed = store.rename(idea, new_id)
    except ValueError as exc:
        _fail(escape(str(exc)))
    console.print(f"{escape(old_id)} → {escape(idea.id)}")
    if changed:
        console.print(f"updated related in: {escape(', '.join(i.id for i in changed))}")


@app.command("rm")
def rm(
    ctx: typer.Context,
    idea_id: IdArg,
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Delete without asking.")] = False,
) -> None:
    """Delete an idea.

    Other ideas that list it under related are updated. In a terminal, asks first; otherwise
    pass --yes. If the store is a git repository (pet init --git), the file stays in its
    history.
    """
    store = _store(ctx)
    idea = _find(store, idea_id)
    console.print(f"{escape(idea.id)}  [dim]{escape(idea.title)}[/]", soft_wrap=True)
    if not yes:
        if not _interactive(False):
            _fail("pass --yes to delete without asking")
        if not click.confirm("Delete this idea? This cannot be undone.", default=False):
            console.print("Not deleted.")
            return
    changed = store.delete(idea)
    console.print(f"[red]-[/] {escape(idea.id)}")
    if changed:
        console.print(f"updated related in: {escape(', '.join(i.id for i in changed))}")


app.command("delete", hidden=True)(rm)


# -- lifecycle ---------------------------------------------------------------


@app.command(
    help="Move an idea to its next stage, adding that stage's sections.\n\n"
    "Moves one stage forward by default. --to can skip stages (each skipped stage still adds "
    "its sections) or move back (adds and removes nothing). A shelved or shipped idea "
    "returns with --to STAGE; it gets the sections of every stage up to STAGE, and an empty "
    "Retro section is removed.\n\n"
    "In a terminal, a forward move offers to fill expected fields that are still empty, "
    "shows the idea, then asks the questions of each new stage that are still empty; every "
    "question can be skipped, and answered ones are changed with pet refine. "
    "With --no-input, or outside a terminal, promote only warns about empty expected fields "
    "and moves the idea anyway.\n\n" + LIFECYCLE_HELP
)
def promote(
    ctx: typer.Context,
    idea_id: IdArg,
    to: Annotated[
        Status | None, typer.Option("--to", help="Target status (default: the next one).")
    ] = None,
    no_input: NoInput = False,
    verbose: Verbose = False,
) -> None:
    store = _store(ctx)
    idea_schema = _schema(ctx)
    idea = _find(store, idea_id)
    target = to or idea.status.next()
    if target is None:
        _fail(f"{escape(idea.id)} is {idea.status.value}; pass --to to move it elsewhere.")
    if target == Status.SHELVED:
        _fail("use `pet shelve ID REASON` to shelve an idea.")
    old = idea.status
    forward = bool(stages.statuses_between(old, target))
    if forward and old in stages.LIFECYCLE and _interactive(no_input):
        with _stoppable():
            if not wizard.promote(_session(store, idea_schema), idea, target):
                console.print("Not promoted.")
                return
        _print_moved(idea, old, target, verbose)
        return
    gaps = stages.gaps(idea, idea_schema, stages.before(target)) if forward else []
    stages.promote(idea, target, idea_schema)
    store.save(idea)
    _print_moved(idea, old, target, verbose)
    if gaps:
        labels = escape(_label_keys(gaps))
        err.print(
            f"[yellow]warning:[/] still empty: {labels} "
            f"(fill them with pet refine {escape(idea.id)})",
            soft_wrap=True,
        )


@app.command()
def refine(
    ctx: typer.Context,
    idea_id: IdArg,
    field_name: Annotated[
        str | None,
        typer.Argument(metavar="FIELD", help="Only this field (key or heading)."),
    ] = None,
) -> None:
    """Answer an idea's questions again, or fill the ones you skipped.

    Without FIELD, pick fields from a list (✓ answered, · empty, * expected) until you
    choose Done. Only fields of the idea's stage and the stages before it are offered. The
    stage does not change. Needs a terminal.
    """
    store = _store(ctx)
    idea_schema = _schema(ctx)
    idea = _find(store, idea_id)
    field = None
    if field_name is not None:
        field = _field(idea_schema, field_name)
        if field.key not in {f.key for f in idea_schema.fields_upto(idea.status)}:
            _fail(
                f"'{field.key}' belongs to the {field.stage} stage; "
                f"use pet set ID {field.key}=... or promote first"
            )
    if not _interactive(False):
        _fail("refine needs a terminal; use pet set ID KEY=VALUE or pet edit ID --field KEY")
    with _stoppable():
        wizard.refine(_session(store, idea_schema), idea, field)


@app.command()
def shelve(
    ctx: typer.Context,
    idea_id: IdArg,
    reason: Annotated[str, typer.Argument(metavar="REASON", help="Why you're putting it aside.")],
) -> None:
    """Shelve an idea, keeping the reason for future you.

    Shelved ideas are hidden from ls and next (see them with ls -a) and gain a Retro
    section. The reason is also added to Notes, with the date. Bring one back with: pet
    promote ID --to STAGE.
    """
    store = _store(ctx)
    idea = _find(store, idea_id)
    try:
        previous = stages.shelve(idea, reason, _schema(ctx))
    except ValueError as exc:
        _fail(escape(str(exc)))
    store.save(idea)
    if previous is not None:
        console.print(
            f"{escape(idea.id)} was already shelved ({escape(previous)}); reason replaced",
            soft_wrap=True,
        )
    else:
        console.print(
            f"{escape(idea.id)}: {_status(Status.SHELVED)}  "
            f"[dim]{escape(idea.shelved_reason or '')}[/]",
            soft_wrap=True,
        )


@app.command(
    help="Go through live ideas you have not looked at for a while.\n\n"
    "An idea counts as looked at when it was created, changed or reviewed. In a terminal, "
    "shows each idea, oldest first, and asks what to do with it: promote, refine, add a note, "
    "set excitement, shelve, skip or quit. Skip, or any action that changes the idea, marks "
    "it as reviewed; if nothing changed, the same question is asked again. "
    "Outside a terminal, or with --no-input, only lists the ideas."
)
def review(
    ctx: typer.Context,
    days: Annotated[
        int,
        typer.Option(
            "--days", "-d", min=0, metavar="N", help="Ideas not looked at for this many days."
        ),
    ] = 14,
    no_input: NoInput = False,
) -> None:
    store = _store(ctx)
    idea_schema = _schema(ctx)
    all_ideas, broken = store.scan()
    ideas = review_.due(all_ideas, days)
    if not ideas:
        console.print(f"Nothing to review. Everything was looked at in the last {days} days.")
        _warn_broken(broken)
        return
    if not _interactive(no_input):
        seen = [review_.last_seen(idea).isoformat() for idea in ideas]
        _print_ideas(ideas, {"last seen": seen}, created=False)
        err.print("Run pet review in a terminal to go through them.")
        _warn_broken(broken)
        return
    result = review_.run(_session(store, idea_schema), ideas)
    console.print(f"Reviewed {result.handled}, {result.remaining} left.")
    _warn_broken(broken)
    if result.stopped:
        err.print("Stopped. Answers so far are saved.")
        raise typer.Exit(130)


@app.command()
def ui(ctx: typer.Context) -> None:
    """Browse and change ideas in a full-screen view.

    Keys: / filter, q quit, a add, p promote, r refine, n note, s shelve, e edit, x excitement.
    Needs a terminal.
    """
    if not _interactive(False):
        _fail("pet ui needs a terminal; use pet ls, pet show and pet set instead")
    _run_ui(ctx)


def _run_ui(ctx: typer.Context) -> None:
    store = _store(ctx)
    idea_schema = _schema(ctx)
    from metapet.tui import PetApp

    PetApp(store, idea_schema, prompter=_prompter).run()


# -- discovery ---------------------------------------------------------------


@app.command()
def search(
    ctx: typer.Context,
    query: Annotated[
        list[str],
        typer.Argument(
            metavar="QUERY...",
            help="Words that must all appear (in the id, title, tags or text); also "
            "status:NAME and tag:NAME.",
            show_default=False,
        ),
    ],
    all_: Annotated[
        bool, typer.Option("--all", "-a", help="Include shipped and shelved ideas.")
    ] = False,
) -> None:
    """Find ideas by words, status:NAME and tag:NAME, like the filter in pet ui."""
    text = " ".join(query).strip()
    if not text:
        _fail("give words to search for")
    unknown = views.parse_query(text).unknown_statuses
    if unknown:
        names = ", ".join(status.value for status in Status)
        _fail(f"unknown status: {escape(', '.join(unknown))} ({names})")
    ideas, broken = _store(ctx).scan()
    hits = views.filter_ideas(ideas, text, everything=all_)
    if hits:
        _print_ideas(hits)
    else:
        message = f"No ideas match '{escape(text)}'."
        asked_status = any(t.lower().startswith("status:") for t in text.split())
        if not all_ and not asked_status and views.filter_ideas(ideas, text, everything=True):
            message += " (shipped and shelved ideas are hidden; add -a)"
        console.print(f"[dim]{message}[/]")
    _warn_broken(broken)


app.command("list", hidden=True)(list_ideas)
app.command("find", hidden=True)(search)


@app.command("next")
def next_(
    ctx: typer.Context,
    count: Annotated[
        int, typer.Option("--count", "-n", min=1, metavar="N", help="How many to suggest.")
    ] = 3,
) -> None:
    """Suggest what to work on next.

    Ranks by (excitement + impact) / effort weight (S=1, M=2, L=4, XL=8; missing values count
    as 3, 3 and M), plus up to 0.75 for later stages and up to 0.5 for ideas that have waited
    six months.
    """
    all_ideas, broken = _store(ctx).scan()
    ranked = scoring.rank(all_ideas)[:count]
    if not ranked:
        console.print('[dim]No live ideas. Capture one with[/] pet add "..."')
    else:
        ideas = [idea for idea, _ in ranked]
        _print_ideas(ideas, {"score": [f"{value:.2f}" for _, value in ranked]})
    _warn_broken(broken)


@app.command("random")
def random_(ctx: typer.Context) -> None:
    """Resurface a random seed or sketch you may have forgotten."""
    pool = [i for i in _store(ctx).all() if i.status in (Status.SEED, Status.SKETCH)]
    if not pool:
        console.print("[dim]No seeds or sketches to resurface.[/]")
        return
    _print_idea(random.choice(pool), _schema(ctx))


@app.command()
def stats(ctx: typer.Context) -> None:
    """Counts by status, tag and month."""
    ideas, broken = _store(ctx).scan()
    if not ideas:
        console.print("[dim]No ideas yet.[/]")
        _warn_broken(broken)
        return
    by_status = Counter(i.status for i in ideas)
    by_tag = Counter(t for i in ideas for t in {tag.casefold() for tag in i.tags})
    by_month = Counter(i.created.strftime("%Y-%m") for i in ideas)
    recent = _last_months(dt.date.today(), 6)

    live = sum(1 for i in ideas if not i.status.terminal)
    table = Table(title=f"{len(ideas)} ideas ({live} live)", box=None, show_header=False)
    table.add_column(style="bold")
    table.add_column()
    table.add_row(
        "status", "  ".join(f"{_status(s)} {by_status[s]}" for s in Status if by_status[s])
    )
    if by_tag:
        top = "  ".join(f"{escape(t)} {n}" for t, n in by_tag.most_common(10))
        table.add_row("top tags", top)
    months = "  ".join(f"{m} {by_month[m]}" for m in recent if by_month[m]) or "none"
    table.add_row("added (last 6 months)", months)
    console.print(table)
    _warn_broken(broken)


def _last_months(today: dt.date, count: int) -> list[str]:
    """The last `count` months up to today, oldest first, as YYYY-MM."""
    months = []
    for back in range(count - 1, -1, -1):
        year, index = divmod(today.year * 12 + today.month - 1 - back, 12)
        months.append(f"{year:04d}-{index + 1:02d}")
    return months


@app.command("stages")
def stages_(ctx: typer.Context) -> None:
    """Show the stages and their field keys, including changes from your stages.toml.

    Fields marked * are expected before moving on. Use these keys with pet set and pet refine.
    """
    idea_schema = _schema(ctx)
    console.print("\n".join(_stage_rows(idea_schema)), markup=False, highlight=False)


@app.command()
def check(ctx: typer.Context) -> None:
    """Validate every idea file and stages.toml, and list empty expected fields."""
    store = _store(ctx)
    ideas, broken = store.scan()
    mismatched = [i for i in ideas if i.path and i.path.stem != i.id]
    for bad in broken:
        if len(bad.problems) > 1:
            err.print(f"[red]✗[/] {escape(bad.path.name)}:")
            for problem in bad.problems:
                err.print(f"    {escape(problem)}", soft_wrap=True)
        else:
            err.print(f"[red]✗[/] {escape(bad.path.name)}: {escape(bad.error)}", soft_wrap=True)
    for idea in ideas:
        if len(idea.id) > ids.ID_MAX and idea.path:
            err.print(
                f"[yellow]![/] {escape(idea.path.name)}: id is longer than {ids.ID_MAX} "
                "characters; shorten it with pet rename",
                soft_wrap=True,
            )
    for idea in mismatched:
        err.print(
            f"[yellow]![/] {escape(idea.path.name)}: id is '{escape(idea.id)}' "
            "(rename the file to match, or run pet rename)"
        )
    try:
        idea_schema = schema.load(store.home)
    except SchemaError as exc:
        idea_schema = None
        err.print(f"[red]✗[/] {escape(str(exc))}", soft_wrap=True)
    if store.home.templates.is_dir():
        err.print(
            "[yellow]![/] templates/ is no longer used; stage fields now come from "
            "stages.toml (see README)"
        )
    if idea_schema is not None:
        for idea in ideas:
            body = sections.parse(idea.body)
            for f in idea_schema.section_fields():
                found = [sec for sec in body.sections if f.matches_heading(sec.heading)]
                if len(found) > 1 and idea.path:
                    err.print(
                        f"[yellow]![/] {escape(idea.path.name)}: {_count_word(len(found))} "
                        f"'{escape(f.label)}' sections; only the first is used",
                        soft_wrap=True,
                    )
        for idea in ideas:
            if idea.status.terminal:
                continue
            gaps = stages.gaps(idea, idea_schema, idea.status)
            if gaps:
                labels = escape(_label_keys(gaps))
                console.print(
                    f"[dim]· {escape(idea.id)} ({idea.status.value}): empty: {labels}[/]",
                    soft_wrap=True,
                )
    if broken or idea_schema is None:
        raise typer.Exit(1)
    console.print(f"[green]✓[/] {len(ideas)} idea{'' if len(ideas) == 1 else 's'} OK")


def _label_keys(found: list[schema.Field]) -> str:
    """`Rough solution (solution)`: the label people read and the key pet set takes."""
    return ", ".join(f"{f.label} ({f.key})" for f in found)


def _count_word(n: int) -> str:
    return {2: "two", 3: "three"}.get(n, str(n))


# -- backup & export ---------------------------------------------------------


@app.command("sync")
def sync_(
    ctx: typer.Context,
    message: Annotated[
        str | None, typer.Option("--message", "-m", metavar="TEXT", help="Commit message.")
    ] = None,
) -> None:
    """Back up the store: commit, pull --rebase, push (if it's a git repo)."""
    store = _store(ctx)
    try:
        steps = sync.sync(store.home.path, message)
    except sync.SyncError as exc:
        _fail(str(exc))
    for step in steps:
        console.print(f"[green]•[/] {step}")


@app.command("export")
def export_(
    ctx: typer.Context,
    md: Annotated[
        Path | None, typer.Option("--md", metavar="FILE", help="Write a Markdown index here.")
    ] = None,
    json_: Annotated[
        Path | None, typer.Option("--json", metavar="FILE", help="Write a JSON dump here.")
    ] = None,
) -> None:
    """Export all ideas as a Markdown index and/or JSON.

    Use - as FILE to write to standard output. Links in the Markdown index are relative to
    the directory of FILE.
    """
    if not md and not json_:
        _fail("pass --md FILE and/or --json FILE")
    for target in (md, json_):
        if target and str(target) != "-" and not target.parent.is_dir():
            _fail(f"directory {escape(str(target.parent))} does not exist")
    ideas = _store(ctx).all()
    for target, render in (
        (md, lambda: export.to_markdown(ideas, md.parent if str(md) != "-" else Path.cwd())),
        (json_, lambda: export.to_json(ideas)),
    ):
        if not target:
            continue
        if str(target) == "-":
            typer.echo(render(), nl=False)
            continue
        target.write_text(render(), encoding="utf-8")
        console.print(f"[green]✓[/] wrote {escape(str(target))}", soft_wrap=True, highlight=False)


def _one_line_paragraphs(text: str) -> str:
    """Help text with each paragraph on one line, so the terminal can wrap it evenly."""
    paragraphs = inspect.cleandoc(text).split("\n\n")
    return "\n\n".join(" ".join(paragraph.split()) for paragraph in paragraphs)


for _info in app.registered_commands:
    if _info.help is None and _info.callback is not None and _info.callback.__doc__:
        _info.help = _one_line_paragraphs(_info.callback.__doc__)
