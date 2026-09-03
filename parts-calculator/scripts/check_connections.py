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
  extrusion T-nut, `nut` a through-bolt with a nut. `gravity` is a part
  that just sits in place under its own weight.
- `through_mm` / `thread_mm`: measured screw-length geometry. `through_mm`
  is the fastener's travel through the `from` side before it reaches the
  anchor, measured over the plain bore only -- a countersink's cone is NOT
  included, because a countersunk screw's nominal length includes its head
  and the head rides in the cone (the site's fit math subtracts the head).
  `thread_mm` is the thread length waiting on the `to` side (tapped
  plastic, insert, nut). Both optional, positive numbers -- record them
  and compatible screw lengths become computable instead of remembered.
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
           "press", "friction", "clip", "glue", "solder", "crimp", "gravity"}
FASTENERLESS = {"press", "friction", "clip", "glue", "solder", "crimp", "gravity"}


def main():
    d = json.loads((HERE / "catalog" / "parts.json").read_text())
    known = {p["id"] for p in d["parts"]} | {a["id"] for a in d.get("assemblies", [])}

    asm_params = {a["id"]: a.get("params") or {} for a in d.get("assemblies", [])}

    bad = []
    for a in d.get("assemblies", []):
        # params: each slot's default must be a real part, each {param} line a
        # declared slot, and each line's args must fill slots the target
        # assembly declares — with real ids, or '$x' forwarding this
        # assembly's own param x.
        params = a.get("params") or {}
        for name, spec in params.items():
            if (spec or {}).get("default") not in known:
                bad.append(f"{a['id']} param {name}: default "
                           f"{(spec or {}).get('default')!r} is not in the catalog")
        for line in a.get("lines") or []:
            if line.get("param") is not None:
                if line.get("part") or line.get("assembly"):
                    bad.append(f"{a['id']}: a line is a part, an assembly OR a "
                               f"param slot -- not several at once: {line!r}")
                if line["param"] not in params:
                    bad.append(f"{a['id']}: line references param "
                               f"{line['param']!r}, which this assembly does "
                               f"not declare")
            for k, v in (line.get("args") or {}).items():
                target = line.get("assembly")
                if target is None:
                    bad.append(f"{a['id']}: args only make sense on a line "
                               f"referencing a sub-assembly: {line!r}")
                elif k not in asm_params.get(target, {}):
                    bad.append(f"{a['id']}: passes arg {k!r} to {target}, "
                               f"which declares no such param")
                if isinstance(v, str) and v.startswith("$"):
                    if v[1:] not in params:
                        bad.append(f"{a['id']}: arg {k}={v!r} forwards a param "
                                   f"this assembly does not declare")
                elif v not in known:
                    bad.append(f"{a['id']}: arg {k}={v!r} is not in the catalog")
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
            for k in ("through_mm", "thread_mm"):
                if k in c and not (isinstance(c[k], (int, float))
                                   and not isinstance(c[k], bool) and c[k] > 0):
                    bad.append(f"{tag}: {k} must be a positive number, "
                               f"got {c[k]!r}")
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
