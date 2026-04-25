#!/usr/bin/env python3
"""
Export printable parts from Onshape documents as STL files.

Credentials are read from ~/.config/onshape/credentials.json.
Document URLs and filter configuration live in onshape_config.yaml alongside
this script (or pass --config to override).
"""

import hashlib
import json
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import typer
import yaml

from onshape import Part, client_from_credentials

DEFAULT_CONFIG_PATH = Path(__file__).parent / "onshape_config.yaml"

app = typer.Typer(help=__doc__, no_args_is_help=True)


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------

def load_config(config_path: Path) -> dict:
    if not config_path.exists():
        typer.echo(f"Error: config not found at {config_path}", err=True)
        raise typer.Exit(1)
    return yaml.safe_load(config_path.read_text())


def parse_onshape_url(url: str) -> tuple[str, str, str]:
    """Return (document_id, workspace_id, element_id) from an Onshape document URL.
    element_id is an empty string if not present in the URL."""
    m = re.search(r"/documents/([0-9a-f]+)/w/([0-9a-f]+)(?:/e/([0-9a-f]+))?", url)
    if not m:
        raise ValueError(f"Cannot parse Onshape URL: {url!r}")
    return m.group(1), m.group(2), m.group(3) or ""


# ---------------------------------------------------------------------------
# Filtering
# ---------------------------------------------------------------------------

def _matches_any(name: str, patterns: list[str]) -> bool:
    return any(re.search(p, name, re.IGNORECASE) for p in patterns)


def resolve_parts(parts: list) -> list:
    """
    For each unique part name in a tab, return exactly one Part to export.

    When both a solid body and a composite body share a name, the composite
    is the final merged geometry and is preferred. Plain solids are returned
    as-is when no composite exists for that name.
    """
    by_name: dict[str, list] = {}
    for part in parts:
        by_name.setdefault(part.name, []).append(part)

    resolved = []
    for candidates in by_name.values():
        composites = [p for p in candidates if p.body_type == "composite"]
        resolved.append(composites[0] if composites else candidates[0])
    return resolved


def stl_filename(part_name: str, quantity: int | None) -> str:
    """Build an STL filename, appending _xN when quantity is known."""
    safe = re.sub(r"[^\w\-]", "_", part_name).strip("_")
    if quantity is not None:
        return f"{safe}_x{quantity}.stl"
    return f"{safe}.stl"


def should_skip_tab(
    tab_name: str,
    *,
    global_blocklist: list[str],
    doc_blocklist: list[str],
    doc_allowlist: list[str],
) -> bool:
    """
    Return True if a Part Studio tab should be skipped entirely.

    Decision order:
      1. global_blocklist — always skipped regardless of allowlist
      2. doc_blocklist    — per-document additional skips
      3. doc_allowlist    — if non-empty, tab must match at least one entry
    """
    if _matches_any(tab_name, global_blocklist):
        return True
    if _matches_any(tab_name, doc_blocklist):
        return True
    if doc_allowlist and not _matches_any(tab_name, doc_allowlist):
        return True
    return False


def is_purchased(
    part_name: str,
    *,
    purchased_names: set[str],
    purchased_patterns: list[str],
) -> bool:
    return part_name in purchased_names or _matches_any(part_name, purchased_patterns)


def should_skip_part(
    part_name: str,
    *,
    global_blocklist: list[str],
    doc_blocklist: list[str],
) -> bool:
    """
    Return True if a part should be skipped regardless of purchase status.
    Matches against global and per-document part blocklist patterns.
    """
    return _matches_any(part_name, global_blocklist) or _matches_any(part_name, doc_blocklist)


def excluded_reason(
    part_name: str,
    *,
    global_part_blocklist: list[str],
    doc_part_blocklist: list[str],
    purchased_names: set[str],
    purchased_patterns: list[str],
) -> str | None:
    """Return "blocked", "purchased", or None for parts that should be exported."""
    if should_skip_part(
        part_name,
        global_blocklist=global_part_blocklist,
        doc_blocklist=doc_part_blocklist,
    ):
        return "blocked"
    if is_purchased(
        part_name,
        purchased_names=purchased_names,
        purchased_patterns=purchased_patterns,
    ):
        return "purchased"
    return None


def group_parts_by_element(parts: list[Part]) -> dict[str, list[Part]]:
    """Group a flat list of Parts by their element_id."""
    grouped: dict[str, list[Part]] = {}
    for p in parts:
        grouped.setdefault(p.element_id, []).append(p)
    return grouped


# ---------------------------------------------------------------------------
# Version cache — sidecar JSON next to exported STLs
# ---------------------------------------------------------------------------

class VersionCache:
    """
    Per-document JSON sidecar mapping {relative_stl_path: {microversion, md5}}.

    A cache hit (current Onshape microversion matches and the STL file still
    exists on disk) lets us skip the STL export API call entirely.
    """

    FILENAME = "version_cache.json"

    def __init__(self, doc_dir: Path):
        self.doc_dir = doc_dir
        self.path = doc_dir / self.FILENAME
        self.entries: dict[str, dict] = {}
        if self.path.exists():
            try:
                self.entries = json.loads(self.path.read_text())
            except Exception:
                self.entries = {}

    def lookup(self, stl_path: Path, microversion: str) -> str | None:
        """Return cached md5 if microversion matches and file is on disk; else None."""
        if not microversion:
            return None
        rel_key = stl_path.relative_to(self.doc_dir).as_posix()
        entry = self.entries.get(rel_key)
        if not entry or entry.get("microversion") != microversion:
            return None
        if not stl_path.exists():
            return None
        return entry.get("md5")

    def record(self, stl_path: Path, microversion: str, md5: str) -> None:
        if not microversion:
            return
        rel_key = stl_path.relative_to(self.doc_dir).as_posix()
        self.entries[rel_key] = {"microversion": microversion, "md5": md5}

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.entries, indent=2, sort_keys=True))


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

@app.command()
def list_parts(
    config: Path = typer.Option(DEFAULT_CONFIG_PATH, help="Path to onshape_config.yaml"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show skipped tabs and parts"),
):
    """List all parts in configured documents, showing which will be exported."""
    client, _ = client_from_credentials()
    cfg = load_config(config)

    global_tab_blocklist: list[str] = cfg.get("global_tab_blocklist", [])
    global_part_blocklist: list[str] = cfg.get("global_part_blocklist", [])
    purchased_patterns: list[str] = cfg.get("global_purchased_patterns", [])
    purchased_names: set[str] = set(cfg.get("global_purchased_names", []))

    for doc_entry in cfg.get("documents", []):
        did, wid, eid = parse_onshape_url(doc_entry["url"])
        doc_tab_blocklist: list[str] = doc_entry.get("tab_blocklist", [])
        doc_tab_allowlist: list[str] = doc_entry.get("tab_allowlist", [])
        doc_part_blocklist: list[str] = doc_entry.get("part_blocklist", [])
        doc_variants: list[str] = doc_entry.get("variants", [])
        quantities = client.get_bom_quantities(did, wid, eid) if eid else {}

        dir_name = doc_entry.get("directory_name") or did
        description = doc_entry.get("description") or did
        typer.echo(f"\n=== [{dir_name}] {description} ===")
        typer.echo(f"  {'Tab':<44} {'Part':<38} {'Qty':>4}  Status")
        typer.echo("  " + "-" * 100)

        parts_by_tab = group_parts_by_element(client.get_parts_in_document(did, wid))

        for tab in client.get_part_studios(did, wid):
            if should_skip_tab(
                tab.name,
                global_blocklist=global_tab_blocklist,
                doc_blocklist=doc_tab_blocklist,
                doc_allowlist=doc_tab_allowlist,
            ):
                if verbose:
                    typer.echo(f"  {'[skip tab] ' + tab.name:<44} {'':38} {'':>4}  blocked")
                continue

            tab_lower = tab.name.lower()
            variant = next((v for v in doc_variants if v.lower() in tab_lower), None)

            visible = [p for p in parts_by_tab.get(tab.id, []) if not p.is_hidden]
            for part in resolve_parts(visible):
                reason = excluded_reason(
                    part.name,
                    global_part_blocklist=global_part_blocklist,
                    doc_part_blocklist=doc_part_blocklist,
                    purchased_names=purchased_names,
                    purchased_patterns=purchased_patterns,
                )
                if reason and not verbose:
                    continue
                if reason:
                    status = f"SKIP ({reason})"
                else:
                    variant_prefix = f"{variant}/" if variant else ""
                    status = f"PRINT → {variant_prefix}{tab.name}"
                qty = quantities.get((tab.id, part.part_id))
                qty_str = f"x{qty}" if qty is not None else "?"
                typer.echo(f"  {tab.name:<44} {part.name:<38} {qty_str:>4}  {status}")


class CollisionError(Exception):
    """Raised when two tabs produce the same output path with different geometry."""

    def __init__(self, stl_path: Path, prev_source: str, new_source: str):
        self.stl_path = stl_path
        self.prev_source = prev_source
        self.new_source = new_source
        super().__init__(str(stl_path))


def _register_or_skip(
    stl_path: Path,
    md5: str,
    tab_source: str,
    *,
    written: dict[Path, tuple[str, str]],
    written_lock: threading.Lock,
    lines: list[str],
    verbose: bool,
) -> bool:
    """
    Register stl_path → md5 in the cross-doc `written` dict.

    Returns True if newly registered (caller should proceed to write/record).
    Returns False if md5 matches an existing entry (caller should skip silently).
    Raises CollisionError if md5 differs from an existing entry for this path.
    """
    with written_lock:
        if stl_path in written:
            prev_md5, prev_source = written[stl_path]
            if md5 != prev_md5:
                raise CollisionError(stl_path, prev_source, tab_source)
            if verbose:
                lines.append(f"    (identical to {prev_source}, skipping)")
            return False
        written[stl_path] = (md5, tab_source)
        return True


def _remove_orphans(
    doc_output: Path,
    *,
    expected_paths: set[Path],
    version_cache: "VersionCache",
    dry_run: bool,
    lines: list[str],
) -> int:
    """
    Delete *.stl files under doc_output that no part in this run targeted.

    Anything in expected_paths is preserved — including paths whose export
    failed transiently — so a flaky API call doesn't wipe the previous good
    copy. Prunes corresponding version_cache entries and removes empty
    subdirectories left behind. Honors dry_run.
    """
    if not doc_output.exists():
        return 0

    removed = 0
    for stl_file in doc_output.rglob("*.stl"):
        if stl_file in expected_paths:
            continue
        rel_key = stl_file.relative_to(doc_output).as_posix()
        if dry_run:
            lines.append(f"  [dry-run] would remove orphan {stl_file}")
        else:
            stl_file.unlink()
            version_cache.entries.pop(rel_key, None)
            lines.append(f"  removed orphan {stl_file}")
        removed += 1

    if not dry_run:
        # Remove now-empty subdirectories, deepest first.
        for d in sorted(
            (p for p in doc_output.rglob("*") if p.is_dir()),
            key=lambda p: -len(p.parts),
        ):
            if not any(d.iterdir()):
                d.rmdir()

    return removed


def _export_document(
    doc_entry: dict,
    *,
    client,
    output_dir: Path,
    global_tab_blocklist: list[str],
    global_part_blocklist: list[str],
    purchased_patterns: list[str],
    purchased_names: set[str],
    dry_run: bool,
    verbose: bool,
    units: str,
    written: dict[Path, tuple[str, str]],
    written_lock: threading.Lock,
) -> tuple[list[str], int, int, int, int]:
    """
    Export all printable parts from one document.

    Returns (log_lines, exported_count, cached_count, skipped_count, orphans_removed).
    Raises CollisionError if a filename collision with different geometry is detected.
    """
    lines: list[str] = []
    exported = 0
    cached_count = 0
    skipped = 0
    expected_paths: set[Path] = set()

    did, wid, eid = parse_onshape_url(doc_entry["url"])
    doc_tab_blocklist: list[str] = doc_entry.get("tab_blocklist", [])
    doc_tab_allowlist: list[str] = doc_entry.get("tab_allowlist", [])
    doc_part_blocklist: list[str] = doc_entry.get("part_blocklist", [])
    doc_variants: list[str] = doc_entry.get("variants", [])
    quantities = client.get_bom_quantities(did, wid, eid) if eid else {}
    dir_name = doc_entry.get("directory_name") or did
    description = doc_entry.get("description") or did
    doc_output = output_dir / dir_name
    version_cache = VersionCache(doc_output)

    lines.append(f"\n=== [{dir_name}] {description} ===")

    parts_by_tab = group_parts_by_element(client.get_parts_in_document(did, wid))

    for tab in client.get_part_studios(did, wid):
        if should_skip_tab(
            tab.name,
            global_blocklist=global_tab_blocklist,
            doc_blocklist=doc_tab_blocklist,
            doc_allowlist=doc_tab_allowlist,
        ):
            continue

        tab_lower = tab.name.lower()
        variant = next((v for v in doc_variants if v.lower() in tab_lower), None)
        tab_source = f"{dir_name}/{variant + '/' if variant else ''}{tab.name}"

        visible = [p for p in parts_by_tab.get(tab.id, []) if not p.is_hidden]
        for part in resolve_parts(visible):
            reason = excluded_reason(
                part.name,
                global_part_blocklist=global_part_blocklist,
                doc_part_blocklist=doc_part_blocklist,
                purchased_names=purchased_names,
                purchased_patterns=purchased_patterns,
            )
            if reason:
                skipped += 1
                if verbose:
                    lines.append(f"  skip  {part.name}  ({reason})")
                continue

            qty = quantities.get((tab.id, part.part_id))
            fname = stl_filename(part.name, qty)
            stl_path = (doc_output / variant / fname) if variant else (doc_output / fname)
            expected_paths.add(stl_path)

            cached_md5 = (
                None if dry_run else version_cache.lookup(stl_path, part.microversion_id)
            )
            if cached_md5 is not None:
                if not _register_or_skip(
                    stl_path, cached_md5, tab_source,
                    written=written, written_lock=written_lock,
                    lines=lines, verbose=verbose,
                ):
                    skipped += 1
                    continue
                cached_count += 1
                if verbose:
                    lines.append(
                        f"  cached  {part.name!r} (microversion {part.microversion_id[:8]})"
                    )
                continue

            if dry_run:
                lines.append(f"  [dry-run] {stl_path}")
                exported += 1
                continue

            lines.append(f"  exporting {part.name!r} → {stl_path} ...")
            try:
                stl_bytes = client.export_part_stl(
                    did, wid, tab.id, part.part_id, units=units
                )
                md5 = hashlib.md5(stl_bytes).hexdigest()

                if not _register_or_skip(
                    stl_path, md5, tab_source,
                    written=written, written_lock=written_lock,
                    lines=lines, verbose=verbose,
                ):
                    skipped += 1
                    continue

                try:
                    stl_path.parent.mkdir(parents=True, exist_ok=True)
                    stl_path.write_bytes(stl_bytes)
                except Exception:
                    # On disk-write failure, undo the registration so a
                    # subsequent same-path part can retry the write.
                    with written_lock:
                        written.pop(stl_path, None)
                    raise

                version_cache.record(stl_path, part.microversion_id, md5)
                exported += 1
                time.sleep(0.5)  # stay within API rate limits
            except CollisionError:
                raise
            except Exception as e:
                lines.append(f"    ERROR: {e}")

    orphans_removed = _remove_orphans(
        doc_output,
        expected_paths=expected_paths,
        version_cache=version_cache,
        dry_run=dry_run,
        lines=lines,
    )

    if not dry_run:
        version_cache.save()

    return lines, exported, cached_count, skipped, orphans_removed


@app.command()
def export(
    config: Path = typer.Option(DEFAULT_CONFIG_PATH, help="Path to onshape_config.yaml"),
    output_dir: Path = typer.Option(Path("stl_output"), help="Directory to write STL files into"),
    dry_run: bool = typer.Option(False, help="Print what would be exported without downloading"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show skipped parts"),
    units: str = typer.Option("millimeter", help="Export units (millimeter, inch, etc.)"),
):
    """Export printable parts as STL files."""
    client, _ = client_from_credentials()
    cfg = load_config(config)

    global_tab_blocklist: list[str] = cfg.get("global_tab_blocklist", [])
    global_part_blocklist: list[str] = cfg.get("global_part_blocklist", [])
    purchased_patterns: list[str] = cfg.get("global_purchased_patterns", [])
    purchased_names: set[str] = set(cfg.get("global_purchased_names", []))
    documents: list[dict] = cfg.get("documents", [])

    total_exported = 0
    total_cached = 0
    total_skipped = 0
    total_orphans = 0
    written: dict[Path, tuple[str, str]] = {}
    written_lock = threading.Lock()

    with ThreadPoolExecutor(max_workers=len(documents)) as executor:
        futures = {
            executor.submit(
                _export_document,
                doc,
                client=client,
                output_dir=output_dir,
                global_tab_blocklist=global_tab_blocklist,
                global_part_blocklist=global_part_blocklist,
                purchased_patterns=purchased_patterns,
                purchased_names=purchased_names,
                dry_run=dry_run,
                verbose=verbose,
                units=units,
                written=written,
                written_lock=written_lock,
            ): doc
            for doc in documents
        }
        try:
            for future in as_completed(futures):
                lines, exported, cached, skipped, orphans = future.result()
                for line in lines:
                    typer.echo(line)
                total_exported += exported
                total_cached += cached
                total_skipped += skipped
                total_orphans += orphans
        except CollisionError as e:
            typer.echo("\nERROR: collision — same filename, different geometry:", err=True)
            typer.echo(f"  originally from: {e.prev_source}", err=True)
            typer.echo(f"  conflict from:   {e.new_source}", err=True)
            raise typer.Exit(1)

    typer.echo(
        f"\nDone. {total_exported} exported, {total_cached} cached, "
        f"{total_skipped} skipped (purchased/reference), "
        f"{total_orphans} orphan{'s' if total_orphans != 1 else ''} removed."
    )


if __name__ == "__main__":
    app()
