# metapet

[![PyPI](https://img.shields.io/pypi/v/metapet)](https://pypi.org/project/metapet/)
[![Python](https://img.shields.io/pypi/pyversions/metapet)](https://pypi.org/project/metapet/)
[![CI](https://github.com/jrazi/metapet/actions/workflows/ci.yml/badge.svg)](https://github.com/jrazi/metapet/actions/workflows/ci.yml)
[![License](https://img.shields.io/pypi/l/metapet)](https://github.com/jrazi/metapet/blob/main/LICENSE)

metapet is a command-line tool, `pet`, for keeping notes on side-project ideas. Each
idea is a Markdown file with YAML frontmatter. An idea has a stage (seed, sketch,
spec, building, shipped or shelved), and moving it to a new stage asks that stage's
questions, such as what problem it solves or how it could work.

![The full-screen view of metapet](https://raw.githubusercontent.com/jrazi/metapet/main/docs/screenshot.svg)

## Installation

```sh
uv tool install metapet
```

or `pipx install metapet`. metapet needs Python 3.11 or newer and installs a command
called `pet`. To try it without installing, run `uvx --from metapet pet`.

## Usage

Run `pet init` once to create the data folder. Then add an idea:

```console
$ pet add "Concert alerts" -t music
+ concert-alerts  Concert alerts
```

`pet new` asks for the name, a short description, tags and a rating instead.

### Stages

`pet promote` moves an idea to its next stage and asks that stage's questions. Enter
skips a question.

```console
$ pet promote concert
? What problem does it solve? I find out about shows after they sell out
? Who is it for?
? How could it work, roughly? Check my most played artists against a concert listings site every week
? What is it worth if it exists?
? Why is now a good time for it?
concert-alerts: seed → sketch
```

Any part of an id that matches only one idea works, so `concert` is enough.
`pet refine concert` changes the answers later.

### Notes and ratings

```sh
pet note concert "Songkick and Bandsintown both list concerts"
pet set concert excitement=5 effort=M
```

### Listing ideas

```console
$ pet ls
id                    title                 status  exc  tags     imp  effort
shared-shopping-list  Shared shopping list  seed      4  mobile     4  M
recipe-box            Recipe box            seed      3  cooking       M
reading-tracker       Reading tracker       seed      2  books         M
concert-alerts        Concert alerts        sketch    5  music         M

$ pet next
id                    title             status  score  exc  tags     imp  effort
concert-alerts        Concert alerts    sketch   4.25    5  music         M
shared-shopping-list  Shared shopping…  seed     4.00    4  mobile     4  M
recipe-box            Recipe box        seed     3.00    3  cooking       M
```

`pet next` ranks ideas by excitement plus impact, divided by effort. `pet show`,
`pet search` and `pet review` cover the rest, and `pet` on its own opens the
full-screen view shown above. See `pet --help` for all commands.

## Idea files

Each idea is a Markdown file that you can also edit by hand, or with `pet edit`.
This is `concert-alerts.md` from the example above, without its empty sections:

```markdown
---
id: concert-alerts
title: Concert alerts
status: sketch
created: 2026-09-25
updated: 2026-09-25
tags:
- music
excitement: 5
effort: M
---

## Problem
I find out about shows after they sell out

## Rough solution
Check my most played artists against a concert listings site every week

## Notes
- 2026-09-25: Songkick and Bandsintown both list concerts
```

## Configuration

**Data folder.** Ideas are kept in `~/.local/share/metapet` on Linux,
`~/Library/Application Support/metapet` on macOS and `%LOCALAPPDATA%\metapet` on
Windows. Set `METAPET_HOME` or pass `--home PATH` to use another folder.
`pet where` shows the folder in use.

**Custom stages.** A `stages.toml` in the data folder replaces the questions of any
stage. The [built-in file](https://github.com/jrazi/metapet/blob/main/src/metapet/stages.toml)
shows the format, and `pet check` reports mistakes.

**Backup.** `pet init --git --remote <url>` makes the folder a git repository, and
`pet sync` commits and pushes it. A folder synced by Dropbox, iCloud or Syncthing
works too.

**Shell completion.** `pet --install-completion` adds Tab completion for commands and
idea ids in bash, zsh, fish and PowerShell.

## Development

```sh
git clone https://github.com/jrazi/metapet.git
cd metapet
uv sync
uv run pytest
```

## License

[MIT](https://github.com/jrazi/metapet/blob/main/LICENSE)
