# metapet

A tiny CLI for capturing pet-project ideas the moment they strike, then growing
them from a one-line seed into a buildable spec.

```console
$ pet add "Spotify downloader bot for Telegram" -t telegram -t bot
+ spotify-downloader-bot-for-telegram
$ pet promote spotify
spotify-downloader-bot-for-telegram: seed → sketch
$ pet next
```

## Install

Requires [uv](https://docs.astral.sh/uv/).

```sh
git clone <this repo> && cd metapet
uv tool install -e .     # puts `pet` on your PATH
pet init
```

Or run it without installing: `uv run pet …`.

### Tab completion

```sh
pet --install-completion   # bash, zsh, fish or PowerShell; then open a new shell
```

Completes commands, options and idea ids (`pet show sp<TAB>`); zsh and fish also
show each idea's title. `pet --help` and `pet promote --help` explain the lifecycle
and list each stage's fields.

## Where ideas live

The repository holds **only the tool**. Your ideas are stored in a separate data
directory and never enter this repo's history. The first match wins:

| # | Source | Example |
|---|---|---|
| 1 | `--home PATH` flag | `pet --home ~/ideas ls` |
| 2 | `METAPET_HOME` environment variable | `export METAPET_HOME=~/ideas` |
| 3 | `./data` in a source checkout, **if it exists** (portable mode, gitignored) | `pet init --local` |
| 4 | The platform's user data directory | Linux `~/.local/share/metapet`, macOS `~/Library/Application Support/metapet`, Windows `%LOCALAPPDATA%\metapet` |

`pet where` prints the directory in use and which rule picked it.

```
<data home>/
├── ideas/<id>.md    # one idea per file
└── stages.toml      # optional changes to the stage fields
```

## Ideas

Each idea is a Markdown file with YAML frontmatter, pleasant to edit by hand:

```markdown
---
id: spotify-downloader-bot-for-telegram
title: Spotify downloader bot for Telegram
status: seed
created: 2026-09-25
tags: [telegram, bot]
excitement: 4      # 1-5
impact: 3          # 1-5
effort: M          # S / M / L / XL
---
Send a Spotify link, get the audio back.
```

Only `id`, `title`, `status` and `created` are required. Optional fields are
`updated`, `reviewed`, `tags`, `excitement`, `impact`, `effort`, `repo`, `related`
and `shelved_reason`. Unknown keys are preserved.

### Lifecycle

`seed → sketch → spec → building → shipped`, or `shelved` at any point.

Each stage has a few fields: questions worth answering before the idea moves on.
Most answers are sections in the body (`## Problem`); a few are frontmatter keys.
Fields marked * are expected before moving on:

| Stage | Fields (key: where it is stored) |
|---|---|
| seed | title*: frontmatter · summary: text before the first heading · tags, excitement: frontmatter |
| sketch | problem* (`## Problem`) · audience (`## Who it's for`) · solution* (`## Rough solution`) · value (`## Value`) · why_now (`## Why now`) |
| spec | features* (`## Features`) · mvp* (`## MVP scope`) · stack · risks · prior_art (sections) · effort, impact: frontmatter |
| building | repo*: frontmatter · next_step (`## Next step`) · log (`## Log`, dated items) |
| shipped / shelved | retro (`## Retro`) |
| any stage | notes (`## Notes`, dated items) · links (`## Links`) · related: frontmatter |

`pet promote` moves an idea forward and adds an empty section, with the question as
an HTML comment, for each section field of the new stage. It never touches what you
have already written and skips sections you already have. Every field can be left
empty: if an expected field of an earlier stage is empty, promote prints a warning
and moves the idea anyway. `pet check` lists the empty expected fields of every idea.

Fill fields with `pet set ID KEY=VALUE`, `pet note ID TEXT` or
`pet edit ID --field KEY`, or edit the file by hand. Headings match fields by name,
ignoring case, so files written by older versions keep working.

### Changing the stages

Put a `stages.toml` in the data home to change the fields. A stage you define there
replaces the built-in stage of the same name completely, including its field list;
stages you leave out stay as they are. If your stage has no `meaning`, the built-in
one is kept. For example, to give `sketch` just two fields:

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

See [`src/metapet/stages.toml`](src/metapet/stages.toml) for the built-in file and
every option (`kind`, `store`, `hint`, `choices`, `aliases`, `dated`). `pet check`
reports mistakes in your file. The old `templates/` folder is no longer used.

## Commands

| Command | What it does |
|---|---|
| `pet init [--local] [--git] [--remote URL]` | Create the store, optionally as a git repo |
| `pet add TITLE [-t TAG]… [-m NOTE]` | Capture a seed instantly |
| `pet new TITLE [-m SUMMARY] [-t TAG]… [-x 1-5] [-s KEY=VALUE]…` | Capture an idea with its seed fields (and any others with `--set`) |
| `pet ls [-s STATUS]… [-t TAG]… [--sort created\|excitement\|impact\|score\|title] [-a]` | List live ideas (`-a` includes shipped/shelved) |
| `pet show ID` · `pet edit ID` | View or edit; `ID` can be any unique prefix or fragment |
| `pet edit ID --field FIELD` | Edit one section in `$EDITOR` |
| `pet set ID KEY=VALUE… [+TAG] [-TAG]` | Change fields; an empty value clears one |
| `pet note ID TEXT` | Add a dated line to the Notes section |
| `pet promote ID [--to STATUS] [--no-input]` | Advance the lifecycle; warns about empty expected fields |
| `pet shelve ID REASON` | Park an idea, remembering why |
| `pet search TEXT` | Search titles, tags and bodies |
| `pet next [-n N]` | Suggest what to build next |
| `pet random` | Resurface a forgotten seed or sketch |
| `pet stats` | Counts by status, tag and month |
| `pet check` | Validate idea files and `stages.toml`; list empty expected fields |
| `pet where` | Show the data directory in use |
| `pet sync [-m MSG]` | Git backup: commit, pull --rebase, push |
| `pet export [--md FILE] [--json FILE]` | Markdown index and/or JSON dump |

### How `next` ranks ideas

Ranks by (excitement + impact) / effort weight (S=1, M=2, L=4, XL=8; missing values
count as 3, 3 and M), plus up to 0.75 for later stages and up to 0.5 for ideas that
have waited six months. Shipped and shelved ideas are excluded.

## Backing up your ideas

Because ideas stay out of this repo, back them up however you like. The built-in
option is to make the data directory its own (private) git repository:

```sh
pet init --git --remote git@github.com:<you>/<your-ideas-repo>.git
pet sync
```

Cloud-synced folders (Dropbox, iCloud, Syncthing) also work: point
`METAPET_HOME` at one.

## Development

```sh
uv sync
uv run pytest
uv run ruff check . && uv run ruff format --check .
```

## License

MIT
