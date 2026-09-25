# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.1] - 2026-09-25

### Changed

- Rewrote the README around a worked example, with a screenshot of the full-screen view.
- Reworded the package summary.

## [0.1.0] - 2026-09-25

### Added

- The `pet` command, which keeps pet-project ideas as Markdown files with YAML frontmatter.
- Stages from seed to shipped, or shelved, with a few questions for each stage.
  Change them in `stages.toml`.
- Commands to add, list, search, show, edit, promote, refine, shelve and review ideas.
- `pet next` and `pet random` to pick an idea to work on.
- A full-screen view (`pet ui`, or `pet` on its own).
- Optional git backup with `pet sync`, and export to Markdown and JSON.
- Shell completion for commands and idea ids.

[0.1.1]: https://github.com/jrazi/metapet/releases/tag/v0.1.1
[0.1.0]: https://github.com/jrazi/metapet/releases/tag/v0.1.0
