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

Run `pet init` once to create the data folder. Then add an idea with a name, a tag
and a short description:

```console
$ pet add "Nearby concert alerts" -t music \
    -m "Email me when an artist I listen to on Spotify announces a show in my city."
+ nearby-concert-alerts  Nearby concert alerts
```

The idea is saved as `nearby-concert-alerts.md`. `pet new` asks for the same things
one by one instead.

### Stages

`pet promote` moves an idea to its next stage and asks that stage's questions. Enter
skips a question.

```console
$ pet promote concert
? What problem does it solve? I find out about shows after they sell out
? Who is it for? Me and anyone who goes to a lot of concerts
? How could it work, roughly? Read my top artists from the Spotify API and check a concert listings API once a week
? What is it worth if it exists?
? Why is now a good time for it?
nearby-concert-alerts: seed → sketch
```

Any part of an id that matches only one idea works, so `concert` is enough.
`pet refine concert` changes the answers later.

### Notes and ratings

```sh
pet note concert "Songkick and Bandsintown both have APIs for concert listings"
pet set concert excitement=5 effort=M
```

### Listing ideas

```console
$ pet ls
id                     title                  status  exc  tags     imp  effort
recipe-box             Recipe box             seed      3  cooking       M
reading-tracker        Reading tracker        seed      2  books         M
nearby-concert-alerts  Nearby concert alerts  sketch    5  music         M
family-grocery-list    Family grocery list    seed      4  mobile     4  M

$ pet next
id                     title                  status  score  exc  tags     imp
nearby-concert-alerts  Nearby concert alerts  sketch   4.25    5  music
family-grocery-list    Family grocery list    seed     4.00    4  mobile     4
recipe-box             Recipe box             seed     3.00    3  cooking
```

`pet next` ranks ideas by excitement plus impact, divided by effort. `pet show`,
`pet search` and `pet review` cover the rest, and `pet` on its own opens the
full-screen view shown above. See `pet --help` for all commands.

## Idea files

Each idea is a Markdown file that you can also edit by hand, or with `pet edit`.
This is `nearby-concert-alerts.md` after the commands above, without its two empty
sections:

```markdown
---
id: nearby-concert-alerts
title: Nearby concert alerts
status: sketch
created: 2026-09-25
updated: 2026-09-25
tags:
- music
excitement: 5
effort: M
---

Email me when an artist I listen to on Spotify announces a show in my city.

## Problem
I find out about shows after they sell out

## Who it's for
Me and anyone who goes to a lot of concerts

## Rough solution
Read my top artists from the Spotify API and check a concert listings API once a week

## Notes
- 2026-09-25: Songkick and Bandsintown both have APIs for concert listings
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
