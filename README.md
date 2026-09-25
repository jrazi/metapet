# metapet

A small command-line tool for keeping your side-project ideas in one place.

Side-project ideas tend to end up spread across notes apps, chats and browser tabs,
and most of them are hard to find again when you finally have time to build
something. metapet keeps each idea as a Markdown file on your computer. Adding one
takes a few seconds. Later you can come back and fill it in, as the idea grows from
a rough thought into something you could start building.

The command is `pet`.

## Installation

```sh
uv tool install metapet
```

or

```sh
pipx install metapet
```

metapet needs Python 3.11 or newer. To try it without installing, run
`uvx --from metapet pet --help`.

## Quick start

```sh
pet init                          # create the place where ideas are stored
pet add "Plant watering bot"      # save an idea with just a name
pet new                           # add an idea and answer a few questions about it
pet ls                            # list your ideas
pet promote plant                 # move an idea to its next stage
pet                               # open the full-screen view
```

You don't have to type the whole id: any part of the id or title that matches only
one idea works, so `plant` finds `plant-watering-bot`.

## How it works

### Stages

Every idea has a stage:

| Stage | Meaning |
|---|---|
| seed | a raw thought: a name, maybe a sentence |
| sketch | thought through for a few minutes |
| spec | concrete enough to start building from |
| building | work has started |
| shipped | done and usable |
| shelved | put aside on purpose, with a reason |

Each stage comes with a few questions, such as "What problem does it solve?" or
"What is the smallest version you would actually use?". `pet promote` asks them when an idea
moves to the next stage, and `pet refine` lets you answer them again later. You can
skip any question. `pet stages` lists the fields of every stage.

### Idea files

Each idea is a Markdown file with a little YAML at the top. You can open it in any
editor, or with `pet edit`:

```markdown
---
id: plant-watering-bot
title: Plant watering bot
status: sketch
created: 2026-09-25
updated: 2026-09-25
tags:
- hardware
excitement: 4
---
Water the plants when the soil is dry.

## Problem
I forget to water them.
```

### Full-screen view

`pet` on its own (or `pet ui`) shows your ideas with a preview of the selected one.

| Key | Action |
|---|---|
| `/` | filter by words, `status:spec` or `tag:cli` |
| `a` | add an idea |
| `p` | promote to the next stage |
| `r` | answer the idea's questions |
| `n` | add a note |
| `s` | shelve |
| `e` | open in your editor |
| `q` | quit |

## Other useful commands

```sh
pet note plant "Try a capacitive soil sensor"   # add a dated note
pet set plant excitement=5 +garden             # change a field or add a tag
pet next                                        # suggest what to work on next
pet review                                      # go through ideas you haven't looked at in a while
pet search sensor                               # find ideas
```

Run `pet --help` for the full list, and `pet <command> --help` for details.

## Configuration

### Where ideas are stored

pet stores ideas in the first of these that is set:

1. the `--home PATH` option
2. the `METAPET_HOME` environment variable
3. the default data folder for your system: `~/.local/share/metapet` on Linux,
   `~/Library/Application Support/metapet` on macOS and `%LOCALAPPDATA%\metapet`
   on Windows

`pet where` shows which folder is in use.

### Custom stages

To change the questions, put a `stages.toml` file in that folder. A stage you define
there replaces the built-in stage with the same name:

```toml
[sketch]
meaning = "thought through for a few minutes"

[[sketch.fields]]
key = "problem"
label = "Problem"
question = "What problem does it solve?"
kind = "long"
required = true
```

The [built-in stages.toml](https://github.com/jrazi/metapet/blob/main/src/metapet/stages.toml)
shows every option. `pet check` reports mistakes in your file.

### Backup

pet can keep the folder in its own git repository and sync it with a remote:

```sh
pet init --git --remote git@github.com:<you>/<your-ideas>.git
pet sync
```

A folder synced by Dropbox, iCloud or Syncthing works too: point `METAPET_HOME` at it.

### Shell completion

```sh
pet --install-completion
```

Open a new shell afterwards. Commands, options and idea ids will complete with Tab.

## Development

```sh
git clone https://github.com/jrazi/metapet.git
cd metapet
uv sync
uv run pytest
uv run pet --help
```

## License

MIT. See [LICENSE](https://github.com/jrazi/metapet/blob/main/LICENSE).
