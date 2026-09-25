# metapet

`pet` is a small command-line tool for keeping pet-project ideas as Markdown files.
Each idea moves through stages, from a one-line seed to a plan you can build from.

```console
$ pet add "Plant watering bot" -t hardware
+ plant-watering-bot  Plant watering bot
$ pet promote plant
plant-watering-bot: seed → sketch
```

## Install

```sh
uv tool install metapet
```

Or use `pipx install metapet`, or `pip install metapet`. Needs Python 3.11 or newer.
Upgrade with `uv tool upgrade metapet` or `pipx upgrade metapet`.

## Quick start

```sh
pet init                                  # create the idea store (once)
pet add "Plant watering bot" -t hardware  # add an idea
pet ls                                    # list your ideas
pet promote plant                         # move it to the next stage
pet show plant                            # read it
pet next                                  # suggest what to work on
```

`pet ls` hides shipped and shelved ideas unless you pass `--all`.

You do not have to type the whole id. Any unique part of the id or title works.
Run `pet` on its own to open the full-screen view.

## Where ideas are stored

Ideas are plain Markdown files in a data directory. pet uses the first of these
that is set:

1. the `--home PATH` option, as in `pet --home ~/ideas ls`
2. the `METAPET_HOME` environment variable
3. the default for your system:
   - Linux: `~/.local/share/metapet`
   - macOS: `~/Library/Application Support/metapet`
   - Windows: `%LOCALAPPDATA%\metapet`

`pet where` shows the directory in use. Inside it:

```
ideas/<id>.md    one file per idea
stages.toml      optional changes to the stages
```

An idea file has YAML frontmatter and a Markdown body. You can edit it by hand:

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

## Stages

`seed → sketch → spec → building → shipped`, or `shelved` at any point.

| Stage | Meaning |
|---|---|
| seed | a raw thought: a title, maybe a one-liner |
| sketch | thought through for a few minutes |
| spec | concrete enough to start building from |
| building | real work has started |
| shipped | done and usable |
| shelved | put aside on purpose, with a reason |

Each stage asks a few questions, such as the problem or the first version's scope.
`pet promote` asks them when an idea moves on, and `pet refine` asks them again.
You can skip any question. If a field marked with * in `pet stages` is still empty,
`pet promote` prints a warning but still moves the idea.

## Customizing stages

Put a `stages.toml` in the data directory. A stage you define there replaces the
built-in stage of the same name. For example, to give `sketch` just two fields:

```toml
[sketch]
meaning = "thought through for a few minutes"

[[sketch.fields]]
key = "problem"
label = "Problem"
question = "What problem does it solve?"
kind = "long"
required = true

[[sketch.fields]]
key = "vibe"
label = "Vibe"
question = "How should it feel to use?"
```

The [built-in stages.toml](https://github.com/jrazi/metapet/blob/main/src/metapet/stages.toml)
shows every option. `pet check` reports mistakes in your file.

## Full-screen view

`pet ui`, or `pet` on its own, shows your ideas with a preview of the selected one.

| Key | Action |
|---|---|
| `/` | Filter by words, `status:spec` or `tag:cli` (Escape clears it) |
| `a` | Add an idea |
| `p` | Promote to the next stage |
| `r` | Refine: answer questions |
| `n` | Add a note |
| `s` | Shelve, with a reason |
| `x` | Set excitement (1-5) |
| `e` | Open the file in `$EDITOR` |
| `q` | Quit |

Shipped and shelved ideas are hidden unless the filter has a `status:` word.

## Backup

pet can keep the data directory in its own git repository:

```sh
pet init --git --remote git@github.com:<you>/<your-ideas-repo>.git
pet sync
```

`pet sync` commits, pulls and pushes. You can also point `METAPET_HOME` at a folder
that Dropbox, iCloud or Syncthing keeps in sync.

## Shell completion

```sh
pet --install-completion
```

Then open a new shell. This works in bash, zsh, fish and PowerShell, and completes
commands, options and idea ids.

## Commands

| Command | What it does |
|---|---|
| `pet init` | Create the idea store |
| `pet add` | Add an idea with just a title |
| `pet new` | Add an idea and answer its first questions |
| `pet ls` | List ideas; add `--all` to include shipped and shelved (also `pet list`) |
| `pet show` | Show one idea |
| `pet edit` | Open an idea in `$EDITOR` |
| `pet set` | Change fields, such as `excitement=4` or `+tag` |
| `pet note` | Add a dated note |
| `pet rename` | Change an idea's id |
| `pet rm` | Delete an idea (also `pet delete`) |
| `pet promote` | Move an idea to its next stage |
| `pet refine` | Answer an idea's questions again |
| `pet shelve` | Put an idea aside and record why |
| `pet review` | Go through ideas you have not looked at for a while |
| `pet ui` | Open the full-screen view |
| `pet search` | Find ideas (also `pet find`) |
| `pet next` | Suggest what to work on next |
| `pet random` | Show a random seed or sketch |
| `pet stats` | Count ideas by stage, tag and month |
| `pet stages` | Show the stages and their fields |
| `pet check` | Check idea files and `stages.toml` |
| `pet where` | Show the data directory in use |
| `pet sync` | Back up with git |
| `pet export` | Export ideas as a Markdown index, JSON, or both |

Run `pet <command> --help` for options. When piped, list commands print
tab-separated lines.

## Development

```sh
git clone https://github.com/jrazi/metapet.git
cd metapet
uv sync
uv run pytest
uv run ruff check . && uv run ruff format --check .
```

`uv run pet` runs the tool from the checkout. In a source checkout, `pet init --local`
stores ideas in `./data`, which git ignores. pet uses that folder when `--home` and
`METAPET_HOME` are not set.

## License

MIT. See [LICENSE](https://github.com/jrazi/metapet/blob/main/LICENSE).
