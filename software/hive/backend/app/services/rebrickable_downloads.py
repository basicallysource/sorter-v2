"""Rebrickable's CSV downloads (https://rebrickable.com/downloads/), which the
catalog syncs import. Rebrickable's API is not used: it refuses requests from
some servers, and the downloads, rebuilt daily, carry what Hive keeps."""

from __future__ import annotations

import csv
import gzip
import shutil
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import requests

DOWNLOADS_URL = "https://cdn.rebrickable.com/media/downloads"
DOWNLOAD_TIMEOUT_SECONDS = 60
# Rebrickable spells booleans True and False.
_BOOLEAN_COLUMNS = frozenset({"is_spare", "is_trans"})


def download(name: str, directory: Path) -> Path:
    """Rebrickable's ``<name>.csv.gz``, saved as it streams in."""
    path = directory / f"{name}.csv.gz"
    with requests.get(f"{DOWNLOADS_URL}/{name}.csv.gz", stream=True, timeout=DOWNLOAD_TIMEOUT_SECONDS) as resp:
        resp.raise_for_status()
        with open(path, "wb") as out:
            shutil.copyfileobj(resp.raw, out)
    return path


@contextmanager
def downloads(*names: str) -> Iterator[dict[str, Path]]:
    """Each named download, saved to a temporary directory that goes when the
    block ends. All of them are fetched before the block runs, so a failed
    download stops a sync before it changes anything."""
    with tempfile.TemporaryDirectory(prefix="rebrickable-") as tmp:
        yield {name: download(name, Path(tmp)) for name in names}


def _value(column: str, raw: str) -> Any:
    if raw == "":
        return None
    if column in _BOOLEAN_COLUMNS:
        return 1 if raw == "True" else 0
    return raw


def rows(path: Path, columns: tuple[str, ...]) -> Iterator[tuple[Any, ...]]:
    """The file's rows, the named columns of each, read one at a time
    (inventory_parts is 1.5 million rows). Empty values are None; numbers stay
    text, which SQLite stores as numbers in an INTEGER column."""
    with gzip.open(path, "rt", encoding="utf-8", newline="") as f:
        reader = csv.reader(f)
        header = next(reader)
        missing = [column for column in columns if column not in header]
        if missing:
            raise ValueError(f"{path.name} has no column {', '.join(missing)} (it has {', '.join(header)})")
        positions = [(column, header.index(column)) for column in columns]
        for row in reader:
            yield tuple(_value(column, row[i]) for column, i in positions)
