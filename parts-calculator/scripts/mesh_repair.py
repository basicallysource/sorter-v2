#!/usr/bin/env python
"""Close the tessellation defects in an STL without moving any real geometry.

For when a part is sound in CAD but its export is not a closed solid. Three
steps, each refusing anything that is not obviously a slip of the tessellator:

  1. delete coincident triangle pairs (the same triangle twice, facing opposite
     ways: a flap with no thickness, which nothing can be printed from),
  2. split each boundary into simple cycles, since a boundary pinched at one
     vertex is two holes that touch rather than one big one,
  3. fill each cycle as a fan from its own centroid, refusing any hole wider
     than --max-span, which is what keeps this from quietly reshaping a part.

Nothing already in the file is moved, so every added triangle lies inside the
hole's own bounding box, and the report says exactly how many triangles were
touched. A repaired export is not what the CAD gave you: prefer fixing the
feature that tessellates badly, and treat this as the fallback.

    python scripts/mesh_repair.py in.stl out.stl [--max-span 1.0]

Exits 1 if the result is still not a closed volume.
"""
import argparse
import sys
from collections import Counter

import numpy as np
import trimesh


def open_edges(mesh):
    counts = Counter(tuple(e) for e in mesh.edges_sorted)
    return [e for e, n in counts.items() if n == 1]


def drop_coincident(mesh):
    """Remove both halves of any triangle that appears twice. Two coincident
    faces are not a surface, and keeping either one would leave a fin."""
    keys = [tuple(sorted(f)) for f in mesh.faces]
    seen = Counter(keys)
    dup = [i for i, k in enumerate(keys) if seen[k] > 1]
    if dup:
        keep = np.ones(len(mesh.faces), bool)
        keep[dup] = False
        mesh.update_faces(keep)
        mesh.remove_unreferenced_vertices()
    return len(dup)


def cycles(mesh):
    """Simple cycles of the boundary graph. A vertex where two holes meet is
    walked twice, once per hole, instead of yielding one figure-eight."""
    edges = open_edges(mesh)
    if not edges:
        return []
    adj = {}
    for a, b in edges:
        adj.setdefault(a, []).append(b)
        adj.setdefault(b, []).append(a)
    unused = {tuple(sorted(e)) for e in edges}
    out = []
    while unused:
        a, b = next(iter(unused))
        unused.discard((a, b))
        path = [a, b]
        while True:
            cur = path[-1]
            nxt = [v for v in adj[cur] if tuple(sorted((cur, v))) in unused]
            if not nxt:
                break
            v = nxt[0]
            unused.discard(tuple(sorted((cur, v))))
            if v in path:                       # closed a loop: emit and back up
                i = path.index(v)
                out.append(path[i:])
                path = path[:i + 1] if i else []
                if not path:
                    break
            else:
                path.append(v)
    return [c for c in out if len(c) >= 3]


def fill(mesh, max_span, log):
    added = 0
    for loop in cycles(mesh):
        span = float(np.ptp(mesh.vertices[loop], axis=0).max())
        if span > max_span:
            log(f"  refusing a {len(loop)}-vertex hole spanning {span:.2f} mm "
                f"(over --max-span {max_span}); fix this one in CAD")
            continue
        centroid = mesh.vertices[loop].mean(axis=0)
        tip = len(mesh.vertices)
        faces = [[loop[i], loop[(i + 1) % len(loop)], tip] for i in range(len(loop))]
        mesh = trimesh.Trimesh(vertices=np.vstack([mesh.vertices, centroid]),
                               faces=np.vstack([mesh.faces, faces]), process=False)
        added += len(faces)
        log(f"  filled a {len(loop)}-vertex hole spanning {span:.3f} mm with {len(faces)} triangles")
    return mesh, added


def repair(src, dst, max_span=1.0, log=print):
    before = trimesh.load(src)
    faces0, area0, bounds0 = len(before.faces), before.area, before.bounds.copy()
    keys0 = Counter(tuple(sorted(map(tuple, f))) for f in np.round(before.vertices[before.faces], 4))

    mesh = trimesh.load(src)
    log(f"  deleted {drop_coincident(mesh)} coincident triangles")
    for _ in range(8):
        mesh, added = fill(mesh, max_span, log)
        mesh.merge_vertices()
        if not added or not open_edges(mesh):
            break
    trimesh.repair.fix_normals(mesh)
    mesh.export(dst)

    after = trimesh.load(dst)
    keys1 = Counter(tuple(sorted(map(tuple, f))) for f in np.round(after.vertices[after.faces], 4))
    kept = sum((keys0 & keys1).values())
    log(f"  {kept} of {faces0} original triangles untouched, "
        f"{sum((keys0 - keys1).values())} deleted, {sum((keys1 - keys0).values())} added")
    log(f"  surface {area0:.4f} -> {after.area:.4f} mm2 · "
        f"bounding box moved {float(np.abs(after.bounds - bounds0).max()):.6f} mm")
    log(f"  watertight {after.is_watertight} · a volume {after.is_volume} · "
        f"winding {after.is_winding_consistent}")
    return after.is_volume


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("src")
    ap.add_argument("dst")
    ap.add_argument("--max-span", type=float, default=1.0, metavar="MM",
                    help="refuse to fill a hole wider than this (default 1.0)")
    args = ap.parse_args()
    print(args.src.rsplit("/", 1)[-1])
    sys.exit(0 if repair(args.src, args.dst, args.max_span) else 1)


if __name__ == "__main__":
    main()
