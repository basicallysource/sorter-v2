"""machine.toml, this machine's config file: where it is, reading it, changing it.

Everything that touches the file goes through here. read() parses it; edit()
holds one lock across the read, the caller's change and the write, so two saves
at once can't undo each other, and writes the file atomically. A malformed file
raises MachineTomlError for every caller alike.

Every reader and writer asks machine_toml_path(); nothing else reads
MACHINE_SPECIFIC_PARAMS_PATH. When a dozen places each read the variable with a
fallback of their own, settings saved from the UI could land in a file the
running machine never read.
"""

from __future__ import annotations

import copy
import os
import tempfile
import threading
import tomllib
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

import tomli_w

ENV_VAR = "MACHINE_SPECIFIC_PARAMS_PATH"
BACKEND_DIR = Path(__file__).resolve().parent
DEFAULT_PATH = BACKEND_DIR.parents[1] / "machine.toml"  # software/, beside machine.example.toml

_LOCK = threading.RLock()
# The control loop reads settings every tick, so the last parse is reused while
# the file's text is unchanged: reading 5 KB is cheap, parsing it is not.
_parsed: tuple[tuple[Path, str], dict[str, Any]] | None = None
_resolved: tuple[str, Path] | None = None


class MachineTomlError(Exception):
    """machine.toml can't be parsed or written."""


def machine_toml_path() -> Path:
    """software/machine.toml, or MACHINE_SPECIFIC_PARAMS_PATH if it's set.

    A relative value is taken from the backend directory: machines set it in
    software/.env as "../../machine.toml", written for a backend started there,
    and a script started anywhere else has to find the same file."""
    global _resolved
    raw = os.environ.get(ENV_VAR, "").strip()
    if not raw:
        return DEFAULT_PATH
    cached = _resolved
    if cached is not None and cached[0] == raw:
        return cached[1]
    path = Path(raw).expanduser()
    path = path if path.is_absolute() else (BACKEND_DIR / path).resolve()
    _resolved = (raw, path)
    return path


def read() -> dict[str, Any]:
    """The parsed file, or {} when there is none yet. A copy: change it freely."""
    global _parsed
    path = machine_toml_path()
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    except OSError as exc:
        raise MachineTomlError(f"can't read {path}: {exc}") from exc
    cached = _parsed
    if cached is None or cached[0] != (path, text):
        try:
            cached = ((path, text), tomllib.loads(text))
        except tomllib.TOMLDecodeError as exc:
            raise MachineTomlError(f"{path} is not valid TOML: {exc}") from exc
        _parsed = cached
    return copy.deepcopy(cached[1])


@contextmanager
def edit() -> Iterator[dict[str, Any]]:
    """Change the file: `with edit() as config: config["chute"] = {...}`.

    The file is written when the block ends without an exception, and only if
    the config changed. None values are left out: TOML has no null."""
    with _LOCK:
        config = read()
        before = copy.deepcopy(config)
        yield config
        if config != before:
            _write(config)


def _without_none(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _without_none(v) for k, v in value.items() if v is not None}
    if isinstance(value, (list, tuple)):
        return [_without_none(v) for v in value if v is not None]
    return value


def _write(config: dict[str, Any]) -> None:
    path = machine_toml_path()
    try:
        text = tomli_w.dumps(_without_none(config))
    except TypeError as exc:
        raise MachineTomlError(f"can't write {path}: {exc}") from exc
    path.parent.mkdir(parents=True, exist_ok=True)
    # mkstemp makes the file 0600, which it keeps: machine.toml can hold keys.
    fd, tmp_path = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
    except OSError as exc:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise MachineTomlError(f"can't write {path}: {exc}") from exc
