"""Validate the connection edges in catalog/parts.json.

An assembly's `connections` record its joints as a graph over its members:

    { "from": "nema-bracket", "to": "stator", "via": "scr-m3-12-cs",
      "qty": 4, "method": "self-tap", "note": "...", "draft": true }

- `from` / `to`: the two members the joint holds together. Both MUST be
  direct members of the assembly (named in its `lines`): a joint belongs to
  the node where both sides are present, which is also where it is made on
  the bench. When a joint seems to span levels, the structure is wrong, not
  the rule -- restructure so both sides share a node (the C-channel's
  output gear bolted to the rotor became the rotor units). `to` is the
  anchor side when the joint has one -- where the fastener ends (the
  thread, insert, nut or T-nut).
- `via`: the fastener, which must be a hardware line of this assembly.
  Fastenerless joints (press, friction, clip, glue) omit it.
- `qty`: fasteners in this joint per one instance of the assembly. Across
  edges, a fastener's qtys must not exceed its line qty.
- `method`: how the joint holds. Extends the JoinMethod enum with the
  anchor kinds: `insert` is a heat-set insert in the `to` part (pairs with
  its `requires`), `thread` a machine thread in the `to` member, `tnut` an
  extrusion T-nut, `nut` a through-bolt with a nut.
- `draft: true`: extracted from prose, not yet confirmed at the bench.
  Removed when the assembly is validated.

    python scripts/check_connections.py

Pure JSON, exits non-zero listing every violation.
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent

METHODS = {"self-tap", "thread", "insert", "nut", "tnut",
           "press", "friction", "clip", "glue", "solder", "crimp"}
FASTENERLESS = {"press", "friction", "clip", "glue", "solder", "crimp"}


def main():
    d = json.loads((HERE / "catalog" / "parts.json").read_text())
    known = {p["id"] for p in d["parts"]} | {a["id"] for a in d.get("assemblies", [])}

    bad = []
    for a in d.get("assemblies", []):
        lines = {}
        for line in a.get("lines") or []:
            if line.get("part"):
                lines[line["part"]] = lines.get(line["part"], 0) + (
                    line["qty"] if isinstance(line["qty"], int) else 0)
        members = {line.get("part") or line.get("assembly")
                   for line in a.get("lines") or []}
        used = {}
        for i, c in enumerate(a.get("connections") or []):
            tag = f"{a['id']} connection {i} ({c.get('from')} -> {c.get('to')})"
            for end in ("from", "to"):
                if c.get(end) not in known:
                    bad.append(f"{tag}: {end} {c.get(end)!r} is not in the catalog")
                elif c.get(end) not in members:
                    bad.append(f"{tag}: {end} {c.get(end)!r} is not a member of "
                               f"{a['id']} -- a joint lives where both sides are "
                               f"lines; restructure rather than reach across levels")
            method = c.get("method")
            if method not in METHODS:
                bad.append(f"{tag}: method {method!r} is not one of "
                           f"{sorted(METHODS)}")
            via = c.get("via")
            if via is None:
                if method in METHODS - FASTENERLESS:
                    bad.append(f"{tag}: method {method!r} needs a fastener -- "
                               f"name it in `via`")
            else:
                if via not in lines:
                    bad.append(f"{tag}: via {via!r} is not a line of {a['id']}")
                used[via] = used.get(via, 0) + (c.get("qty") or 0)
            if not isinstance(c.get("qty"), int) or c["qty"] < 1:
                bad.append(f"{tag}: qty must be a positive integer, "
                           f"got {c.get('qty')!r}")
        for via, n in used.items():
            if lines.get(via, 0) and n > lines[via]:
                bad.append(f"{a['id']}: connections use {n} x {via} but the "
                           f"assembly's lines carry only {lines[via]}")

    if bad:
        print(f"{len(bad)} connection violation(s) in parts.json:")
        for b in bad:
            print(f"  {b}")
        sys.exit(1)
    n = sum(len(a.get("connections") or []) for a in d.get("assemblies", []))
    print(f"connections are consistent ({n} edge(s))")


if __name__ == "__main__":
    main()
