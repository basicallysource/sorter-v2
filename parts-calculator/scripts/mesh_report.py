#!/usr/bin/env python
"""Find the places an STL is not a closed solid, and picture them.

A part that is not watertight cannot be stamped (engrave.py needs a volume to
subtract from), and a slicer will guess at it rather than fail, so the defect
is worth seeing before the bytes get pinned. Tessellators produce four kinds of
slip, all of them here:

  open edges        a hole: an edge with one face instead of two
  non-manifold      an edge with three or more faces
  zero-area faces   slivers with no extent, usually inside engraved lettering
  coincident pairs  the same triangle twice, facing opposite ways (a flap)

Defect vertices are clustered into sites, since one bad feature makes many bad
edges, and each site is reported with its coordinates in the STL's own frame.

    python scripts/mesh_report.py part.stl [more.stl ...] [--figures DIR]

Exits 1 if anything is wrong with any file, so it can gate a pin.
"""
import argparse
import sys
from collections import Counter

import numpy as np
import trimesh
from scipy.cluster.hierarchy import fcluster, linkage

sys.path.insert(0, __file__.rsplit("/", 1)[0])
import meshfig                                                    # noqa: E402

CLUSTER_MM = 3.0   # defect vertices closer than this describe one bad feature


def defects(mesh):
    """Every defective edge and face, plus the vertices they touch."""
    counts = Counter(tuple(e) for e in mesh.edges_sorted)
    open_edges = np.array([e for e, n in counts.items() if n == 1], int).reshape(-1, 2)
    nonmanifold = np.array([e for e, n in counts.items() if n > 2], int).reshape(-1, 2)
    degenerate = np.where(mesh.area_faces < 1e-9)[0]
    keys = [tuple(sorted(f)) for f in mesh.faces]
    seen = Counter(keys)
    coincident = np.array([i for i, k in enumerate(keys) if seen[k] > 1], int)

    verts = [np.unique(a) for a in (open_edges, nonmanifold) if len(a)]
    verts += [np.unique(mesh.faces[i]) for i in (degenerate, coincident) if len(i)]
    verts = np.unique(np.concatenate(verts)) if verts else np.array([], int)
    return dict(open_edges=open_edges, nonmanifold=nonmanifold,
                degenerate=degenerate, coincident=coincident, verts=verts)


def sites(mesh, d):
    """Defect vertices grouped into bad features, worst (largest) first."""
    if not len(d["verts"]):
        return []
    pts = mesh.vertices[d["verts"]]
    labels = (fcluster(linkage(pts, "single"), t=CLUSTER_MM, criterion="distance")
              if len(pts) > 1 else np.array([1]))
    out = []
    for k in np.unique(labels):
        keep = labels == k
        group, ids = pts[keep], d["verts"][keep]
        counted = {
            "open": int(np.isin(d["open_edges"], ids).any(axis=1).sum()) if len(d["open_edges"]) else 0,
            "non-manifold": int(np.isin(d["nonmanifold"], ids).any(axis=1).sum()) if len(d["nonmanifold"]) else 0,
            "zero-area": int(np.isin(mesh.faces[d["degenerate"]], ids).any(axis=1).sum()) if len(d["degenerate"]) else 0,
            "coincident": int(np.isin(mesh.faces[d["coincident"]], ids).any(axis=1).sum()) if len(d["coincident"]) else 0,
        }
        out.append({"centre": group.mean(axis=0), "size": np.ptp(group, axis=0),
                    "verts": ids, "counts": counted})
    return sorted(out, key=lambda s: -float(s["size"].max()))


def hot_faces(mesh, ids, d):
    hot = np.isin(mesh.faces, ids).any(axis=1)
    for i in np.concatenate([d["degenerate"], d["coincident"]]).astype(int):
        hot[i] = True
    return hot


def figure(mesh, d, site, path, title):
    """One sheet per site: the whole part with the spot ringed, then two zooms."""
    ids = site["verts"]
    hot = hot_faces(mesh, ids, d)
    normals = mesh.face_normals[np.isin(mesh.faces, ids).any(axis=1)]
    n = normals.mean(axis=0) if len(normals) else np.array([0, 0, 1.0])
    if np.linalg.norm(n) < 1e-6:
        n = np.array([0, 0, 1.0])
    cam = meshfig.basis(n / np.linalg.norm(n) + 0.45 * np.array([0.5, -0.7, 0.5]))
    centre = site["centre"]
    whole = float(np.linalg.norm(np.ptp(mesh.bounds, axis=0))) * 1.03
    close = min(max(float(site["size"].max()) * 5, 2.4), 12.0)
    size = (900, 900)
    bad = np.vstack([e for e in (d["open_edges"], d["nonmanifold"]) if len(e)]) \
        if (len(d["open_edges"]) or len(d["nonmanifold"])) else np.zeros((0, 2), int)
    near = bad[np.isin(bad, ids).any(axis=1)] if len(bad) else bad
    panels = [
        ("", meshfig.Panel(mesh, cam, centre, whole, size, hot).ring(centre).finish("whole part, spot ringed")),
        ("", meshfig.Panel(mesh, cam, centre, 16.0, size, hot).ring(centre, 0.09).finish("16 mm across")),
        ("", meshfig.Panel(mesh, cam, centre, close, size, hot).edges(near, (255, 210, 40, 255)).finish(f"{close:.1f} mm across")),
        ("", meshfig.Panel(mesh, cam, centre, close, size, wireframe=True).edges(near, (255, 210, 40, 255)).finish("every triangle drawn")),
    ]
    where = "(%.2f, %.2f, %.2f) mm" % tuple(site["centre"])
    counts = "  ·  ".join(f"{v} {k}" for k, v in site["counts"].items() if v)
    return meshfig.sheet(path, title, f"{where}   ·   {counts}   ·   "
                         + "%.2f x %.2f x %.2f mm" % tuple(site["size"]), panels)


def report(path, figures=None):
    mesh = trimesh.load(path)
    name = path.rsplit("/", 1)[-1]
    d = defects(mesh)
    found = sites(mesh, d)
    print(f"{name}")
    print(f"  {len(mesh.faces)} faces · watertight {mesh.is_watertight} · a volume {mesh.is_volume}"
          f" · winding {mesh.is_winding_consistent}")
    if not found:
        print("  no defects")
        return True
    for i, s in enumerate(found, 1):
        counts = ", ".join(f"{v} {k}" for k, v in s["counts"].items() if v)
        print("  site %d: %s at (%.3f, %.3f, %.3f), %.3f x %.3f x %.3f mm"
              % (i, counts, *s["centre"], *s["size"]))
        if figures:
            out = f"{figures}/{name.rsplit('.', 1)[0]}-site-{i}.png"
            figure(mesh, d, s, out, f"{name} — site {i}")
            print(f"    wrote {out}")
    return False


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("stl", nargs="+")
    ap.add_argument("--figures", metavar="DIR", help="also write a PNG per defect site")
    args = ap.parse_args()
    ok = all([report(p, args.figures) for p in args.stl])
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
