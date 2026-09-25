"""Resolve where ideas are stored.

Resolution order (first match wins):

1. an explicit path (the ``--home`` flag)
2. the ``METAPET_HOME`` environment variable
3. ``<checkout>/data`` if it exists ("portable mode", source checkouts only)
4. the platform's per-user data directory (via platformdirs)
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from platformdirs import user_data_dir

APP_NAME = "metapet"
ENV_VAR = "METAPET_HOME"
IDEAS_DIR = "ideas"
TEMPLATES_DIR = "templates"


@dataclass(frozen=True)
class DataHome:
    path: Path
    source: str

    @property
    def ideas(self) -> Path:
        return self.path / IDEAS_DIR

    @property
    def templates(self) -> Path:
        return self.path / TEMPLATES_DIR

    @property
    def exists(self) -> bool:
        return self.ideas.is_dir()


def checkout_root() -> Path | None:
    """Return the source checkout root when running from one, else None."""
    root = Path(__file__).resolve().parents[2]
    return root if (root / "pyproject.toml").is_file() else None


def portable_dir() -> Path | None:
    root = checkout_root()
    return root / "data" if root else None


def resolve(explicit: str | os.PathLike[str] | None = None) -> DataHome:
    if explicit:
        return DataHome(Path(explicit).expanduser().resolve(), "--home flag")
    env = os.environ.get(ENV_VAR)
    if env:
        return DataHome(Path(env).expanduser().resolve(), f"${ENV_VAR}")
    portable = portable_dir()
    if portable is not None and portable.is_dir():
        return DataHome(portable, "portable ./data in checkout")
    return DataHome(Path(user_data_dir(APP_NAME, appauthor=False)), "platform default")
