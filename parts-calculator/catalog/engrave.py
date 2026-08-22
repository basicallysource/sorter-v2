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

  1. find the faces: every planar facet (any normal, not just the six axes --
     the bins and the frame crossbeam have their biggest faces at an angle)
     and every cylindrical wall (the stator, the rotor, a post), found by
     walking the mesh across small dihedral angles and fitting a cylinder
  2. on each, union the triangles into the face's real 2-D outline -- a
     cylinder is unrolled first, which is an isometry, so margins mean the
     same thing -- and find room for the text in a corner, rastering across
     the face when no corner has room
  3. refuse a spot whose wall is too thin to take a 0.6 mm pocket
  4. rank: the bed face first (a pocket in the first layer prints cleanest
     and is out of sight once assembled), then upward and vertical faces,
     downward overhangs last; within that, large flat faces before walls,
     and walls before small flat faces -- a curved surface is where the text
     goes when a part is running out of big flat ones, not a rival to them
  5. subtract a shallow prism of the text; on a cylinder the prism is bent
     onto the wall first, so the pocket is a true 0.6 mm at any radius

Parts too small to carry the text, or with no face, get no variants: the page
simply does not offer a stamp.

Reproducibility is the constraint behind the details. The same geometry has to
stamp to the same bytes on any machine or the content-addressed bucket starts
collecting near-duplicates: the font is one pinned file fetched by hash, facet
grouping, cylinder fits and corner order are quantised and fixed, and the
boolean is manifold's, which is deterministic for identical input.
"""

from __future__ import annotations

import hashlib
import math
import os
import re
import shutil
import urllib.request

import numpy as np
import scipy.sparse
import scipy.sparse.csgraph
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
MIN_WALL = 1.6     # mm of material under the pocket: 0.6 removed, five layers left
MAX_VARIANTS = 4   # faces offered per part; the first is the default
PLANE_TOL = 0.02   # two faces are coplanar within this, mm
NORMAL_TOL = 0.9995
SMOOTH_DEG = 8.0   # adjacent triangles this close in angle are one smooth surface
CYL_TOL = 0.06     # a fitted cylinder's radial residual, mm, for a face to count
MIN_RADIUS = 8.0   # smallest wall considered; MAX_ARC keeps the text legible on it
MAX_ARC = 1.05     # radians the text box may subtend around a cylinder's axis
LARGE_FACE = 600.0 # mm2: a flat face this big is preferred over any wall; a
                   # wall is only offered when a part is running out of these

# Anything in this tuple changes every stamped STL when it changes, so it is
# folded into generate.py's memo key and a bump here regenerates the lot.
SIGNATURE = ("engrave-v2", FONT_SHA, CAP, DEPTH, MAX_VARIANTS, MIN_WALL, MIN_RADIUS)


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


# ------------------------------------------------------------------ frames
def _up_for(n: np.ndarray) -> np.ndarray:
    """Which way is up on a face: world +Z unless the face is nearly
    horizontal, then +Y. A vertical face reads standing up."""
    return np.array([0.0, 0.0, 1.0]) if abs(n[2]) < 0.9 else np.array([0.0, 1.0, 0.0])


def _frame(d: np.ndarray):
    """(u, v) spanning a flat face so that text reads upright from outside:
    v is as close to up as the face allows, u = v x d so u x v = d."""
    up = _up_for(d)
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


def _outline(pts2: np.ndarray):
    """Union of (n, 3, 2) triangles into the real 2-D outline of a face."""
    polys = shapely.polygons(np.round(pts2, 4))
    try:
        outline = shapely.coverage_union_all(polys)
    except Exception:
        outline = shapely.union_all(polys)
    return outline.buffer(0)


# ------------------------------------------------------------------ flat faces
def _flat_faces(mesh: trimesh.Trimesh):
    """Planar facets, largest first, as Face objects. A facet is a connected
    run of coplanar triangles (trimesh's grouping), so two separate flats on
    one plane are two candidates."""
    bed_offset = -mesh.bounds[0][2]          # the plane z == min z, as seen along -Z
    out = []
    order = np.argsort(-mesh.facets_area)
    for fi in order[:24]:
        faces = mesh.facets[fi]
        d = mesh.facets_normal[fi].astype(float)
        d = np.round(d / np.linalg.norm(d), 6)
        d /= np.linalg.norm(d)
        u, v = _frame(d)
        tri = mesh.triangles[faces]
        offset = float(np.round(np.mean(tri.reshape(-1, 3) @ d), 3))
        pts2 = np.stack([tri.reshape(-1, 3) @ u, tri.reshape(-1, 3) @ v], axis=1).reshape(-1, 3, 2)
        outline = _outline(pts2)
        if outline.is_empty:
            continue
        is_bed = d[2] < -NORMAL_TOL and abs(offset - bed_offset) < PLANE_TOL
        out.append(FlatFace(d, offset, u, v, outline, float(mesh.facets_area[fi]), is_bed))
    return out


class FlatFace:
    def __init__(self, d, offset, u, v, outline, area, is_bed):
        self.d, self.offset, self.u, self.v = d, offset, u, v
        self.outline, self.area, self.is_bed = outline, area, is_bed
        self.label = _label(d)

    def text_rotation(self):
        return 0.0                      # the frame already has v = up

    def world(self, x, y, z):
        """Unrolled (x, y) and outward z -> STL coordinates."""
        return self.u * x + self.v * y + self.d * (self.offset + z)

    def normal_at(self, x, y):
        return self.d

    def describe(self):
        return {}


# ------------------------------------------------------------------ round walls
class RoundFace:
    """A wall that is a surface of revolution: a cylinder or a cone, about
    axis `a` through point `c`, radius r0 at c growing by `slope` per mm
    along the axis (0 for a cylinder). `sign` is +1 for a convex wall
    (outward normal points away from the axis) and -1 for a bore. Both are
    developable, so the wall unrolls onto a plane without stretching and
    text placed on the unrolled outline keeps its true size and margins.

    Unrolled coordinates: on a cylinder (s, y) = (sign * R * (theta - theta0),
    axial); on a cone the sector (rho * sin(phi), -rho * cos(phi)) with rho
    the slant distance from the apex and phi = sign * (theta - theta0) *
    sin(gamma). Either way (e_x, e_y, outward) is right-handed, so text reads
    correctly from outside a wall and from inside a bore."""

    def __init__(self, a, c, r0, slope, sign, theta0, e1, e2, outline, area, tilt):
        self.a, self.c, self.r0, self.slope, self.sign = a, c, r0, slope, sign
        self.theta0, self.e1, self.e2 = theta0, e1, e2
        self.outline, self.area, self.is_bed = outline, area, False
        self.kind = "cylinder" if slope == 0 else "cone"
        self.label = ("outer" if sign > 0 else "inner") + " wall"
        self._rot = tilt
        if slope:
            # apex: where the radius reaches zero along the axis
            self.gamma = math.atan(abs(slope))          # generator angle from the axis
            t_apex = -r0 / slope
            self.apex = c + a * t_apex
            self.d_ap = 1.0 if t_apex > 0 else -1.0     # apex lies toward +a or -a

    def _radial(self, theta):
        return math.cos(theta) * self.e1 + math.sin(theta) * self.e2

    def _theta(self, x, y):
        if self.kind == "cylinder":
            return self.theta0 + self.sign * x / self.r0
        phi = math.atan2(x, -y)
        return self.theta0 + phi / (self.sign * math.sin(self.gamma))

    def text_rotation(self):
        return self._rot

    def world(self, x, y, z):
        theta = self._theta(x, y)
        r = self._radial(theta)
        if self.kind == "cylinder":
            return self.c + self.a * y + r * (self.r0 + self.sign * z)
        g = -self.d_ap * self.a * math.cos(self.gamma) + r * math.sin(self.gamma)
        n_out = r * math.cos(self.gamma) + self.d_ap * self.a * math.sin(self.gamma)
        return self.apex + g * math.hypot(x, y) + n_out * (self.sign * z)

    def normal_at(self, x, y):
        theta = self._theta(x, y)
        r = self._radial(theta)
        if self.kind == "cylinder":
            return self.sign * r
        return self.sign * (r * math.cos(self.gamma) + self.d_ap * self.a * math.sin(self.gamma))

    def radius_at(self, x, y):
        """Distance from the axis at this spot: what the text wraps around."""
        if self.kind == "cylinder":
            return self.r0
        return math.hypot(x, y) * math.sin(self.gamma)

    def describe(self):
        return {"surface": {"axis": [round(float(t), 5) for t in self.a],
                            "point": [round(float(t), 3) for t in self.c],
                            "r0": round(float(self.r0), 3), "slope": round(float(self.slope), 5),
                            "sign": self.sign}}


def _fit_round(mesh, faces):
    """Least-squares surface of revolution through a set of triangles.

    The axis is the direction the normals vary least along (the smallest
    eigenvector of their area-weighted covariance); on a cylinder the normals
    lie in the plane across it, on a cone they tilt toward it by a constant
    angle. Faces whose tilt is off the dominant value are dropped first --
    that is what splits a wall from the fillets and flats a smooth walk
    merged it with -- then, since the tilt fixes the slope of radius against
    height, the dominant intercept picks the wall out of other walls on the
    same axis (a post's shaft from its flared ends), and the line is refined
    with a few Gauss-Newton steps. Returns (axis, point on axis, r0, slope,
    sign, inlier faces) or None."""
    n = mesh.face_normals[faces]
    w = mesh.area_faces[faces]
    cen = mesh.triangles_center[faces]
    nbar = (n * w[:, None]).sum(0) / w.sum()
    cov = ((n - nbar) * w[:, None]).T @ (n - nbar) / w.sum()
    vals, vecs = np.linalg.eigh(cov)
    if vals[1] < 5e-3 or vals[0] > 0.15 * vals[1]:
        return None                              # too little turn to tell the axis
    a = vecs[:, 0] / np.linalg.norm(vecs[:, 0])
    if a[2] < 0 or (a[2] == 0 and (a[1] < 0 or (a[1] == 0 and a[0] < 0))):
        a = -a                                   # a fixed sign, for reproducibility
    tilt = n @ a
    hist, edges = np.histogram(tilt, bins=np.arange(-1.0, 1.021, 0.02), weights=w)
    mode = edges[hist.argmax()] + 0.01
    keep = np.abs(tilt - mode) < 0.035
    for _ in range(2):
        mode = float(np.average(tilt[keep], weights=w[keep]))
        keep = np.abs(tilt - mode) < 0.035
    if w[keep].sum() < LARGE_FACE:
        return None
    e1 = np.cross(a, np.array([0.0, 0.0, 1.0]) if abs(a[2]) < 0.9 else np.array([1.0, 0.0, 0.0]))
    e1 /= np.linalg.norm(e1)
    e2 = np.cross(a, e1)
    px, py, t = cen @ e1, cen @ e2, cen @ a
    # start from an algebraic circle through the kept centroids: its centre is
    # about right even when they sit at several radii
    k = keep
    A = np.stack([2 * px[k], 2 * py[k], np.ones(k.sum())], axis=1) * np.sqrt(w[k])[:, None]
    b = (px[k] ** 2 + py[k] ** 2) * np.sqrt(w[k])
    (cx, cy, q), *_ = np.linalg.lstsq(A, b, rcond=None)
    # the tilt fixes |dr/dt|: a cylinder's is 0, a cone's is cot(tilt). With
    # the slope known up to sign, every face has an intercept r - slope * t,
    # and the wall is the intercept most of the area agrees on
    r_all = np.hypot(px - cx, py - cy)
    mag = 0.0 if abs(mode) < 0.02 else math.sqrt(max(1 - mode * mode, 0.0)) / abs(mode)
    best = None
    for s0 in ((0.0,) if mag == 0.0 else (mag, -mag)):
        icept = r_all - s0 * t
        lo, hi = icept[keep].min(), icept[keep].max()
        hist, edges = np.histogram(icept[keep], bins=max(int((hi - lo) / 0.25) + 1, 1), range=(lo, lo + max(hi - lo, 0.25)), weights=w[keep])
        centre = edges[hist.argmax()] + 0.125
        inl = keep & (np.abs(icept - centre) < 0.3)
        if best is None or w[inl].sum() > best[0]:
            best = (w[inl].sum(), s0, centre, inl)
    _, slope, r0, k = best
    if w[k].sum() < LARGE_FACE:
        return None
    for _ in range(8):
        dx, dy = px[k] - cx, py[k] - cy
        r = np.hypot(dx, dy)
        e = r - r0 - slope * t[k]
        J = np.stack([-dx / r, -dy / r, -np.ones_like(r), -t[k]], axis=1)
        Wj = J * w[k][:, None]
        try:
            step = np.linalg.solve(Wj.T @ J + 1e-9 * np.eye(4), -(Wj.T @ e))
        except np.linalg.LinAlgError:
            return None
        cx, cy, r0, slope = cx + step[0], cy + step[1], r0 + step[2], slope + step[3]
        r_all = np.hypot(px - cx, py - cy)
        resid = np.abs(r_all - r0 - slope * t)
        k = keep & (resid < max(CYL_TOL, 0.002 * abs(r0)))
        if k.sum() < 12:
            return None
    if abs(slope) < 0.004:
        slope = 0.0
    if abs(slope) > 3.0:
        return None                              # nearly a flat disc; not a wall
    # re-origin on the axis at the wall's mid-height so the numbers stay small
    t_mid = float(np.average(t[k], weights=w[k]))
    c = e1 * cx + e2 * cy + a * t_mid
    r0 = r0 + slope * t_mid
    if r0 < MIN_RADIUS:
        return None
    radial = cen[k] - np.outer(t[k], a) - (e1 * cx + e2 * cy)
    sign = 1 if float(np.mean(np.einsum("ij,ij->i", n[k], radial))) > 0 else -1
    return (np.round(a, 6), np.round(c, 4), round(float(r0), 4), round(float(slope), 6),
            sign, faces[k])


def _round_faces(mesh: trimesh.Trimesh):
    """Cylindrical and conical walls, largest first. Walk the mesh across
    edges whose dihedral angle is small (a tessellated wall steps a degree or
    two per strip), fit a surface of revolution to each smooth region, keep
    the inliers that connect to its largest piece, and unroll them."""
    fa = mesh.face_adjacency
    smooth = mesh.face_adjacency_angles < math.radians(SMOOTH_DEG)
    n = len(mesh.faces)
    g = scipy.sparse.coo_matrix((np.ones(smooth.sum()), (fa[smooth, 0], fa[smooth, 1])), shape=(n, n))
    k, lab = scipy.sparse.csgraph.connected_components(g, directed=False)
    areas = np.bincount(lab, weights=mesh.area_faces, minlength=k)
    out = []
    for comp in np.argsort(-areas)[:12]:
        faces = np.flatnonzero(lab == comp)
        # a flat facet is also "smooth"; only a region whose normals turn is a wall
        if len(faces) < 12 or areas[comp] < LARGE_FACE or np.linalg.norm(mesh.face_normals[faces].mean(0)) > 0.97:
            continue
        fit = _fit_round(mesh, faces)
        if fit is None:
            continue
        a, c, r0, slope, sign, inl = fit
        # keep the largest connected piece of inliers: one wall, not every
        # wall of that radius on that axis
        mask = np.zeros(n, bool)
        mask[inl] = True
        e = smooth & mask[fa[:, 0]] & mask[fa[:, 1]]
        g2 = scipy.sparse.coo_matrix((np.ones(e.sum()), (fa[e, 0], fa[e, 1])), shape=(n, n))
        _, lab2 = scipy.sparse.csgraph.connected_components(g2, directed=False)
        piece = np.bincount(lab2[inl], weights=mesh.area_faces[inl]).argmax()
        inl = inl[lab2[inl] == piece]
        area = float(mesh.area_faces[inl].sum())
        if area < LARGE_FACE:
            continue
        e1 = np.cross(a, np.array([0.0, 0.0, 1.0]) if abs(a[2]) < 0.9 else np.array([1.0, 0.0, 0.0]))
        e1 /= np.linalg.norm(e1)
        e2 = np.cross(a, e1)
        tri = mesh.triangles[inl]
        rel = tri.reshape(-1, 3) - c
        cen = mesh.triangles_center[inl] - c
        cen_rad = cen - np.outer(cen @ a, a)
        # seam: opposite the wall's mean direction, so a partial wall never
        # straddles it (a full wall has to straddle it somewhere)
        cang = np.arctan2(cen_rad @ e2, cen_rad @ e1)
        mean_dir = np.array([np.cos(cang).mean(), np.sin(cang).mean()])
        theta0 = float(np.round(math.atan2(mean_dir[1], mean_dir[0]) if np.linalg.norm(mean_dir) > 0.05 else 0.0, 6))
        # unroll each triangle about its own centroid angle so the seam only
        # cuts the outline where a triangle actually crosses it
        ang = np.arctan2(rel @ e2, rel @ e1).reshape(-1, 3)
        d = (ang - cang[:, None] + np.pi) % (2 * np.pi) - np.pi
        theta = cang[:, None] + d
        rel_t = (theta - theta0 + np.pi) % (2 * np.pi) - np.pi
        wrap = np.abs(rel_t - rel_t.mean(1, keepdims=True)) > np.pi
        rel_t = np.where(wrap, rel_t - 2 * np.pi * np.sign(rel_t), rel_t)
        face = RoundFace(a, c, r0, slope, sign, theta0, e1, e2, None, area, 0.0)
        if face.kind == "cylinder":
            pts2 = np.stack([sign * r0 * rel_t, (rel @ a).reshape(-1, 3)], axis=2)
        else:
            rho = np.linalg.norm(tri.reshape(-1, 3) - face.apex, axis=1).reshape(-1, 3)
            phi = sign * rel_t * math.sin(face.gamma)
            pts2 = np.stack([rho * np.sin(phi), -rho * np.cos(phi)], axis=2)
        outline = _outline(pts2)
        if outline.is_empty:
            continue
        face.outline = outline
        # which way is up in the unrolled plane, measured at the wall's middle
        r_c = face._radial(theta0)
        t_c = np.cross(a, r_c)
        n_c = face.normal_at(0.0, 0.0) if face.kind == "cylinder" else \
            sign * (r_c * math.cos(face.gamma) + face.d_ap * a * math.sin(face.gamma))
        up = _up_for(n_c)
        up = up - n_c * (up @ n_c)
        if np.linalg.norm(up) < 0.3:
            up = np.array([0.0, 1.0, 0.0]) if abs(n_c[2]) >= 0.9 else np.array([1.0, 0.0, 0.0])
            up = up - n_c * (up @ n_c)
        up /= np.linalg.norm(up)
        ey = a if face.kind == "cylinder" else \
            (face.d_ap * a * math.cos(face.gamma) - r_c * math.sin(face.gamma))   # toward the apex
        v2 = np.array([up @ (sign * t_c), up @ ey])
        face._rot = round(math.degrees(math.atan2(v2[1], v2[0])) - 90.0, 3)
        out.append(face)
    return out


# ------------------------------------------------------------------ placing
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


def _wall_thickness(mesh, face, placed):
    """Material under the text box: the nearest surface behind each of its
    corners and its centre, looking straight in. A pocket into a wall
    thinner than MIN_WALL leaves too little to print."""
    x0, y0, x1, y1 = placed.bounds
    pts = [((x0 + x1) / 2, (y0 + y1) / 2), (x0, y0), (x1, y0), (x0, y1), (x1, y1)]
    origins, dirs = [], []
    for x, y in pts:
        n = face.normal_at(x, y)
        origins.append(face.world(x, y, -0.05))
        dirs.append(-n)
    loc, idx, _ = mesh.ray.intersects_location(np.array(origins), np.array(dirs), multiple_hits=False)
    if len(idx) < len(pts):
        return 0.0                      # a ray escaped: we are not inside a wall
    dist = np.linalg.norm(loc - np.array(origins)[idx], axis=1) + 0.05
    return float(dist.min())


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

    Each is {face, normal, center, size, [surface], _placed, _face}: `face` a
    short label ("bottom", "+x side", "angled face", "outer wall"), `normal`
    the outward unit normal at the text, `center` the middle of the text in
    the STL's own coordinates, `size` its [width, height] in mm, and on a
    wall the surface of revolution it sits on -- enough for the viewer to
    find the pocket's triangles and paint them, and to fly the camera to it
    -- plus two private keys `cut()` needs."""
    font = font or font_path()
    glyphs = _glyphs(text.upper(), font)
    margin = 0.5 + CAP * 0.25
    found = []
    for face in _flat_faces(mesh) + _round_faces(mesh):
        if isinstance(face, RoundFace) and face.sign < 0:
            continue                    # a bore is a fit far more often than a wall is
        placed = None
        # on a wall, text that would wrap too far around the axis is turned
        # sideways to run along it instead (the print on a pen)
        for extra in ((0.0,) if not isinstance(face, RoundFace) else (0.0, 90.0)):
            rot = face.text_rotation() + extra
            tg = glyphs if rot == 0 else shapely.affinity.rotate(glyphs, rot, origin=(0, 0))
            at = _place(face.outline, tg, margin)
            if at is None:
                continue
            cand = shapely.affinity.translate(tg, *at)
            if isinstance(face, RoundFace):
                x0, y0, x1, y1 = cand.bounds
                if (x1 - x0) / face.radius_at((x0 + x1) / 2, (y0 + y1) / 2) > MAX_ARC:
                    continue
            placed = cand
            break
        if placed is None:
            continue
        x0, y0, x1, y1 = placed.bounds
        if _wall_thickness(mesh, face, placed) < MIN_WALL:
            continue
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        n = face.normal_at(cx, cy)
        rank = 0 if face.is_bed else 1 if n[2] >= -0.2 else 2
        tier = 1 if isinstance(face, RoundFace) else 0 if face.area >= LARGE_FACE else 2
        found.append((rank, tier, -face.area, face, placed, n, (cx, cy)))
    found.sort(key=lambda t: (t[0], t[1], t[2]))
    out, labels = [], {}
    for rank, tier, _, face, placed, n, (cx, cy) in found[:MAX_VARIANTS]:
        k = labels[face.label] = labels.get(face.label, 0) + 1
        label = face.label if k == 1 else f"{face.label} {k}"
        x0, y0, x1, y1 = placed.bounds
        out.append({
            "face": label,
            "normal": [round(float(t), 4) for t in n],
            "center": [round(float(t), 2) for t in face.world(cx, cy, 0.0)],
            "size": [round(x1 - x0, 2), round(y1 - y0, 2)],
            **face.describe(),
            "_placed": placed, "_face": face,
        })
    return out


def cut(mesh: trimesh.Trimesh, variant: dict) -> trimesh.Trimesh:
    """The mesh with this variant's text recessed into its face."""
    face, placed = variant["_face"], variant["_placed"]
    pieces = [trimesh.creation.extrude_polygon(g, DEPTH + SLACK)
              for g in getattr(placed, "geoms", [placed])]
    cutter = trimesh.util.concatenate(pieces)
    # local +z is outward: the prism starts DEPTH inside the face and ends
    # SLACK proud of it. Mapping every vertex through the face (a plane, or a
    # cylinder that bends the prism onto the wall) puts it in STL space.
    cutter.apply_translation((0, 0, -DEPTH))
    v = cutter.vertices
    cutter.vertices = np.array([face.world(x, y, z) for x, y, z in v])
    out = trimesh.boolean.difference([mesh, cutter], engine="manifold")
    if out.is_empty or out.volume >= mesh.volume - 1e-6:
        raise RuntimeError(f"stamp on {variant['face']!r} removed nothing")
    return out


def slug(text: str) -> str:
    """Filename-safe face label; the sign survives so +x and -x stay apart."""
    text = text.lower().replace("+", "plus ").replace("-", "minus ")
    return re.sub(r"[^a-z0-9]+", "-", text).strip("-")


PUBLIC_KEYS = ("face", "normal", "center", "size", "surface")


def stamp(stl_path: str, text: str, out_dir: str, name: str) -> list[dict]:
    """Stamp `text` on every face it fits, writing <name>-stamped-<face>.stl
    under out_dir. Returns the variants with a `path` each (private keys
    dropped), best first; an empty list when nothing fits. Raises NotAVolume
    for a mesh a boolean cannot work on."""
    mesh = load(stl_path)
    out, seen = [], set()
    os.makedirs(out_dir, exist_ok=True)
    for var in variants(mesh, text):
        path = os.path.join(out_dir, f"{name}-stamped-{slug(var['face'])}.stl")
        cut(mesh, var).export(path)
        # two faces can come out as one cut (a face the mesh lists twice, say);
        # the second would be a duplicate download under a second name
        digest = _sha256(path)
        if digest in seen:
            os.remove(path)
            continue
        seen.add(digest)
        out.append({**{k: var[k] for k in PUBLIC_KEYS if k in var}, "path": path})
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
