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
└── templates/       # optional overrides of the stage templates
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
effort: M          # S / M / L / XL
---
Send a Spotify link, get the audio back.
```

Only `id`, `title`, `status` and `created` are required. Optional fields are
`updated`, `tags`, `excitement`, `effort`, `repo`, `related` and
`shelved_reason`. Unknown keys are preserved.

### Lifecycle

`seed → sketch → spec → building → shipped`, or `shelved` at any point.

`pet promote` moves an idea forward and appends the new stage's sections to the
body. It never touches what you've already written, and it skips sections you
already have:

| Stage | Sections added |
|---|---|
| sketch | Problem · Rough solution · Why me / why now |
| spec | Features · MVP scope · Stack · Risks · Prior art |
| building | Repo · Log |
| shipped / shelved | Retro |

To customise a stage, drop your own `sketch.md`, `spec.md`, `building.md` or
`retro.md` into `<data home>/templates/`.

## Commands

| Command | What it does |
|---|---|
| `pet init [--local] [--git] [--remote URL]` | Create the store, optionally as a git repo |
| `pet add TITLE [-t TAG]… [-m NOTE]` | Capture a seed instantly |
| `pet new [--no-edit]` | Capture interactively, then open `$EDITOR` |
| `pet ls [-s STATUS]… [-t TAG]… [--sort created\|excitement\|score\|title] [-a]` | List live ideas (`-a` includes shipped/shelved) |
| `pet show ID` · `pet edit ID` | View or edit; `ID` can be any unique prefix or fragment |
| `pet promote ID [--to STATUS]` | Advance the lifecycle |
| `pet shelve ID REASON` | Park an idea, remembering why |
| `pet search TEXT` | Search titles, tags and bodies |
| `pet next [-n N]` | Suggest what to build next |
| `pet random` | Resurface a forgotten seed or sketch |
| `pet stats` | Counts by status, tag and month |
| `pet check` | Validate every idea file |
| `pet where` | Show the data directory in use |
| `pet sync [-m MSG]` | Git backup: commit, pull --rebase, push |
| `pet export [--md FILE] [--json FILE]` | Markdown index and/or JSON dump |

### How `next` ranks ideas

`excitement ÷ effort weight` (S=1, M=2, L=4, XL=8; missing values default to 3
and M), plus a small bonus for later stages (up to +0.75) and for ideas that have
waited a long time (up to +0.5 after six months). Shipped and shelved ideas are
excluded.

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
