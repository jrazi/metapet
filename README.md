# metapet

[![PyPI](https://img.shields.io/pypi/v/metapet)](https://pypi.org/project/metapet/)
[![Python](https://img.shields.io/pypi/pyversions/metapet)](https://pypi.org/project/metapet/)
[![CI](https://github.com/jrazi/metapet/actions/workflows/ci.yml/badge.svg)](https://github.com/jrazi/metapet/actions/workflows/ci.yml)
[![License](https://img.shields.io/pypi/l/metapet)](https://github.com/jrazi/metapet/blob/main/LICENSE)

A small command-line tool for keeping side-project ideas as Markdown files.

Most side-project ideas end up as a line in a notes app or a message to yourself,
and by the time you have a free weekend the context is gone. metapet gives each
idea its own Markdown file and a stage. You save an idea with one command, then fill
it in over time: what problem it solves, how it could work, what to build first.
When you want to start something, `pet next` suggests an idea based on how much you
want to build it and how much work it looks like.

![The full-screen view of metapet](https://raw.githubusercontent.com/jrazi/metapet/main/docs/screenshot.svg)

## Installation

```sh
uv tool install metapet
```

or `pipx install metapet`. metapet needs Python 3.11 or newer and installs a command
called `pet`. To try it without installing, run `uvx --from metapet pet`.

## Usage

Run `pet init` once to create the folder where ideas are kept.

### Save an idea

```console
$ pet add "Music library tagger" -t music -t cli \
    -m "Tag and rename a messy music folder, using audio fingerprints to identify each track."
+ music-library-tagger  Music library tagger
```

`pet new` does the same, but asks for each field instead.

### Think it through

Every idea has a stage: `seed`, `sketch`, `spec`, `building`, `shipped`, or
`shelved` at any point. Moving an idea to the next stage asks that stage's questions.
Press Enter to skip one.

```console
$ pet promote music
? What problem does it solve? Half my music has no tags and junk file names
? Who is it for? Me
? How could it work, roughly? Fingerprint each file with AcoustID, look it up on MusicBrainz, show the changes before applying them
? What is it worth if it exists?
? Why is now a good time for it?
music-library-tagger: seed → sketch
```

Any part of an id that matches only one idea works, so `music` is enough. The answers
are saved as sections of the idea's file, and `pet refine music` lets you change them.
`pet stages` lists the fields of each stage.

### Add notes and ratings

```sh
pet note music "beets can do this, but its import step is a lot for one folder"
pet set music excitement=5 impact=3 effort=M
```

### Decide what to work on

```console
$ pet ls
id                         title                    status  exc  tags        imp  effort
train-ticket-price-alerts  Train ticket price ale…  seed      4  telegram      3  S
music-library-tagger       Music library tagger     sketch    5  music, cli    3  M
home-lab-status-page       Home lab status page     seed      3  selfhosted       M
board-game-score-keeper    Board game score keeper  seed      2  mobile

$ pet next
id                         title             status  score  exc  tags        imp  effort
train-ticket-price-alerts  Train ticket pr…  seed     7.00    4  telegram      3  S
music-library-tagger       Music library t…  sketch   4.25    5  music, cli    3  M
home-lab-status-page       Home lab status…  seed     3.00    3  selfhosted       M
```

`pet next` ranks ideas by excitement plus impact, divided by effort. `pet show music`
prints one idea, `pet search fingerprint` finds ideas by any word in them, and
`pet review` goes through the ideas you haven't looked at in two weeks.

Run `pet` on its own to open the full-screen view shown above. See `pet --help` for
all commands.

## Idea files

Each idea is a plain Markdown file, so you can also open it in any editor or with
`pet edit music`. This is the file from the example above, without its two empty
sections:

```markdown
---
id: music-library-tagger
title: Music library tagger
status: sketch
created: 2026-09-25
updated: 2026-09-25
tags:
- music
- cli
excitement: 5
impact: 3
effort: M
---

Tag and rename a messy music folder, using audio fingerprints to identify each track.

## Problem
Half my music has no tags and junk file names

## Who it's for
Me

## Rough solution
Fingerprint each file with AcoustID, look it up on MusicBrainz, show the changes before applying them

## Notes
- 2026-09-25: beets can do this, but its import step is a lot for one folder
```

## Configuration

**Where ideas are kept.** By default in `~/.local/share/metapet` on Linux,
`~/Library/Application Support/metapet` on macOS and `%LOCALAPPDATA%\metapet` on
Windows. Set `METAPET_HOME` or pass `--home PATH` to use another folder.
`pet where` shows the folder in use.

**Your own questions.** Put a `stages.toml` in that folder to replace the questions
of any stage. The [built-in file](https://github.com/jrazi/metapet/blob/main/src/metapet/stages.toml)
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
