import os
import re
import json
import zipfile
import urllib.request

import numpy as np

LDU_MM = 0.4  # 1 LDraw Unit = 0.4 mm
LDRAW_COMPLETE_URL = "https://library.ldraw.org/library/updates/complete.zip"

# strip a printed/decorated/assembly suffix to the underlying physical mold id
_SUFFIX_RE = re.compile(r'^(\d+[a-z]?)(p[a-z0-9]+|pr\d+|pb\d+|c\d{2}[a-z]?|d\d+|s\d+)$')
_LEADING_NUM_RE = re.compile(r'^(\d+[a-z]?)')


def baseMoldId(part_id: str) -> str | None:
    m = _SUFFIX_RE.match(part_id)
    if m:
        return m.group(1)
    m = _LEADING_NUM_RE.match(part_id)
    return m.group(1) if m else None


def buildFileIndex(ldraw_root: str) -> dict[str, str]:
    index: dict[str, str] = {}
    for root in ("parts", "p"):
        base = os.path.join(ldraw_root, root)
        if not os.path.isdir(base):
            continue
        for dirpath, _dirs, files in os.walk(base):
            rel = os.path.relpath(dirpath, base)
            for f in files:
                if f.lower().endswith(".dat"):
                    key = (os.path.join(rel, f) if rel != "." else f).replace("\\", "/").lower()
                    index[key] = os.path.join(dirpath, f)
    return index


class _Resolver:
    def __init__(self, index: dict[str, str]):
        self.index = index
        self.cache: dict[str, tuple[np.ndarray, np.ndarray]] = {}
        self.geom_cache: dict[str, dict | None] = {}

    def resolve(self, name: str) -> str | None:
        return self.index.get(name.replace("\\", "/").lower())

    def localGeom(self, path: str, depth: int = 0) -> tuple[np.ndarray, np.ndarray]:
        if path in self.cache:
            return self.cache[path]
        if depth > 30:
            return np.zeros((0, 3, 3)), np.zeros((0, 2, 3))
        tris: list[np.ndarray] = []
        segs: list[np.ndarray] = []
        try:
            lines = open(path, encoding="latin-1").read().splitlines()
        except OSError:
            return np.zeros((0, 3, 3)), np.zeros((0, 2, 3))
        for ln in lines:
            p = ln.split()
            if not p:
                continue
            t = p[0]
            if t == "1" and len(p) >= 15:
                vals = list(map(float, p[2:14]))
                x, y, z, a, b, c, d, e, f, g, h, i = vals
                rot = np.array([[a, b, c], [d, e, f], [g, h, i]], float)
                trans = np.array([x, y, z], float)
                sub = self.resolve(" ".join(p[14:]))
                if not sub:
                    continue
                ctris, csegs = self.localGeom(sub, depth + 1)
                if len(ctris):
                    tris.append(ctris @ rot.T + trans)
                if len(csegs):
                    segs.append(csegs @ rot.T + trans)
            elif t == "3" and len(p) >= 11:
                pts = np.array(list(map(float, p[2:11])), float).reshape(3, 3)
                tris.append(pts[None, :, :])
            elif t == "4" and len(p) >= 14:
                q = np.array(list(map(float, p[2:14])), float).reshape(4, 3)
                tris.append(q[[0, 1, 2]][None])
                tris.append(q[[0, 2, 3]][None])
            elif t == "2" and len(p) >= 8:
                s = np.array(list(map(float, p[2:8])), float).reshape(2, 3)
                segs.append(s[None, :, :])
        out_t = np.concatenate(tris) if tris else np.zeros((0, 3, 3))
        out_s = np.concatenate(segs) if segs else np.zeros((0, 2, 3))
        # Only what another file references is kept: primitives and subparts are
        # used thousands of times, while a whole part's triangles, once measured,
        # are not wanted again (its measurement is in geom_cache). Keeping every
        # part's mesh would hold the whole library in memory by the end.
        if depth > 0:
            self.cache[path] = (out_t, out_s)
        return out_t, out_s


def _geomForDat(resolver: _Resolver, path: str) -> dict | None:
    if path in resolver.geom_cache:
        return resolver.geom_cache[path]
    result = _computeGeomForDat(resolver, path)
    resolver.geom_cache[path] = result
    return result


def _computeGeomForDat(resolver: _Resolver, path: str) -> dict | None:
    tris, segs = resolver.localGeom(path)
    verts = []
    if len(tris):
        verts.append(tris.reshape(-1, 3))
    if len(segs):
        verts.append(segs.reshape(-1, 3))
    if not verts:
        return None
    v_mm = np.concatenate(verts) * LDU_MM
    bbox = v_mm.max(0) - v_mm.min(0)
    try:
        from scipy.spatial import ConvexHull
        hv = v_mm[ConvexHull(v_mm).vertices]
        d2 = ((hv[:, None, :] - hv[None, :, :]) ** 2).sum(-1)
        max_extent = float(np.sqrt(d2.max()))
    except Exception:
        max_extent = float(np.sqrt((bbox ** 2).sum()))
    volume = None
    if len(tris):
        tm = tris * LDU_MM
        volume = float(abs(np.einsum('ij,ij->i', tm[:, 0], np.cross(tm[:, 1], tm[:, 2])).sum()) / 6.0)
    dims = sorted((float(bbox[0]), float(bbox[1]), float(bbox[2])), reverse=True)
    return {
        "bbox_x_mm": round(dims[0], 2),
        "bbox_y_mm": round(dims[1], 2),
        "bbox_z_mm": round(dims[2], 2),
        "max_extent_mm": round(max_extent, 2),
        "volume_mm3": round(volume, 1) if volume is not None else None,
    }


def ensureLibrary(library_dir: str, url: str = LDRAW_COMPLETE_URL) -> str:
    root = os.path.join(library_dir, "ldraw")
    if os.path.isdir(os.path.join(root, "parts")):
        return root
    os.makedirs(library_dir, exist_ok=True)
    zip_path = os.path.join(library_dir, "complete.zip")
    if not os.path.exists(zip_path):
        urllib.request.urlretrieve(url, zip_path)
    with zipfile.ZipFile(zip_path) as z:
        z.extractall(library_dir)
    return root


def _bricklinkOnlyItems(conn) -> list[tuple[str, list[str]]]:
    # Every BrickLink item number that is not also a Rebrickable part number,
    # with the Rebrickable parts it stands for: the primary mapping first, then
    # the item's own part, then the rest.
    items: dict[str, list[str]] = {}
    for item_no, part_num in conn.execute(
        "SELECT pbi.item_no, pbi.part_num FROM part_bricklink_ids pbi "
        "LEFT JOIN bricklink_items bi ON bi.item_no = pbi.item_no "
        "WHERE pbi.item_no NOT IN (SELECT part_num FROM parts) "
        "ORDER BY pbi.item_no, pbi.is_primary DESC, (pbi.part_num = bi.part_num) DESC, pbi.part_num"
    ):
        items.setdefault(item_no, []).append(part_num)
    for item_no, part_num in conn.execute(
        "SELECT item_no, part_num FROM bricklink_items "
        "WHERE item_no NOT IN (SELECT part_num FROM parts) ORDER BY item_no"
    ):
        mapped = items.setdefault(item_no, [])
        if part_num not in mapped:
            mapped.append(part_num)
    return sorted(items.items())


def computeAllGeometry(conn, ldraw_root, upsert_fn, computed_at,
                       progress_fn=None, should_stop_fn=None) -> dict:
    # Two passes. The first measures every Rebrickable part. The second gives a
    # row to every BrickLink item number that is not a Rebrickable part number
    # (3040, 3069, 4073: what a sorter predicts), from the parts it maps to, so
    # that a lookup by the number a sorter sends finds a size.
    index = buildFileIndex(ldraw_root)
    resolver = _Resolver(index)
    rows = conn.execute("SELECT part_num, external_ids FROM parts").fetchall()
    items = _bricklinkOnlyItems(conn)
    total = len(rows) + len(items)
    counts = {"direct": 0, "parent": 0, "bricklink": 0}
    measured: dict[str, dict] = {}

    def result(stopped):
        return {"total": total, "computed": sum(counts.values()), **counts, "stopped": stopped}

    def step(i, part_num, geom):
        if geom:
            upsert_fn(conn, part_num, geom, computed_at)
            counts[geom["geometry_source"]] += 1
        if (i + 1) % 1000 == 0:
            conn.commit()
            if progress_fn:
                progress_fn(i + 1, total, f"Geometry: {i+1}/{total} ({sum(counts.values())} computed)")

    for i, (part_num, ext_json) in enumerate(rows):
        if should_stop_fn and should_stop_fn():
            conn.commit()
            return result(True)
        ext = json.loads(ext_json) if ext_json else {}
        ldraw_ids = [str(x) for x in ext.get("LDraw", [])]
        geom = resolveGeometry(resolver, part_num, ldraw_ids)
        if geom:
            measured[part_num] = geom
        step(i, part_num, geom)
    for j, (item_no, part_nums) in enumerate(items):
        if should_stop_fn and should_stop_fn():
            conn.commit()
            return result(True)
        step(len(rows) + j, item_no, resolveBricklinkGeometry(resolver, item_no, part_nums, measured))
    conn.commit()
    return result(False)


def resolveBricklinkGeometry(resolver: _Resolver, item_no: str, part_nums: list[str],
                             measured: dict[str, dict]) -> dict | None:
    # A BrickLink number can stand for several Rebrickable parts (4287 is 4287a,
    # 4287b and 4287c; 30413 is a thin- and a thick-walled panel). A piece
    # predicted as that number may be any of them, so its size is the largest
    # of theirs: a piece is never sent to a bin too small for it. Mostly they
    # are the same mold in variants and the sizes agree; on a tie the first
    # (the primary mapping) is named.
    found = [(pn, measured[pn]) for pn in part_nums if pn in measured]
    if found:
        part_num, geom = max(found, key=lambda f: f[1]["max_extent_mm"])
        return {**geom, "physical_parent_part_num": part_num, "geometry_source": "bricklink"}
    # None of them measured: LDraw's own file of that number (for an old
    # number, often a "~Moved to" that points at the current one).
    return resolveGeometry(resolver, item_no, [])


def resolveGeometry(resolver: _Resolver, part_num: str, ldraw_ids: list[str]) -> dict | None:
    # 1) direct: the part's own LDraw ids or its part_num map to a .dat
    candidates = [part_num] + [str(x) for x in ldraw_ids]
    for cand in candidates:
        path = resolver.resolve(cand + ".dat")
        if path:
            g = _geomForDat(resolver, path)
            if g:
                return {**g, "ldraw_id": cand, "physical_parent_part_num": None, "geometry_source": "direct"}
    # 2) printed/decorated variant -> base physical mold
    for cand in candidates:
        base = baseMoldId(cand)
        if not base or base == cand:
            continue
        path = resolver.resolve(base + ".dat")
        if path:
            g = _geomForDat(resolver, path)
            if g:
                return {**g, "ldraw_id": base, "physical_parent_part_num": base, "geometry_source": "parent"}
    return None
