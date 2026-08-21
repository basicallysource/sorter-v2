#!/usr/bin/env python3
"""Verify the committed generated data agrees with the committed source pins.

The generated files are written by whoever edits slicer/parts.json running
slicer/filament.py, and committed in the same change; nothing regenerates them
after the fact. So the guard against "edited the source, forgot to regenerate"
is this cross-check: every printed part's generated entry must serve exactly
the STL its pin names, carry real slice numbers, and no entry may outlive its
part. Pure JSON, no network, no slicer.

    python scripts/check_generated_pins.py

Exits non-zero listing every disagreement.
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE / "scripts"))
from sync_bucket import stl_url  # noqa: E402


def main():
    manifest = json.loads((HERE / "slicer" / "parts.json").read_text())
    generated = json.loads(
        (HERE / "src" / "lib" / "data" / "parts.generated.json").read_text())
    gen = {p["id"]: p for p in generated["parts"]}

    printed = [p for p in manifest["parts"]
               if p.get("kind", "printed") == "printed" and p.get("stl_hash")]
    bad = []
    for p in printed:
        g = gen.get(p["id"])
        if g is None:
            bad.append(f"{p['id']}: pinned in parts.json but absent from parts.generated.json")
            continue
        want = stl_url(p["id"], p["stl_id"], p["stl_hash"])
        if g.get("stl") != want:
            bad.append(f"{p['id']}: generated stl is {g.get('stl')!r}, the pin says {want!r}")
        if not isinstance(g.get("grams"), (int, float)):
            bad.append(f"{p['id']}: no grams in the generated data")

    live = {p["id"] for p in printed}
    for pid in gen:
        if pid not in live:
            bad.append(f"{pid}: in parts.generated.json but no longer pinned in parts.json")

    if bad:
        print(f"{len(bad)} disagreement(s) between parts.json and parts.generated.json:")
        for b in bad:
            print(f"  {b}")
        print("\nRun slicer/filament.py and commit the regenerated data with your change.")
        sys.exit(1)
    print(f"parts.generated.json agrees with parts.json ({len(printed)} pinned parts)")


if __name__ == "__main__":
    main()
