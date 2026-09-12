"""What a printed part is screwed together with, as text for engrave.py.

A builder holding a printed part wants to know which screw goes in its holes
without going back to the documentation (asked by ReveryX, 2026-09-12). The
catalog already knows: every assembly's `connections` are its joints, and each
one names its fastener in `via`. This turns that graph into one short string
per part -- "2*M3X12 5*M3X16" -- which engrave.py recesses into a face the
same way it recesses the uid.

The asterisk separates a count from its screw rather than a space, on
ReveryX's reading of the first cut: "2X M3X12 5X M3X16" spaces the groups no
wider than it spaces their parts, so the eye has to work out where each one
ends. A lowercase x would read better still and is not available -- variants()
uppercases the stamp text, which is the rule that puts a lowercase parts.json
uid on the plastic in capitals. The asterisk survives that, is two characters
shorter per group, and prints: its narrowest stroke in the pinned font is
0.92 mm at the 3.5 mm cap, wider than the 0.79 mm of the `0` standing next to
it.

It is the counts that need care, not the designations:

  * `qty` on a connection is fasteners per ASSEMBLY instance, and an assembly
    may hold several of the part (six bin retainers to a layer, sharing one
    12-screw edge). The count on the part is therefore qty / the part's line
    qty in that assembly, and a division that does not come out whole means
    the graph cannot say what one part takes -- so that part gets no text
    rather than a rounded guess.
  * A part used in two assemblies (the bin retainer is in `layer` and in
    `bottom-layer`) has one set of holes, not two, so the counts are MAXed
    across assemblies, never summed. Within one assembly they are summed: two
    edges to two different neighbours are two sets of holes.
  * Both ends of a joint are marked. `from` is the side the fastener passes
    through and `to` is the side it ends in, and both of them have the holes.

A fastener whose length is not decided (`scr-m3-tbd`, `scr-m5-shcs-tbd`) has
no designation to engrave. One of those on a part suppresses the whole text:
a part stamped with the screws we happen to know would read as the complete
list and send somebody to the wrong drawer.

Nothing here reads or writes geometry; `stamp_text()` returns the string and
engrave.py decides whether it fits. The newline it puts between the lines is
engrave.py's soft break -- one line if the part has room for one, stacked if
not.
"""

from __future__ import annotations

import collections
import json
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
PARTS_JSON = os.path.join(HERE, "parts.json")

# scr-m3-12-cs -> thread 3, length 12, head "cs". A screw id that does not
# match this is one whose size is not settled (the -tbd entries) and has no
# designation.
SCREW_ID = re.compile(r"^scr-m(\d+(?:\.\d+)?)-(\d+)-([a-z]+)$")


def designation(part_id: str) -> str | None:
    """"M3x12" for `scr-m3-12-cs`, or None if the id does not state a size."""
    m = SCREW_ID.match(part_id)
    return f"M{m.group(1)}x{m.group(2)}" if m else None


def _sort_key(part_id: str):
    m = SCREW_ID.match(part_id)
    return (float(m.group(1)), int(m.group(2)), m.group(3))


def _line_qty(assembly: dict, part_id: str) -> int | None:
    """How many of `part_id` one instance of this assembly holds, counting a
    slot it is the default for. None when the assembly does not name it
    directly, which is a part reached through some other route and not a
    count this can be sure of."""
    total = 0
    params = assembly.get("params") or {}
    for line in assembly.get("lines", []):
        if line.get("part") == part_id:
            total += line.get("qty", 1)
        elif "param" in line:
            slot = params.get(line["param"]) or {}
            if slot.get("default") == part_id:
                total += line.get("qty", 1)
    return total or None


def counts(catalog: dict) -> dict[str, dict[str, int]]:
    """{part id: {fastener part id: how many of them that one part takes}}."""
    per_assembly: dict[str, dict[str, collections.Counter]] = collections.defaultdict(dict)
    for assembly in catalog.get("assemblies", []):
        for conn in assembly.get("connections", []):
            via = conn.get("via")
            if not via:
                continue                # a fastenerless joint: press fit, clip, glue
            for end in ("from", "to"):
                part_id = conn.get(end)
                if not part_id:
                    continue
                per = per_assembly[part_id].setdefault(assembly["id"], collections.Counter())
                per[via] += conn.get("qty", 0)
    out: dict[str, dict[str, int]] = {}
    for part_id, by_assembly in per_assembly.items():
        best: collections.Counter = collections.Counter()
        usable = True
        for assembly_id, tally in by_assembly.items():
            assembly = next(a for a in catalog["assemblies"] if a["id"] == assembly_id)
            held = _line_qty(assembly, part_id)
            if held is None:
                continue                # cannot say how many of the part share these screws
            for via, qty in tally.items():
                if qty % held:
                    usable = False      # 5 screws over 2 parts: the graph cannot split them
                    break
                best[via] = max(best[via], qty // held)
            if not usable:
                break
        if usable and best:
            out[part_id] = dict(best)
    return out


def lines(fasteners: dict[str, int]) -> list[str] | None:
    """["2*M3x12", "5*M3x16"] for one part's fasteners, smallest first, or
    None if any of them has no designation to write."""
    if not fasteners or any(designation(f) is None for f in fasteners):
        return None
    order = sorted(fasteners, key=_sort_key)
    # Two lengths of the same thread read apart on their own; two HEADS of one
    # size do not, so those get the head code and only those.
    seen = collections.Counter(designation(f) for f in order)
    out = []
    for f in order:
        name = designation(f)
        if seen[name] > 1:
            name += " " + SCREW_ID.match(f).group(3).upper()
        out.append(f"{fasteners[f]}*{name}")
    return out


def stamp_text(part_id: str, catalog: dict, uid: str | None = None,
               tally: dict[str, dict[str, int]] | None = None) -> str | None:
    """The stamp text for one part: its uid (when given) and then one line per
    fastener, newline-separated. None when the catalog cannot state the part's
    fasteners -- the caller then stamps the uid alone, as it always has.

    Pass `tally` (one `counts()` for the whole catalog) when doing every part;
    it is the same answer and saves walking the assemblies each time."""
    got = (tally if tally is not None else counts(catalog)).get(part_id)
    body = lines(got) if got else None
    if not body:
        return None
    return "\n".join(([uid.upper()] if uid else []) + body)


def load(path: str = PARTS_JSON) -> dict:
    with open(path) as f:
        return json.load(f)


if __name__ == "__main__":
    import sys

    catalog = load(sys.argv[1] if len(sys.argv) > 1 else PARTS_JSON)
    printed = {p["id"]: p for p in catalog["parts"] if p.get("stl_hash")}
    tally = counts(catalog)
    for part_id in sorted(tally):
        text = stamp_text(part_id, catalog, printed.get(part_id, {}).get("uid"), tally)
        kind = "printed" if part_id in printed else "       "
        print(f"{kind} {part_id:32s} {(text or '(no text)').replace(chr(10), ' / ')}")
    print(f"\n{len(tally)} part(s) with fasteners, "
          f"{sum(1 for p in tally if p in printed)} of them printed")
