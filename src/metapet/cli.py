"""The `pet` command-line interface."""

from __future__ import annotations

import random
import sys
from collections import Counter
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Annotated, NoReturn

import click
import typer
from rich.console import Console
from rich.markdown import Markdown
from rich.markup import escape
from rich.panel import Panel
from rich.table import Table

from metapet import export, fields, paths, schema, scoring, stages, sync, wizard
from metapet import review as review_
from metapet.model import Idea, Status
from metapet.prompter import Prompter
from metapet.schema import Schema, SchemaError, Storage
from metapet.store import IdeaLookupError, Store


def _lifecycle_help() -> str:
    built_in = schema.builtin()

    def keys(stage_fields) -> str:
        return ", ".join(f"{f.key}*" if f.required else f.key for f in stage_fields)

    described = stages.describe(built_in)
    name_w = max(len(status.value) for status, _, _ in described)
    meaning_w = max(len(meaning) for _, meaning, _ in described)
    rows = [
        f"  {status.value:<{name_w}}  {meaning:<{meaning_w}}  {keys(stage_fields)}".rstrip()
        for status, meaning, stage_fields in described
    ]
    rows.append(f"  {'any stage':<{name_w + 2 + meaning_w}}  {keys(built_in.any_fields())}")
    return (
        "[bold]Lifecycle:[/] seed → sketch → spec → building → shipped, or shelved at any point.\n"
        + "\n".join(rows)
        + "\n\n"
        "Fields marked * are expected before moving on; promote only warns when they are empty, "
        "and any question can be skipped. Change the stages in <data home>/stages.toml (see the "
        "README): a stage defined there replaces the built-in stage of the same name."
    )


LIFECYCLE_HELP = _lifecycle_help()

app = typer.Typer(
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
        typer.Option("--home", help="Data directory to use (overrides $METAPET_HOME)."),
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
    err.print(f"[red]error:[/] {message}")
    raise typer.Exit(1)


def _find(store: Store, query: str) -> Idea:
    try:
        return store.find(query)
    except IdeaLookupError as exc:
        if exc.candidates:
            ids = "\n".join(f"  • {i.id}  [dim]{i.title}[/]" for i in exc.candidates)
            _fail(f"{exc}; be more specific:\n{ids}")
        _fail(str(exc))


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
    return wizard.Session(idea_schema, _prompter(), store.save, store.all_tags())


@contextmanager
def _stoppable() -> Iterator[None]:
    """Turn Ctrl-C during questions into a short message and exit code 130."""
    try:
        yield
    except KeyboardInterrupt:
        err.print("Stopped. Answers so far are saved.")
        raise typer.Exit(130) from None


def _field(idea_schema: Schema, name: str) -> schema.Field:
    try:
        return idea_schema.field(name)
    except KeyError:
        known = ", ".join(f.key for f in idea_schema.all_fields())
        _fail(f"unknown field '{escape(name)}'; known fields: {known}")


def _complete_ids(ctx: typer.Context, incomplete: str) -> list[tuple[str, str]]:
    """Shell completion for idea ids; completion must never fail loudly."""
    try:
        home = paths.resolve(ctx.find_root().params.get("home"))
        ideas = Store(home).all()
    except Exception:
        return []
    # Shells only offer candidates that extend the typed word, so match by id prefix.
    matches = [i for i in ideas if i.id.startswith(incomplete.lower())]
    return [(idea.id, idea.title) for idea in sorted(matches, key=lambda i: i.id)]


NoInput = Annotated[
    bool, typer.Option("--no-input", help="Never ask questions; use only the values given.")
]

IdArg = Annotated[
    str,
    typer.Argument(
        metavar="ID",
        help="Idea id; any unique prefix or fragment of the id or title works.",
        autocompletion=_complete_ids,
    ),
]


def _status(status: Status) -> str:
    return f"[{STATUS_STYLE[status]}]{status.value}[/]"


def _ideas_table(ideas: list[Idea], extra: dict[str, list[str]] | None = None) -> Table:
    table = Table(box=None, header_style="bold", pad_edge=False)
    table.add_column("id", style="bold", no_wrap=True, min_width=max(len(i.id) for i in ideas))
    table.add_column("title")
    table.add_column("status")
    table.add_column("exc", justify="right")
    table.add_column("imp", justify="right")
    table.add_column("effort")
    table.add_column("tags", style="dim")
    table.add_column("created", style="dim")
    for name in extra or {}:
        table.add_column(name, justify="right")
    for row, idea in enumerate(ideas):
        table.add_row(
            idea.id,
            idea.title,
            _status(idea.status),
            str(idea.excitement or ""),
            str(idea.impact or ""),
            idea.effort.value if idea.effort else "",
            ", ".join(idea.tags),
            idea.created.isoformat(),
            *[values[row] for values in (extra or {}).values()],
        )
    return table


def _stars(value: int) -> str:
    return f"{'★' * value}{'☆' * (5 - value)}"


def _print_idea(idea: Idea) -> None:
    meta = [f"{_status(idea.status)}  [dim]created {idea.created}[/]"]
    if idea.updated:
        meta[0] += f" [dim]· updated {idea.updated}[/]"
    if idea.reviewed:
        meta[0] += f" [dim]· reviewed {idea.reviewed}[/]"
    details = []
    if idea.excitement:
        details.append(f"excitement {_stars(idea.excitement)}")
    if idea.impact:
        details.append(f"impact {_stars(idea.impact)}")
    if idea.effort:
        details.append(f"effort {idea.effort.value}")
    if idea.tags:
        details.append("tags " + ", ".join(idea.tags))
    if details:
        meta.append("  ·  ".join(details))
    if idea.repo:
        meta.append(f"repo {idea.repo}")
    if idea.related:
        meta.append("related " + ", ".join(idea.related))
    if idea.shelved_reason:
        meta.append(f"[dim]shelved: {idea.shelved_reason}[/]")
    console.print(
        Panel("\n".join(meta), title=f"[bold]{idea.title}[/]", subtitle=idea.id, expand=False)
    )
    if idea.body.strip():
        console.print(Markdown(idea.body))


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
        str | None, typer.Option("--remote", help="Git remote URL for backups (implies --git).")
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
    title: Annotated[str, typer.Argument(help="The idea, in a few words.")],
    tag: Annotated[list[str] | None, typer.Option("--tag", "-t", help="Tag (repeatable).")] = None,
    note: Annotated[str | None, typer.Option("--note", "-m", help="One-line description.")] = None,
    interactive: Annotated[
        bool,
        typer.Option(
            "--interactive", "-i", help="Then ask the other seed questions (in a terminal only)."
        ),
    ] = False,
) -> None:
    """Capture a seed instantly, without opening an editor.

    Grow it later with pet promote ID (see pet promote --help for the stages).
    """
    store = _store(ctx)
    idea_schema = _schema(ctx) if interactive else None
    idea = store.create(title, tags=list(tag or []), body=note or "")
    console.print(f"[green]+[/] {idea.id}  [dim]{idea.path}[/]", soft_wrap=True)
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
    title: Annotated[str | None, typer.Argument(help="The idea, in a few words.")] = None,
    summary: Annotated[
        str | None, typer.Option("--summary", "-m", help="Describe it in one sentence.")
    ] = None,
    tag: Annotated[list[str] | None, typer.Option("--tag", "-t", help="Tag (repeatable).")] = None,
    excitement: Annotated[
        str | None, typer.Option("--excitement", "-x", help="How excited you are, 1-5.")
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
    no_input: NoInput = False,
) -> None:
    """Capture an idea with its seed fields.

    In a terminal, asks for the title if it is not given, then for the seed fields you did not
    pass as options, and offers to go on to the next stages. Every question can be skipped.
    Fields of later stages can be filled right away with --set.
    """
    store = _store(ctx)
    idea_schema = _schema(ctx)
    interactive = _interactive(no_input)
    session = _session(store, idea_schema) if interactive else None
    if not title or not title.strip():
        if session is None:
            _fail('a title is required: pet new "TITLE"')
        with _stoppable():
            title = wizard.ask_title(session)
    flagged = {
        _summary_key(idea_schema): summary,
        "tags": ",".join(tag) if tag else None,
        "excitement": excitement,
    }
    tokens = [f"{key}={value}" for key, value in flagged.items() if value is not None]
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
        idea = Idea(id=store.unique_id(title), title=title.strip())
        fields.apply_changes(idea, idea_schema, fields.parse_changes(tokens) + extra)
    except ValueError as exc:
        _fail(escape(str(exc)))
    idea.updated = None  # just created
    store.save(idea)
    console.print(f"[green]+[/] {idea.id}  [dim]{idea.path}[/]", soft_wrap=True)
    if session is None:
        return
    supplied = {"title", *(key for key, value in flagged.items() if value is not None)}
    supplied |= {c.key.lower().replace("-", "_") for c in extra}
    with _stoppable():
        wizard.new_idea(session, idea, supplied)
        wizard.continue_stages(session, idea)


# -- browsing ----------------------------------------------------------------


@app.command("ls")
def list_ideas(
    ctx: typer.Context,
    status: Annotated[
        list[Status] | None, typer.Option("--status", "-s", help="Filter by status (repeatable).")
    ] = None,
    tag: Annotated[list[str] | None, typer.Option("--tag", "-t", help="Filter by tag.")] = None,
    sort: Annotated[
        str, typer.Option(help="Sort by: created, excitement, impact, score, title.")
    ] = "created",
    all_: Annotated[
        bool, typer.Option("--all", "-a", help="Include shipped and shelved ideas.")
    ] = False,
) -> None:
    """List ideas.

    Shipped and shelved ideas are hidden unless you pass --all or filter by --status.
    """
    ideas = _store(ctx).all()
    if status:
        ideas = [i for i in ideas if i.status in status]
    elif not all_:
        ideas = [i for i in ideas if not i.status.terminal]
    if tag:
        wanted = {t.lower() for t in tag}
        ideas = [i for i in ideas if wanted & {t.lower() for t in i.tags}]
    keys = {
        "created": lambda i: (i.created, i.id),
        "excitement": lambda i: (i.excitement or 0, i.created),
        "impact": lambda i: (i.impact or 0, i.created),
        "score": lambda i: (scoring.score(i), i.created),
        "title": lambda i: i.title.lower(),
    }
    if sort not in keys:
        _fail(f"unknown sort '{sort}'; choose from: {', '.join(keys)}")
    ideas.sort(key=keys[sort], reverse=sort != "title")
    if not ideas:
        console.print('[dim]No ideas match. Capture one with[/] pet add "..."')
        return
    console.print(_ideas_table(ideas))


@app.command()
def show(ctx: typer.Context, idea_id: IdArg) -> None:
    """Show one idea."""
    _print_idea(_find(_store(ctx), idea_id))


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
    idea = _find(store, idea_id)
    if field_name is None:
        click.edit(filename=str(idea.path))
        return
    idea_schema = _schema(ctx)
    field = _field(idea_schema, field_name)
    if field.storage == Storage.FRONTMATTER:
        _fail(f"'{field.key}' is stored in the frontmatter; use pet set ID {field.key}=VALUE")
    current = fields.raw(idea, field)
    edited = click.edit(text=current, extension=".md")
    if edited is None or edited.strip() == current.strip():
        console.print(f"{idea.id}: no change")
        return
    fields.put_text(idea, field, edited, idea_schema.section_order)
    idea.touch()
    store.save(idea)
    console.print(f"{idea.id}: {escape(field.label)} updated")


@app.command(
    "set",
    context_settings={"ignore_unknown_options": True},
    help="Change fields without any questions.\n\n"
    "Each CHANGE is key=value, +tag or -tag, for example: pet set ID excitement=4 effort=S +cli "
    "-old. Keys are the field keys listed in pet --help. An empty value clears a field "
    "(summary=). tags=a,b replaces all tags. For a list field, repeat the key, one item "
    "each: features=search features=export. If a -tag is taken as an option, put -- before "
    "the changes.",
)
def set_(
    ctx: typer.Context,
    idea_id: IdArg,
    changes: Annotated[list[str], typer.Argument(metavar="CHANGE...", show_default=False)],
) -> None:
    store = _store(ctx)
    idea = _find(store, idea_id)
    try:
        done = fields.apply_changes(idea, _schema(ctx), fields.parse_changes(changes))
    except ValueError as exc:
        _fail(escape(str(exc)))
    if not done:
        console.print(f"{idea.id}: no change")
        return
    store.save(idea)
    console.print(f"{idea.id}: {escape(', '.join(done))}")


@app.command()
def note(
    ctx: typer.Context,
    idea_id: IdArg,
    text: Annotated[str, typer.Argument(help="The note; it is dated and added to Notes.")],
) -> None:
    """Add a dated line to an idea's Notes section."""
    store = _store(ctx)
    idea = _find(store, idea_id)
    try:
        fields.add_note(idea, _schema(ctx), text)
    except ValueError as exc:
        _fail(str(exc))
    store.save(idea)
    console.print(f"{idea.id}: noted")


# -- lifecycle ---------------------------------------------------------------


@app.command(
    help="Move an idea to its next stage, adding that stage's sections.\n\n"
    "Moves one stage forward by default. --to can skip stages (each skipped stage still adds "
    "its sections) or move back (adds and removes nothing). A shelved idea returns with "
    "--to STAGE.\n\n"
    "In a terminal, a forward move shows the idea, offers to fill expected fields that are "
    "still empty, then asks the questions of each new stage; every question can be skipped. "
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
) -> None:
    store = _store(ctx)
    idea_schema = _schema(ctx)
    idea = _find(store, idea_id)
    target = to or idea.status.next()
    if target is None:
        _fail(f"{idea.id} is {idea.status.value}; pass --to to move it elsewhere.")
    if target == Status.SHELVED:
        _fail("use `pet shelve ID REASON` to shelve an idea.")
    old = idea.status
    forward = bool(stages.statuses_between(old, target))
    if forward and old in stages.LIFECYCLE and _interactive(no_input):
        with _stoppable():
            if not wizard.promote(_session(store, idea_schema), idea, target):
                console.print("Not promoted.")
                return
        console.print(
            f"{idea.id}: {_status(old)} → {_status(target)}  [dim]{idea.path}[/]", soft_wrap=True
        )
        return
    gaps = stages.gaps(idea, idea_schema, stages.before(target)) if forward else []
    stages.promote(idea, target, idea_schema)
    store.save(idea)
    console.print(
        f"{idea.id}: {_status(old)} → {_status(target)}  [dim]{idea.path}[/]", soft_wrap=True
    )
    if gaps:
        labels = escape(", ".join(f.label for f in gaps))
        err.print(
            f"[yellow]warning:[/] still empty: {labels} (fill them with pet refine {idea.id})",
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
    no_input: NoInput = False,
) -> None:
    """Answer an idea's questions again, or fill the ones you skipped.

    Without FIELD, pick fields from a list ([x] filled, [ ] empty) until you choose Done. Only
    fields of the idea's stage and the stages before it are offered. The stage does not
    change. Needs a terminal.
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
    if not _interactive(no_input):
        _fail("refine needs a terminal; use pet set ID KEY=VALUE or pet edit ID --field KEY")
    with _stoppable():
        wizard.refine(_session(store, idea_schema), idea, field)


@app.command()
def shelve(
    ctx: typer.Context,
    idea_id: IdArg,
    reason: Annotated[str, typer.Argument(help="Why you're putting it aside.")],
) -> None:
    """Shelve an idea, keeping the reason for future you.

    Shelved ideas are hidden from ls and next (see them with ls -a) and gain a Retro section.
    Bring one back with: pet promote ID --to STAGE.
    """
    store = _store(ctx)
    idea = _find(store, idea_id)
    stages.move(idea, Status.SHELVED, _schema(ctx))
    idea.shelved_reason = reason
    store.save(idea)
    console.print(f"{idea.id}: {_status(Status.SHELVED)}  [dim]{reason}[/]")


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
        typer.Option("--days", "-d", min=0, help="Ideas not looked at for this many days."),
    ] = 14,
    no_input: NoInput = False,
) -> None:
    store = _store(ctx)
    idea_schema = _schema(ctx)
    ideas = review_.due(store.all(), days)
    if not ideas:
        console.print(f"Nothing to review. Everything was looked at in the last {days} days.")
        return
    if not _interactive(no_input):
        seen = [review_.last_seen(idea).isoformat() for idea in ideas]
        console.print(_ideas_table(ideas, {"last seen": seen}))
        console.print("Run pet review in a terminal to go through them.")
        return
    result = review_.run(_session(store, idea_schema), ideas)
    console.print(f"Reviewed {result.handled}, {result.remaining} left.")
    if result.stopped:
        err.print("Stopped. Answers so far are saved.")
        raise typer.Exit(130)


@app.command()
def ui(ctx: typer.Context) -> None:
    """Browse and change ideas in a full-screen view.

    Keys: / filter, a add, p promote, r refine, n note, s shelve, e edit, x excitement, q quit.
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
def search(ctx: typer.Context, text: Annotated[str, typer.Argument()]) -> None:
    """Find ideas whose title, tags or body mention TEXT."""
    needle = text.lower()
    hits = [
        idea
        for idea in _store(ctx).all()
        if needle in idea.title.lower()
        or needle in idea.body.lower()
        or any(needle in t.lower() for t in idea.tags)
    ]
    if not hits:
        console.print(f"[dim]Nothing mentions '{text}'.[/]")
        return
    console.print(_ideas_table(hits))


@app.command("next")
def next_(
    ctx: typer.Context,
    count: Annotated[int, typer.Option("--count", "-n", help="How many to suggest.")] = 3,
) -> None:
    """Suggest what to work on next.

    Ranks by (excitement + impact) / effort weight (S=1, M=2, L=4, XL=8; missing values count
    as 3, 3 and M), plus up to 0.75 for later stages and up to 0.5 for ideas that have waited
    six months.
    """
    ranked = scoring.rank(_store(ctx).all())[:count]
    if not ranked:
        console.print('[dim]No live ideas. Capture one with[/] pet add "..."')
        return
    ideas = [idea for idea, _ in ranked]
    console.print(_ideas_table(ideas, {"score": [f"{value:.2f}" for _, value in ranked]}))


@app.command("random")
def random_(ctx: typer.Context) -> None:
    """Resurface a random seed or sketch you may have forgotten."""
    pool = [i for i in _store(ctx).all() if i.status in (Status.SEED, Status.SKETCH)]
    if not pool:
        console.print("[dim]No seeds or sketches to resurface.[/]")
        return
    _print_idea(random.choice(pool))


@app.command()
def stats(ctx: typer.Context) -> None:
    """Counts by status, tag and month."""
    ideas = _store(ctx).all()
    if not ideas:
        console.print("[dim]No ideas yet.[/]")
        return
    by_status = Counter(i.status for i in ideas)
    by_tag = Counter(t.lower() for i in ideas for t in i.tags)
    by_month = Counter(i.created.strftime("%Y-%m") for i in ideas)

    table = Table(title=f"{len(ideas)} ideas", box=None, show_header=False)
    table.add_column(style="bold")
    table.add_column()
    table.add_row(
        "status", "  ".join(f"{_status(s)} {by_status[s]}" for s in Status if by_status[s])
    )
    if by_tag:
        table.add_row("tags", "  ".join(f"{t} {n}" for t, n in by_tag.most_common(10)))
    table.add_row("added", "  ".join(f"{m} {n}" for m, n in sorted(by_month.items())[-6:]))
    console.print(table)


@app.command()
def check(ctx: typer.Context) -> None:
    """Validate every idea file and stages.toml, and list empty expected fields."""
    store = _store(ctx)
    ideas, broken = store.scan()
    mismatched = [i for i in ideas if i.path and i.path.stem != i.id]
    for bad in broken:
        err.print(f"[red]✗[/] {bad.path.name}: {escape(bad.error)}")
    for idea in mismatched:
        err.print(f"[yellow]![/] {idea.path.name}: id is '{idea.id}' (rename the file to match)")
    try:
        idea_schema = schema.load(store.home)
    except SchemaError as exc:
        idea_schema = None
        err.print(f"[red]✗[/] stages.toml: {escape(str(exc))}", soft_wrap=True)
    if store.home.templates.is_dir():
        err.print(
            "[yellow]![/] templates/ is no longer used; stage fields now come from "
            "stages.toml (see README)"
        )
    if idea_schema is not None:
        for idea in ideas:
            if idea.status.terminal:
                continue
            gaps = stages.gaps(idea, idea_schema, idea.status)
            if gaps:
                labels = escape(", ".join(f.label for f in gaps))
                console.print(
                    f"[dim]i {idea.id} ({idea.status.value}): empty: {labels}[/]", soft_wrap=True
                )
    if broken or idea_schema is None:
        raise typer.Exit(1)
    console.print(f"[green]✓[/] {len(ideas)} ideas OK")


# -- backup & export ---------------------------------------------------------


@app.command("sync")
def sync_(
    ctx: typer.Context,
    message: Annotated[str | None, typer.Option("--message", "-m", help="Commit message.")] = None,
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
    md: Annotated[Path | None, typer.Option("--md", help="Write a Markdown index here.")] = None,
    json_: Annotated[Path | None, typer.Option("--json", help="Write a JSON dump here.")] = None,
) -> None:
    """Export all ideas as a Markdown index and/or JSON."""
    if not md and not json_:
        _fail("pass --md FILE and/or --json FILE")
    ideas = _store(ctx).all()
    for target, render in ((md, export.to_markdown), (json_, export.to_json)):
        if target:
            target.write_text(render(ideas), encoding="utf-8")
            console.print(f"[green]✓[/] wrote {target}")
