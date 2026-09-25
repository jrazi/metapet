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
empty: if an expected field of an earlier stage is empty, promote warns and moves the
idea anyway. In a terminal it first offers to fill those fields, then asks the
questions of the new stage; any question can be skipped. `pet check` lists the empty
expected fields of every idea.

Fill fields by answering questions with `pet refine ID`, with `pet set ID KEY=VALUE`,
`pet note ID TEXT` or `pet edit ID --field KEY`, or edit the file by hand. Headings match fields by name,
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
| `pet add TITLE [-t TAG]… [-m NOTE] [-i]` | Capture a seed instantly; `-i` then asks the other seed questions |
| `pet new [TITLE] [-m SUMMARY] [-t TAG]… [-x 1-5] [-s KEY=VALUE]… [--no-input]` | Capture an idea, asking for the seed fields not given as options, then offering the next stages |
| `pet ls [-s STATUS]… [-t TAG]… [--sort created\|excitement\|impact\|score\|title] [-a]` | List live ideas (`-a` includes shipped/shelved) |
| `pet show ID` · `pet edit ID` | View or edit; `ID` can be any unique prefix or fragment |
| `pet edit ID --field FIELD` | Edit one section in `$EDITOR` |
| `pet set ID KEY=VALUE… [+TAG] [-TAG]` | Change fields; an empty value clears one |
| `pet note ID TEXT` | Add a dated line to the Notes section |
| `pet promote ID [--to STATUS] [--no-input]` | Advance the lifecycle and ask the new stage's questions; warns about empty expected fields |
| `pet refine ID [FIELD] [--no-input]` | Answer one field again, or pick fields from a list |
| `pet shelve ID REASON` | Park an idea, remembering why |
| `pet review [--days N] [--no-input]` | Go through live ideas not looked at for N days (default 14) |
| `pet ui` · `pet` | Browse and change ideas in a full-screen view (bare `pet` outside a terminal prints help) |
| `pet search TEXT` | Search titles, tags and bodies |
| `pet next [-n N]` | Suggest what to build next |
| `pet random` | Resurface a forgotten seed or sketch |
| `pet stats` | Counts by status, tag and month |
| `pet check` | Validate idea files and `stages.toml`; list empty expected fields |
| `pet where` | Show the data directory in use |
| `pet sync [-m MSG]` | Git backup: commit, pull --rebase, push |
| `pet export [--md FILE] [--json FILE]` | Markdown index and/or JSON dump |

`new`, `add -i`, `promote`, `refine` and `review` ask questions only when run in a
terminal; `--no-input` turns the questions off, and outside a terminal they use only
the values you give. Press Enter to skip a question and keep the current value; clear a value
with `pet set ID KEY=`. Every answer is saved right away, so Ctrl-C keeps the answers
given so far.

### How `next` ranks ideas

Ranks by (excitement + impact) / effort weight (S=1, M=2, L=4, XL=8; missing values
count as 3, 3 and M), plus up to 0.75 for later stages and up to 0.5 for ideas that
have waited six months. Shipped and shelved ideas are excluded.

### Reviewing ideas

`pet review` shows the live ideas you have not looked at for a while, oldest first.
An idea counts as looked at when it was created, changed or reviewed; the date of
the last review is kept in the `reviewed` key. For each idea you can promote it,
refine it, add a note, set its excitement, shelve it, skip it or quit. Anything but
quit marks the idea as reviewed. Outside a terminal it only lists the ideas.

### Full-screen view

`pet ui`, or `pet` on its own in a terminal, opens a list of ideas with a preview of
the selected one. Keys:

| Key | Action |
|---|---|
| `/` | Filter: words, `status:spec`, `tag:cli` (Enter goes back to the list, Escape clears) |
| `a` | Add an idea |
| `p` | Promote to the next stage |
| `r` | Refine: pick fields to answer |
| `n` | Add a note |
| `s` | Shelve, with a reason |
| `e` | Open the file in `$EDITOR` |
| `x` | Set excitement (1-5) |
| `q` | Quit |

Add, promote and refine ask the same questions as the commands of the same name;
the view steps aside while they run and comes back afterwards. Shipped and shelved
ideas are hidden unless the filter has a `status:` word.

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
