"""Stamp a part's uid into its geometry, so a print can be looked up later.

Every printed part's uid (catalog/parts.json, minted by mint_uid.py) is the
exact thing in your hand: the design revision, not the bytes. Recessing it
into a face means a part found in a drawer a year from now still resolves on
the site -- /u/<uid> names the part, the version, whether it is current.

The stamp is a download-time choice, not a property of the master. generate.py
calls `variants()` once per part and pre-generates a handful of stamped STLs,
one per face the text fits on, ranked by where a stamp prints and hides best;
the part page lets you flip through them, or take the plain master.

Placement is derived from the mesh alone; no part describes where its text
goes:

  1. group the mesh into planar facets (any normal, not just the six axes --
     the bins and the frame crossbeam have their biggest faces at an angle)
  2. rank: the bed face first (a pocket in the first layer prints cleanest and
     is out of sight once assembled), then vertical and upward faces by area,
     downward overhangs last
  3. on each, union the triangles into the face's real 2-D outline -- a hole is
     just area no triangle covers -- and find room for the text in a corner,
     rastering across the face when no corner has room
  4. subtract a shallow prism of the text

Parts too small to carry the text, or with no flat face, get no variants: the
page simply does not offer a stamp.

Reproducibility is the constraint behind the details. The same geometry has to
stamp to the same bytes on any machine or the content-addressed bucket starts
collecting near-duplicates: the font is one pinned file fetched by hash, facet
grouping and corner order are quantised and fixed, and the boolean is
manifold's, which is deterministic for identical input.
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import urllib.request

import numpy as np
import shapely
import shapely.affinity
import trimesh
from matplotlib.font_manager import FontProperties
from matplotlib.textpath import TextPath
from shapely.geometry import Polygon, box

HERE = os.path.dirname(os.path.abspath(__file__))

# Source Code Pro Bold, chosen by measurement (2026-08-22) over every
# monospace font to hand: at this cap height its dotted zero is a 0.79 mm
# pocket inside a 0.77 mm ring of standing plastic, both comfortably above a
# 0.4 mm nozzle, so 0 and O print differently. Its 1, I and l are distinct
# too. (DejaVu Sans, which the renders use, has no dot at all.) OFL-licensed;
# the file lives on the bucket like every other binary and is pinned here.
FONT_URL = "https://img.basically.website/parts/font/source-code-pro-bold-b2095e0d.ttf"
FONT_SHA = "b2095e0d657e6d28dc32444a9dacabab0c9241d0bf39d96371756cc9bdbc3a5f"
FONT_DIR = os.path.join(HERE, "build", "fonts")

CAP = 3.5          # cap height, mm: the smallest a person reads in hand
DEPTH = 0.6        # three 0.2 mm layers; a pocket two layers deep reads as a smudge
SLACK = 0.05       # cutter overshoot past the face so the boolean is clean
MAX_VARIANTS = 4   # faces offered per part; the first is the default
PLANE_TOL = 0.02   # two faces are coplanar within this, mm
NORMAL_TOL = 0.9995

# Anything in this tuple changes every stamped STL when it changes, so it is
# folded into generate.py's memo key and a bump here regenerates the lot.
SIGNATURE = ("engrave-v1", FONT_SHA, CAP, DEPTH, MAX_VARIANTS)


def font_path() -> str:
    """The pinned font, fetched once into gitignored build/fonts/."""
    dest = os.path.join(FONT_DIR, os.path.basename(FONT_URL))
    if os.path.exists(dest) and _sha256(dest) == FONT_SHA:
        return dest
    os.makedirs(FONT_DIR, exist_ok=True)
    req = urllib.request.Request(FONT_URL, headers={
        "User-Agent": "sorter-v2-catalog/1.0 (+https://github.com/basicallysource/sorter-v2)"})
    with urllib.request.urlopen(req, timeout=60) as r, open(dest, "wb") as f:
        shutil.copyfileobj(r, f)
    got = _sha256(dest)
    if got != FONT_SHA:
        os.remove(dest)
        raise RuntimeError(f"font at {FONT_URL} hashed to {got}, expected {FONT_SHA}")
    return dest


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ------------------------------------------------------------------ text
_font_scale = None


def _glyphs(text: str, font: str):
    """The text as a shapely geometry in mm, baseline at y=0, cap height CAP."""
    global _font_scale
    fp = FontProperties(fname=font)
    if _font_scale is None:
        h = _even_odd(TextPath((0, 0), "H", size=10.0, prop=fp))
        _font_scale = 10.0 * CAP / (h.bounds[3] - h.bounds[1])
    return _even_odd(TextPath((0, 0), text, size=_font_scale, prop=fp))


def _even_odd(tp: TextPath):
    """TextPath gives outer rings and holes as sibling polygons (even-odd);
    fold them into real polygons with holes."""
    g = None
    for pts in tp.to_polygons():
        if len(pts) < 3:
            continue
        ring = Polygon(pts)
        if not ring.is_valid:
            ring = ring.buffer(0)
        g = ring if g is None else g.symmetric_difference(ring)
    return g


# ------------------------------------------------------------------ faces
def _frame(d: np.ndarray):
    """(u, v) spanning the face so that text reads upright from outside:
    v is as close to world +Z as the face allows (a vertical face reads
    standing up), or +Y on a horizontal face; u = v x d so u x v = d."""
    up = np.array([0.0, 0.0, 1.0]) if abs(d[2]) < 0.9 else np.array([0.0, 1.0, 0.0])
    v = up - d * (up @ d)
    v /= np.linalg.norm(v)
    u = np.cross(v, d)
    return u, v


def _label(d: np.ndarray) -> str:
    if d[2] > 0.95:
        return "top"
    if d[2] < -0.95:
        return "bottom"
    for i, name in ((0, "x"), (1, "y")):
        if abs(d[i]) > 0.95:
            return f"{'+' if d[i] > 0 else '-'}{name} side"
    return "angled face"


def _facets(mesh: trimesh.Trimesh):
    """Planar facets, largest first: (normal, offset, outline polygon, area,
    is_bed). A facet is a connected run of coplanar triangles (trimesh's
    grouping), so two separate flats on one plane are two candidates."""
    bed_offset = -mesh.bounds[0][2]          # the plane z == min z, as seen along -Z
    out = []
    order = np.argsort(-mesh.facets_area)
    for fi in order[:24]:
        faces = mesh.facets[fi]
        d = mesh.facets_normal[fi].astype(float)
        d /= np.linalg.norm(d)
        # quantise so the same geometry frames the same way on any machine
        d = np.round(d, 6)
        d /= np.linalg.norm(d)
        u, v = _frame(d)
        tri = mesh.triangles[faces]                       # (n, 3, 3)
        offset = float(np.round(np.mean(tri.reshape(-1, 3) @ d), 3))
        pts2 = np.stack([tri.reshape(-1, 3) @ u, tri.reshape(-1, 3) @ v], axis=1).reshape(-1, 3, 2)
        polys = shapely.polygons(np.round(pts2, 4))
        try:
            outline = shapely.coverage_union_all(polys)
        except Exception:
            outline = shapely.union_all(polys)
        outline = outline.buffer(0)
        if outline.is_empty:
            continue
        is_bed = d[2] < -NORMAL_TOL and abs(offset - bed_offset) < PLANE_TOL
        out.append((d, offset, outline, float(mesh.facets_area[fi]), is_bed))
    return out


def _place(outline, text_geom, margin):
    """Lower-left of the text on this face, or None if it does not fit.

    Corners before the middle: a stamp should sit out of the way. The order is
    fixed so the same part always stamps in the same place, which keeps its
    hash stable across runs. A face that is not roughly convex (a plate with a
    hole under its centre and snap arms setting its bounding box) can defeat
    every corner with plenty of clear room left, so raster across it, also in
    a fixed order, before giving up."""
    room = outline.buffer(-margin)
    if room.is_empty:
        return None
    tx0, ty0, tx1, ty1 = text_geom.bounds
    w, h = tx1 - tx0, ty1 - ty0
    rx0, ry0, rx1, ry1 = room.bounds
    if rx1 - rx0 < w or ry1 - ry0 < h:
        return None
    corners = [(rx0, ry0), (rx1 - w, ry0), (rx0, ry1 - h), (rx1 - w, ry1 - h),
               ((rx0 + rx1 - w) / 2, (ry0 + ry1 - h) / 2)]
    for cx, cy in corners:
        if room.contains(box(cx, cy, cx + w, cy + h)):
            return cx - tx0, cy - ty0
    step = 0.5
    for j in range(int((ry1 - h - ry0) / step) + 1):
        for i in range(int((rx1 - w - rx0) / step) + 1):
            cx, cy = rx0 + i * step, ry0 + j * step
            if room.contains(box(cx, cy, cx + w, cy + h)):
                return cx - tx0, cy - ty0
    return None


class NotAVolume(Exception):
    """The mesh is not watertight, so nothing can be subtracted from it."""


def load(stl_path: str) -> trimesh.Trimesh:
    """The part as a closed volume, which is what a boolean needs. An export
    with a few unwelded edges is closed by merging; one with real holes is
    refused -- two parts in the catalog (2026-08) and no repair closes them."""
    mesh = trimesh.load(stl_path, force="mesh", process=True)
    if not mesh.is_volume:
        mesh.merge_vertices(merge_tex=True, merge_norm=True)
        trimesh.repair.fix_normals(mesh)
        trimesh.repair.fill_holes(mesh)
    if not mesh.is_volume:
        raise NotAVolume(f"{os.path.basename(stl_path)} is not watertight; no stamp")
    return mesh


def variants(mesh: trimesh.Trimesh, text: str, font: str | None = None) -> list[dict]:
    """Every face the text fits on, best first, at most MAX_VARIANTS.

    Each is {face, normal, center, size, _placed, _frame}: `face` a short
    label ("bottom", "+x side", "angled face"), `normal` the face's outward
    unit normal, `center` the middle of the text in the STL's own coordinates
    and `size` its [width, height] in mm on the face -- enough for the viewer
    to find the pocket's triangles and paint them, and to fly the camera to
    it -- plus two private keys `cut()` needs."""
    font = font or font_path()
    glyphs = _glyphs(text.upper(), font)
    margin = 0.5 + CAP * 0.25
    ranked = []
    for d, offset, outline, area, is_bed in _facets(mesh):
        rank = 0 if is_bed else 1 if d[2] >= -0.2 else 2
        ranked.append((rank, -area, d, offset, outline))
    ranked.sort(key=lambda t: (t[0], t[1]))
    found = []
    labels = {}
    for rank, _, d, offset, outline in ranked:
        at = _place(outline, glyphs, margin)
        if at is None:
            continue
        placed = shapely.affinity.translate(glyphs, *at)
        u, v = _frame(d)
        cx, cy = (placed.bounds[0] + placed.bounds[2]) / 2, (placed.bounds[1] + placed.bounds[3]) / 2
        center = u * cx + v * cy + d * offset
        base = _label(d)
        n = labels[base] = labels.get(base, 0) + 1
        label = base if n == 1 else f"{base} {n}"
        found.append({
            "face": label,
            "normal": [round(float(x), 4) for x in d],
            "center": [round(float(x), 2) for x in center],
            "size": [round(placed.bounds[2] - placed.bounds[0], 2),
                     round(placed.bounds[3] - placed.bounds[1], 2)],
            "_placed": placed, "_frame": (u, v, d, offset),
        })
        if len(found) >= MAX_VARIANTS:
            break
    return found


def cut(mesh: trimesh.Trimesh, variant: dict) -> trimesh.Trimesh:
    """The mesh with this variant's text recessed into its face."""
    u, v, d, offset = variant["_frame"]
    placed = variant["_placed"]
    pieces = [trimesh.creation.extrude_polygon(g, DEPTH + SLACK)
              for g in getattr(placed, "geoms", [placed])]
    cutter = trimesh.util.concatenate(pieces)
    # local +z is outward: the prism starts DEPTH inside the face and ends
    # SLACK proud of it
    cutter.apply_translation((0, 0, -DEPTH))
    m = np.eye(4)
    m[:3, 0], m[:3, 1], m[:3, 2] = u, v, d
    m[:3, 3] = d * offset
    cutter.apply_transform(m)
    out = trimesh.boolean.difference([mesh, cutter], engine="manifold")
    if out.is_empty or out.volume >= mesh.volume - 1e-6:
        raise RuntimeError(f"stamp on {variant['face']!r} removed nothing")
    return out


def slug(text: str) -> str:
    """Filename-safe face label; the sign survives so +x and -x stay apart."""
    text = text.lower().replace("+", "plus ").replace("-", "minus ")
    return re.sub(r"[^a-z0-9]+", "-", text).strip("-")


def stamp(stl_path: str, text: str, out_dir: str, name: str) -> list[dict]:
    """Stamp `text` on every face it fits, writing <name>-stamped-<face>.stl
    under out_dir. Returns the variants with a `path` each (private keys
    dropped), best first; an empty list when nothing fits. Raises NotAVolume
    for a mesh a boolean cannot work on."""
    mesh = load(stl_path)
    out = []
    os.makedirs(out_dir, exist_ok=True)
    for var in variants(mesh, text):
        path = os.path.join(out_dir, f"{name}-stamped-{slug(var['face'])}.stl")
        cut(mesh, var).export(path)
        out.append({"face": var["face"], "normal": var["normal"],
                    "center": var["center"], "size": var["size"], "path": path})
    return out


if __name__ == "__main__":
    import sys
    import time
    if len(sys.argv) < 3:
        sys.exit("usage: engrave.py <part.stl> <UID> [out_dir]")
    t0 = time.time()
    res = stamp(sys.argv[1], sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else ".",
                os.path.splitext(os.path.basename(sys.argv[1]))[0])
    for r in res:
        print(f"{r['face']:16} normal {r['normal']}  center {r['center']}  size {r['size']}  -> {r['path']}")
    print(f"{len(res)} variant(s) in {time.time() - t0:.1f}s")
