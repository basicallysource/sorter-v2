#!/usr/bin/env python
"""
Data-generation step for the Sorter parts calculator.

Runs anywhere OrcaSlicer is installed -- locally on a Mac, or headlessly in
CI (.github/workflows/regen-parts.yml drives it with a pinned Linux
AppImage via ORCA_BIN/ORCA_PROFILES and commits the outputs back, so PRs
that touch parts get correct data without a local slicer). Never on Vercel.
For every part in parts.json it:
  - slices the STL headlessly with OrcaSlicer using Spencer's settings
  - reads the SLICER'S OWN gram number (used_g) -- not an estimate
  - renders a thumbnail
Then it writes ../src/lib/data/parts.generated.json, which the SvelteKit app
reads to do all the color/layer math in the browser. Every STL/3MF/zip URL in
the generated data is a content-addressed bucket URL (see scripts/
sync_bucket.py, which uploads the bytes); no binary serving copies live in the
repo.

Commit the generated JSON (nothing else changes in git). Re-run whenever a pin
changes or you add/remove parts.

Run:  /opt/homebrew/opt/python@3.11/libexec/bin/python filament.py [--force]
See ../notes/TERMINOLOGY.md for terminology.
"""

import argparse
import hashlib
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import urllib.request
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)

# Large binaries are served from the content-addressed bucket, not from the
# repo. artifact_url() derives the URL from the file's own hash, so it is
# correct before any upload has happened -- scripts/sync_bucket.py only has to
# make sure the bytes are there. See notes/UNIFIED-PARTS-SYSTEM.md section 7.
sys.path.insert(0, os.path.join(REPO, "scripts"))
from sync_bucket import artifact_url, PUBLIC_BASE, sha256 as sha256_file  # noqa: E402

# ---------------------------------------------------------------- config knobs
# Overridable so CI can point at an extracted Linux AppImage. Grams depend on
# the slicer version -- keep CI pinned to the same OrcaSlicer release as local.
ORCA = os.environ.get(
    "ORCA_BIN", "/Applications/OrcaSlicer.app/Contents/MacOS/OrcaSlicer")
PROFILES = os.environ.get(
    "ORCA_PROFILES", "/Applications/OrcaSlicer.app/Contents/Resources/profiles/BBL")

PRINTER = "Bambu Lab A1 0.4 nozzle"      # printer choice barely affects grams
PROCESS = "0.20mm Standard @BBL A1"
FILAMENT = "Bambu PLA Matte @BBL A1"

INFILL_DENSITY = "15%"
INFILL_PATTERN = "adaptivecubic"          # adaptive cubic
# Supports are OFF by default and enabled PER PART via "support": true in parts.json.
# These settings apply only when a part opts in (currently just the stator).
SUPPORT_TYPE = "normal(auto)"             # normal supports, auto-placed
SUPPORT_THRESHOLD = "10"                  # overhang threshold deg
AUTO_ORIENT = False                        # CLI auto-orient is unreliable; use the modeled orientation

# outputs
BUILD = os.path.join(HERE, "build")       # gitignored slicer scratch
CACHE = os.path.join(BUILD, "cache")
PROFILE_DIR = os.path.join(BUILD, "profiles")
DATA_OUT = os.path.join(REPO, "src", "lib", "data", "parts.generated.json")
# NOTHING binary is written into the repo. Masters are fetched from the bucket
# by the stl_hash pinned per part in parts.json; renders, plate thumbnails and
# the all-parts zip are staged under gitignored build/ and uploaded
# content-addressed by sync_bucket.py -- the generated JSON carries their
# bucket URLs. Freshly produced files are the only ones on disk, so an upload
# run only ever pushes new bytes.
MASTERS = os.path.join(BUILD, "masters")
RENDERS_OUT = os.path.join(BUILD, "renders")
VERS_RENDERS_OUT = os.path.join(RENDERS_OUT, "versions")
RENDER_META = os.path.join(CACHE, "renders-meta")   # (stl bytes, hex) -> URL memo
BUNDLE_OUT = os.path.join(BUILD, "bundle")
# build plates: pre-arranged .3mf files pinned by hash in slicer/plates.json
PLATES_SRC = os.path.join(BUILD, "plates")
PLATES_MANIFEST = os.path.join(HERE, "plates.json")
PLATE_THUMB_OUT = os.path.join(BUILD, "plate-thumbs")
PLATES_DATA = os.path.join(REPO, "src", "lib", "data", "plates.generated.json")


# ---------------------------------------------------------------- profile prep
def _load(kind, name):
    p = os.path.join(PROFILES, kind, name + ".json")
    if not os.path.exists(p):
        sys.exit(f"profile not found: {p}\n(is OrcaSlicer installed?)")
    return json.load(open(p))


def _resolve(kind, name):
    d = _load(kind, name)
    inh = d.get("inherits")
    base = _resolve(kind, inh) if inh else {}
    base.update(d)
    return base


def _first(v):
    return v[0] if isinstance(v, list) else v


def lego_hex_map():
    """id -> hex, parsed from the app's bambu-colors.ts (single source of truth)."""
    import re
    txt = open(os.path.join(REPO, "src", "lib", "bambu-colors.ts")).read()
    return {m.group(1): m.group(2)
            for m in re.finditer(r"id:\s*'([^']+)'.*?hex:\s*'(#[0-9A-Fa-f]{6})'", txt)}


def normalize_versions(part):
    """Always return a versions list. If the manifest declares `versions`, pass it
    through; otherwise synthesize a single entry from created_at/version so the app
    can render history uniformly."""
    vs = part.get("versions")
    if vs:
        return vs
    date = part.get("created_at", part.get("date_added", ""))
    entry = {"version": part.get("version", "1"), "date": date,
             "message": "Initial version.", "commit": None}
    # a single-version part can still carry OnShape links at the part level
    if part.get("onshape_version"):
        entry["onshape_version"] = part["onshape_version"]
    if part.get("onshape_doc"):
        entry["onshape_doc"] = part["onshape_doc"]
    return [entry]


def fetch_artifact(sha, dest, prefix="stl", suffix=".stl"):
    """Materialize a content-addressed bucket object at dest, verifying the hash.

    Skips the download when dest already holds the right bytes (gitignored
    build/ keeps these around between local runs)."""
    if os.path.exists(dest) and sha256_file(dest) == sha:
        return
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    url = f"{PUBLIC_BASE}/{prefix}/{sha}{suffix}"
    with urllib.request.urlopen(url, timeout=60) as r, open(dest, "wb") as f:
        shutil.copyfileobj(r, f)
    got = sha256_file(dest)
    if got != sha:
        os.remove(dest)
        raise RuntimeError(f"bucket object {url} hashed to {got}, expected {sha}")


def master_stl(p):
    """Local path of a part's master STL, fetched by its pinned stl_hash."""
    dest = os.path.join(MASTERS, p["id"] + ".stl")
    fetch_artifact(p["stl_hash"], dest)
    return dest


def render_url_for(stl_abs, hexcolor, out_png, force):
    """Bucket URL for this geometry's thumbnail, rendering only when needed.

    Memoized on (STL bytes, hex): the same geometry in the same color is the
    same picture, so its content-addressed URL never changes and nothing needs
    re-rendering or re-uploading. A fresh render lands in build/renders/ where
    sync_bucket.py picks it up."""
    key = hashlib.sha1(open(stl_abs, "rb").read() + hexcolor.encode()).hexdigest()[:16]
    meta = os.path.join(RENDER_META, key + ".json")
    if not force and os.path.exists(meta):
        return json.load(open(meta))["url"]
    render(stl_abs, out_png, hexcolor)
    url = artifact_url(out_png, prefix="render")
    os.makedirs(RENDER_META, exist_ok=True)
    json.dump({"url": url}, open(meta, "w"))
    return url


def archive_versions(parts_by_id, out_parts, profiles, hexmap, role_defaults, force):
    """Give every part version a previewable/downloadable STL.

    The newest version IS the current master file. Every superseded version
    pins its exact geometry via `stl_hash` in parts.json (written by
    stamp_versions.py at supersession time); the bytes are always already on
    the content-addressed bucket, uploaded by the regen that ran while that
    geometry was current. Git history is never consulted. A pre-pin-era
    version with no stl_hash reuses the live asset, the same fallback it
    always had."""
    os.makedirs(VERS_RENDERS_OUT, exist_ok=True)
    os.makedirs(CACHE, exist_ok=True)
    archived = 0
    for out in out_parts:
        p = parts_by_id[out["id"]]
        versions = out.get("versions") or []
        for i, v in enumerate(versions):
            pin = v.get("stl_hash")
            if i == len(versions) - 1 or not pin or pin == p.get("stl_hash"):
                # newest / unpinned / geometry unchanged -> the live part asset
                if out.get("stl"):
                    v["stl"], v["render"], v["grams"] = out["stl"], out["render"], out["grams"]
                continue
            vid = f"{out['id']}-v{v['version']}"
            tmp = os.path.join(CACHE, vid + ".stl")
            fetch_artifact(pin, tmp)
            info = slice_part(tmp, profiles, support=bool(p.get("support", False)), force=force)
            png = os.path.join(VERS_RENDERS_OUT, vid + ".png")
            try:
                v["render"] = render_url_for(tmp, default_hex(p, role_defaults, hexmap), png, force)
            except Exception as e:
                print(f"  ! version render failed for {vid}: {e}")
                v["render"] = None
            v["stl"] = f"{PUBLIC_BASE}/stl/{pin}.stl"
            v["grams"] = info["grams"] if info else None
            archived += 1
    print(f"  {archived} historical part version(s) resolved from pinned stl_hash")


def git_commit_base_url():
    """`https://github.com/owner/repo/commit/` derived from origin, else None."""
    try:
        url = subprocess.run(["git", "-C", REPO, "config", "--get", "remote.origin.url"],
                             capture_output=True, text=True).stdout.strip()
    except Exception:
        return None
    if not url:
        return None
    if url.startswith("git@github.com:"):
        url = "https://github.com/" + url[len("git@github.com:"):]
    if url.endswith(".git"):
        url = url[:-4]
    return url.rstrip("/") + "/commit/" if "github.com" in url else None


def default_hex(part, role_defaults, hexmap):
    """The part's default-color hex (role default / fixed / first split / gray)."""
    c = part.get("color", {})
    if "by_section" in c:                       # resolve to the first section's spec
        c = next(iter(c["by_section"].values()), {})
    cid = None
    if "split" in c:
        cid = c["split"][0]["color"]
    elif "fixed" in c:
        cid = c["fixed"]
    elif "role" in c:
        cid = role_defaults.get(c["role"])
    return hexmap.get(cid, "#cfd3d6") if cid else "#cfd3d6"


def build_profiles():
    os.makedirs(PROFILE_DIR, exist_ok=True)
    machine_path = os.path.join(PROFILE_DIR, "machine.json")
    # Keep the leaf profile (Orca resolves its `inherits`); only override the bed.
    # Slice on a large virtual bed: filament grams are bed-independent (same
    # nozzle/layer/infill/walls), and the CLI rejects ~240mm parts on the real
    # 256mm bed (it demands edge margin the GUI doesn't). This avoids that.
    shutil.copy(os.path.join(PROFILES, "machine", PRINTER + ".json"), machine_path)
    machine = json.load(open(machine_path))
    machine["printable_area"] = ["0x0", "600x0", "600x600", "0x600"]
    machine["printable_height"] = "600"
    machine["bed_exclude_area"] = []
    json.dump(machine, open(machine_path, "w"), indent=1)

    proc = _resolve("process", PROCESS)
    proc.pop("inherits", None)
    proc["name"] = "sorter process"
    proc["sparse_infill_density"] = INFILL_DENSITY
    proc["sparse_infill_pattern"] = INFILL_PATTERN
    proc["skirt_loops"] = "0"                 # no skirt on any part
    # support OFF variant (default)
    proc["enable_support"] = "0"
    process_off = os.path.join(PROFILE_DIR, "process.json")
    json.dump(proc, open(process_off, "w"), indent=1)
    # support ON variant (opt-in parts)
    proc["enable_support"] = "1"
    proc["support_type"] = SUPPORT_TYPE
    proc["support_threshold_angle"] = SUPPORT_THRESHOLD
    process_on = os.path.join(PROFILE_DIR, "process_support.json")
    json.dump(proc, open(process_on, "w"), indent=1)

    fil = _resolve("filament", FILAMENT)
    fil.pop("inherits", None)
    fil["name"] = "sorter filament"
    filament_path = os.path.join(PROFILE_DIR, "filament.json")
    json.dump(fil, open(filament_path, "w"), indent=1)

    density = float(_first(fil.get("filament_density", ["1.24"])))
    cost = float(_first(fil.get("filament_cost", ["0"])))
    return (machine_path, process_off, process_on, filament_path), density, cost


def settings_signature():
    return json.dumps({
        "printer": PRINTER, "process": PROCESS, "filament": FILAMENT,
        "infill": INFILL_DENSITY, "pattern": INFILL_PATTERN,
        "support_params": [SUPPORT_TYPE, SUPPORT_THRESHOLD],
        "orient": AUTO_ORIENT,
    }, sort_keys=True)


BED_CENTER = 300.0   # center of the 600mm virtual bed


def prepare_mesh(stl_abs, out_path):
    """Match what the GUI does on import: weld duplicate vertices, drop the part
    onto the plate (minz->0), and center it. The CLI does NOT auto-drop, so parts
    carrying CAD assembly coordinates (floating / sunk / off-origin) get rejected
    without this. No rotation — the modeled orientation is the print orientation."""
    import trimesh
    m = trimesh.load(stl_abs, process=True)
    m.merge_vertices()
    b = m.bounds
    m.apply_translation([
        BED_CENTER - (b[0][0] + b[1][0]) / 2,
        BED_CENTER - (b[0][1] + b[1][1]) / 2,
        -b[0][2],
    ])
    m.export(out_path)


# ---------------------------------------------------------------- slicing
def slice_part(stl_abs, profiles, support=False, force=False):
    machine_path, process_off, process_on, filament_path = profiles
    process_path = process_on if support else process_off
    stl_bytes = open(stl_abs, "rb").read()
    sig = settings_signature() + ("|support" if support else "|nosupport")
    key = hashlib.sha1(stl_bytes + sig.encode()).hexdigest()[:16]
    cdir = os.path.join(CACHE, key)
    info_path = os.path.join(cdir, "info.json")
    threemf = os.path.join(cdir, "out.3mf")
    fail_path = os.path.join(cdir, "failed")
    if not force:
        if os.path.exists(info_path):
            info = json.load(open(info_path))
            if "support_grams" in info:        # re-parse if schema changed
                return info
        if os.path.exists(threemf):            # re-parse cached slice, no re-slice
            info = parse_3mf(threemf)
            json.dump(info, open(info_path, "w"), indent=1)
            return info
        if os.path.exists(fail_path):
            return None                        # cached failure

    os.makedirs(cdir, exist_ok=True)
    prepared = os.path.join(cdir, "prepared.stl")
    try:
        prepare_mesh(stl_abs, prepared)
    except Exception as e:
        print(f"  ! mesh prep failed for {os.path.basename(stl_abs)}: {e}")
        return None

    cmd = [ORCA,
           "--load-settings", f"{machine_path};{process_path}",
           "--load-filaments", filament_path,
           "--orient", "0", "--arrange", "1", "--slice", "0",
           "--export-3mf", "out.3mf", "--outputdir", cdir, prepared]
    with open(os.path.join(cdir, "slice.log"), "w") as log:
        rc = subprocess.run(cmd, stdout=log, stderr=subprocess.STDOUT).returncode
    if rc != 0 or not os.path.exists(threemf):
        try:
            last = open(os.path.join(cdir, "slice.log")).readlines()[-3:]
            print(f"  ! slicer rc={rc} for {os.path.basename(stl_abs)}: "
                  + " | ".join(l.strip() for l in last if l.strip()))
        except OSError:
            pass
        open(fail_path, "w").close()   # cache the failure
        return None                    # caller decides whether to fall back / report

    info = parse_3mf(threemf)
    json.dump(info, open(info_path, "w"), indent=1)
    # Not persisted (set after the dump): marks a real re-slice, i.e. this
    # geometry/settings combo was new -- callers use it to refresh the render.
    info["fresh"] = True
    return info


def parse_3mf(threemf):
    """Returns total grams, the support portion (from per-feature G-code), cm3, time."""
    grams = cm3 = 0.0
    support_used = False
    seconds = 0
    e_total = e_support = 0.0
    cur_support = False
    relative = True
    with zipfile.ZipFile(threemf) as z:
        si = z.read("Metadata/slice_info.config").decode("utf-8", "ignore")
        for line in si.splitlines():
            if "support_used" in line and 'value="true"' in line:
                support_used = True
            if "used_g=" in line:
                grams += float(line.split('used_g="', 1)[1].split('"', 1)[0])
        gname = next((n for n in z.namelist() if n.endswith(".gcode")), None)
        if gname:
            with z.open(gname) as gf:
                for raw in gf:
                    t = raw.decode("utf-8", "ignore")
                    if t.startswith("; FEATURE:"):
                        cur_support = "support" in t.lower()
                        continue
                    if t.startswith("M82"):
                        relative = False
                    elif t.startswith("M83"):
                        relative = True
                    elif t.startswith("filament used [cm3]") or "filament used [cm3]" in t:
                        cm3 = float(t.split("=")[1])
                    elif "total estimated time:" in t:
                        seconds = _parse_time(t)
                    elif t[:2] in ("G1", "G0"):
                        m = _ERE.search(t)
                        if m and relative:
                            e = float(m.group(1))
                            if e > 0:
                                e_total += e
                                if cur_support:
                                    e_support += e
    support_grams = round(grams * e_support / e_total, 2) if e_total else 0.0
    return {"grams": round(grams, 2), "support_grams": support_grams,
            "cm3": round(cm3, 2), "support_used": support_used, "print_seconds": seconds}


import re as _re
_ERE = _re.compile(r" E(-?[0-9.]+)")


def _parse_time(t):
    seg = t.split("total estimated time:")[-1]
    s = 0
    for tok in seg.replace(";", " ").split():
        if tok.endswith("h"):
            s += int(tok[:-1]) * 3600
        elif tok.endswith("m"):
            s += int(tok[:-1]) * 60
        elif tok.endswith("s"):
            s += int(tok[:-1])
    return s


# ---------------------------------------------------------------- rendering
def render(stl_abs, out_png, hexcolor="#cfd3d6"):
    import numpy as np
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from mpl_toolkits.mplot3d.art3d import Poly3DCollection

    tris = read_triangles(stl_abs)
    base = np.array([int(hexcolor[i:i + 2], 16) / 255 for i in (1, 3, 5)])
    # simple lambert shading so any color (incl. black) shows form
    v0, v1, v2 = tris[:, 0], tris[:, 1], tris[:, 2]
    n = np.cross(v1 - v0, v2 - v0)
    ln = np.linalg.norm(n, axis=1, keepdims=True)
    n = np.divide(n, ln, out=np.zeros_like(n), where=ln != 0)
    light = np.array([0.4, 0.5, 0.85])
    light = light / np.linalg.norm(light)
    shade = 0.45 + 0.55 * np.clip(n @ light, 0, 1)
    facecolors = np.clip(base[None, :] * shade[:, None], 0, 1)
    facecolors = np.concatenate([facecolors, np.ones((len(tris), 1))], axis=1)

    fig = plt.figure(figsize=(3.2, 3.2), dpi=100)
    ax = fig.add_subplot(111, projection="3d")
    ax.add_collection3d(Poly3DCollection(tris, facecolors=facecolors, edgecolor="none"))
    pts = tris.reshape(-1, 3)
    mins, maxs = pts.min(0), pts.max(0)
    ctr = (mins + maxs) / 2
    r = (maxs - mins).max() / 2 or 1
    ax.set_xlim(ctr[0] - r, ctr[0] + r)
    ax.set_ylim(ctr[1] - r, ctr[1] + r)
    ax.set_zlim(ctr[2] - r, ctr[2] + r)
    ax.set_box_aspect((1, 1, 1))
    ax.view_init(elev=22, azim=-60)
    ax.set_axis_off()
    fig.subplots_adjust(left=0, right=1, bottom=0, top=1)
    fig.savefig(out_png, transparent=True)
    plt.close(fig)


def read_triangles(path):
    import numpy as np
    with open(path, "rb") as f:
        head = f.read(80)
        if head[:5] == b"solid" and b"facet" in f.read(200):
            verts = [[float(x) for x in ln.split()[1:4]]
                     for ln in open(path) if ln.strip().startswith("vertex")]
            return np.array(verts, dtype=np.float32).reshape(-1, 3, 3)
        f.seek(80)
        n = struct.unpack("<I", f.read(4))[0]
        data = f.read(n * 50)
    tris = np.empty((n, 9), dtype=np.float32)
    for i in range(n):
        off = i * 50 + 12
        tris[i] = struct.unpack("<9f", data[off:off + 36])
    return tris.reshape(n, 3, 3)


# ---------------------------------------------------------------- main
def build_hardware(manifest):
    """Build the generated COTS records without invoking the slicer."""
    hardware = []
    for p in manifest["parts"]:
        if p.get("kind", "printed") != "cots":
            continue
        # attribute labels are display keys; duplicates read as a contradiction
        labels = [a["label"] for a in p.get("attributes", [])]
        dupes = {label for label in labels if labels.count(label) > 1}
        if dupes:
            raise SystemExit(f"{p['id']}: duplicate attribute label(s) {sorted(dupes)}")
        if p.get("image"):
            raise SystemExit(
                f"{p['id']}: 'image' (a repo file path) is no longer supported -- "
                "images live only on the bucket. Use 'image_url'.")
        hardware.append({
            "id": p["id"],
            "kind": "cots",
            "cots": p.get("cots"),
            "name": p["name"],
            "category": p.get("category"),
            "description": p.get("description", ""),
            "note": p.get("note"),
            "created_at": p.get("created_at", ""),
            "updated_at": p.get("updated_at", p.get("created_at", "")),
            "attributes": p.get("attributes", []),
            "sheet_qty": p.get("sheet_qty"),
            "sheet_qty_text": p.get("sheet_qty_text"),
            # stock material: lines count cut pieces, this converts to lengths to buy
            "stock": p.get("stock"),
            "sourcing": p.get("sourcing"),
            # Marks a part that has an interchangeable alternative (socket vs
            # button head, etc.): true for a bare "Alternative" tag, or a string
            # naming the alternative. Renders the blue "A" badge in the app.
            "alternative": p.get("alternative"),
            # Product images live only on the bucket, authored as a pinned URL.
            # They deliberately never touch git.
            "image": p.get("image_url"),
        })
    return hardware


def build_families(manifest):
    """Build the generated shared-photo families without invoking the slicer."""
    families = []
    for f in manifest.get("families", []):
        if f.get("image"):
            raise SystemExit(
                f"family {f['id']}: 'image' (a repo file path) is no longer "
                "supported -- images live only on the bucket. Use 'image_url'.")
        families.append({
            "id": f["id"],
            "name": f["name"],
            "match": f.get("match", {}),
            "image": f.get("image_url"),
        })
    return families


def check_hardware_refs(manifest, known_ids):
    """Assembly descriptions and joining notes name fasteners as `[[hw:<id>]]` so
    the app can draw the real head symbol and name instead of a bare "M5x16". A
    typo'd id would otherwise reach the site as a raw token in the middle of a
    sentence, so it fails here instead."""
    bad = []
    for asm in manifest.get("assemblies", []):
        texts = [asm.get("description", "")]
        texts += [j.get("note", "") or "" for j in asm.get("joining", []) or []]
        for ref in re.findall(r"\[\[hw:([a-z0-9-]+)\]\]", " ".join(texts)):
            if ref not in known_ids:
                bad.append(f"{asm['id']}: [[hw:{ref}]]")
    if bad:
        sys.exit("assembly description references an unknown part id:\n  "
                 + "\n  ".join(bad))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="re-slice + re-render everything")
    ap.add_argument("--metadata-only", action="store_true",
                    help="refresh authored metadata in existing generated JSON without slicing")
    ap.add_argument("--strict", action="store_true",
                    help="exit nonzero if any part fails to slice (CI uses this "
                         "so broken output can never be committed)")
    args = ap.parse_args()

    manifest = json.load(open(os.path.join(HERE, "parts.json")))
    part_ids = [part["id"] for part in manifest["parts"]]
    duplicate_ids = sorted({part_id for part_id in part_ids if part_ids.count(part_id) > 1})
    if duplicate_ids:
        sys.exit(f"duplicate part id(s): {duplicate_ids}")
    check_hardware_refs(manifest, set(part_ids))
    if args.metadata_only:
        if not os.path.exists(DATA_OUT):
            sys.exit("--metadata-only needs an existing parts.generated.json")
        data = json.load(open(DATA_OUT))
        authored = {p["id"]: p for p in manifest["parts"]
                    if p.get("kind", "printed") == "printed"}
        refreshed = []
        for old in data["parts"]:
            source = authored.get(old["id"])
            if not source:
                refreshed.append(old)
                continue
            # Keep this in the same key order and with the same defaults as the full
            # generator so a metadata refresh produces a focused, reviewable diff.
            refreshed.append({
                "id": source["id"], "name": source["name"],
                **({"aliases": source["aliases"]} if source.get("aliases") else {}),
                "quantities": source.get("quantities", {}),
                "assembly": source.get("assembly"),
                "folder": source.get("folder"),
                "variant_group": source.get("variant_group"),
                "variant_name": source.get("variant_name"),
                "description": source.get("description", ""),
                "version": source.get("version", ""),
                "created_at": source.get("created_at", source.get("date_added", "")),
                "updated_at": source.get("updated_at", source.get("created_at", source.get("date_added", ""))),
                "versions": old.get("versions", normalize_versions(source)),
                "attributes": source.get("attributes", []),
                "grams": old["grams"], "support_grams": old["support_grams"],
                "support_used": old["support_used"],
                "support_intentional": bool(source.get("support", False)),
                "print_seconds": old["print_seconds"],
                "color": source.get("color", {"any": True}),
                "optional": source.get("optional", False),
                "onshape": source.get("onshape"), "info": source.get("info"),
                "low_tolerance": source.get("low_tolerance", False),
                "low_tolerance_note": source.get("low_tolerance_note"),
                "layer_scope": source.get("layer_scope", "all"),
                "requires": source.get("requires", []),
                "stl": old["stl"], "render": old["render"],
            })
        data["parts"] = refreshed
        data["sections"] = manifest["sections"]
        data["changes"] = manifest.get("changes", [])
        data["folders"] = manifest.get("folders", [])
        data["assemblies"] = manifest.get("assemblies", [])
        data["hardware"] = build_hardware(manifest)
        data["families"] = build_families(manifest)
        json.dump(data, open(DATA_OUT, "w"), indent="\t")
        print(f"refreshed authored metadata in {DATA_OUT}")
        return
    profiles, density, cost_per_kg = build_profiles()
    hexmap = lego_hex_map()
    role_defaults = {r["id"]: r["default"] for r in manifest["color_roles"]}
    os.makedirs(RENDERS_OUT, exist_ok=True)
    os.makedirs(os.path.dirname(DATA_OUT), exist_ok=True)

    print(f"settings: {INFILL_DENSITY} {INFILL_PATTERN} | supports per-part "
          f"(off by default; {SUPPORT_TYPE} @{SUPPORT_THRESHOLD}deg when on) | "
          f"{FILAMENT} ({density} g/cm3, ${cost_per_kg}/kg)\n")

    out_parts = []
    zip_members = []
    failed = []
    forced_support = []
    printed = [p for p in manifest["parts"] if p.get("kind", "printed") == "printed"]
    for i, p in enumerate(printed, 1):
        if not p.get("stl_hash"):
            print(f"  ! no stl_hash pinned, skipping: {p['id']}")
            continue
        stl_abs = master_stl(p)
        want = bool(p.get("support", False))
        info = slice_part(stl_abs, profiles, support=want, force=args.force)
        if info is None and not want:
            # Orca makes "floating regions" fatal when support is off. Fall back to
            # support-on so we still get a number; flagged for the user.
            info = slice_part(stl_abs, profiles, support=True, force=args.force)
            if info is not None:
                forced_support.append(p["id"])
        if info is None:
            failed.append(p["id"])
            continue

        png = os.path.join(RENDERS_OUT, p["id"] + ".png")
        try:
            render_url = render_url_for(stl_abs, default_hex(p, role_defaults, hexmap),
                                        png, args.force)
        except Exception as e:
            print(f"  ! render failed for {p['id']}: {e}")
            render_url = None

        zip_members.append((stl_abs, p["id"] + ".stl"))

        out_parts.append({
            "id": p["id"],
            "name": p["name"],
            **({"aliases": p["aliases"]} if p.get("aliases") else {}),
            "quantities": p.get("quantities", {}),
            "assembly": p.get("assembly"),
            "folder": p.get("folder"),
            "variant_group": p.get("variant_group"),
            "variant_name": p.get("variant_name"),
            "description": p.get("description", ""),
            "version": p.get("version", ""),
            "created_at": p.get("created_at", p.get("date_added", "")),
            "updated_at": p.get("updated_at", p.get("created_at", p.get("date_added", ""))),
            "versions": normalize_versions(p),
            "attributes": p.get("attributes", []),
            "grams": info["grams"],
            "support_grams": info.get("support_grams", 0.0),
            "support_used": info["support_used"],
            # true only when the part *opts into* support in the manifest; the slicer
            # may force support on other parts just to slice, but that isn't surfaced.
            "support_intentional": bool(p.get("support", False)),
            "print_seconds": info["print_seconds"],
            "color": p.get("color", {"any": True}),
            "optional": p.get("optional", False),
            "onshape": p.get("onshape"),
            "info": p.get("info"),
            "low_tolerance": p.get("low_tolerance", False),
            "low_tolerance_note": p.get("low_tolerance_note"),
            "layer_scope": p.get("layer_scope", "all"),
            "requires": p.get("requires", []),
            "stl": f"{PUBLIC_BASE}/stl/{p['stl_hash']}.stl",
            "render": render_url,
        })
        sup = " +support" if info["support_used"] else ""
        # [n/total] makes mid-run CI log pings read as real progress
        print(f"  [{i}/{len(printed)}] {p['name']:<26} {info['grams']:7.1f} g/ea{sup}",
              flush=True)

    archive_versions({p["id"]: p for p in printed}, out_parts,
                     profiles, hexmap, role_defaults, args.force)

    # COTS hardware (kind: "cots") is passed through, not sliced. Product images
    # are pinned bucket URLs authored in parts.json; they never live in the repo.
    hardware = build_hardware(manifest)

    # Hardware families: one product photo shared by every cots part whose `cots`
    # block matches. Like all product images, it is a pinned bucket URL.
    families = build_families(manifest)

    # bundle every STL into one downloadable zip (built before the data dict so
    # its content-addressed URL can go into settings)
    # Deterministic zip: fixed timestamps + sorted members, so the bytes (and
    # therefore the content-addressed URL) depend only on the STLs. zf.write()
    # would embed file mtimes, which a fresh CI checkout changes every run.
    os.makedirs(BUNDLE_OUT, exist_ok=True)
    zip_path = os.path.join(BUNDLE_OUT, "all-parts.zip")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for src, name in sorted(zip_members, key=lambda t: t[1]):
            zi = zipfile.ZipInfo(name, date_time=(2020, 1, 1, 0, 0, 0))
            zi.compress_type = zipfile.ZIP_DEFLATED
            zi.external_attr = 0o644 << 16
            zf.writestr(zi, open(src, "rb").read())

    data = {
        "settings": {
            "printer": PRINTER, "process": PROCESS, "filament": FILAMENT,
            "infill_density": INFILL_DENSITY, "infill_pattern": INFILL_PATTERN,
            "support_enabled": False, "support_type": SUPPORT_TYPE,
            "support_threshold_deg": int(SUPPORT_THRESHOLD),
            "density_g_cm3": density, "cost_per_kg": cost_per_kg,
            "commit_base_url": git_commit_base_url(),
            "all_parts_zip": artifact_url(zip_path, prefix="bundle"),
        },
        "sections": manifest["sections"],
        "changes": manifest.get("changes", []),
        "folders": manifest.get("folders", []),
        "color_roles": manifest["color_roles"],
        "families": families,
        "assemblies": manifest.get("assemblies", []),
        "parts": out_parts,
        "hardware": hardware,
    }
    json.dump(data, open(DATA_OUT, "w"), indent="\t")

    print(f"\nwrote {DATA_OUT}")
    print(f"  {len(out_parts)} parts · thumbnails, STLs + bundle -> bucket")
    if forced_support:
        print(f"  ~ {len(forced_support)} part(s) needed support to slice (floating regions "
              f"in modeled orientation); sliced WITH support: {', '.join(forced_support)}")
    if failed:
        print(f"  ! {len(failed)} part(s) FAILED to slice: {', '.join(failed)}")

    process_plates(manifest)

    if args.strict and (failed or not out_parts):
        sys.exit(f"strict mode: {len(failed)} part(s) failed, "
                 f"{len(out_parts)} produced -- refusing to bless this output")


def process_plates(manifest):
    """Build plates from slicer/plates.json: each entry pins a 3mf on the
    bucket by hash. Fetch it, pull its embedded plate previews (uploaded
    content-addressed too), and read the parts it contains (cross-linked to
    manifest parts via each part's optional `source` filename)."""
    import re
    import collections
    os.makedirs(PLATE_THUMB_OUT, exist_ok=True)
    src_to_id = {p["source"]: p["id"] for p in manifest["parts"] if p.get("source")}
    entries = json.load(open(PLATES_MANIFEST))["plates"] if os.path.exists(PLATES_MANIFEST) else []
    out = []
    for entry in entries:
        base = os.path.splitext(entry["file"])[0]
        pid = re.sub(r"[^a-z0-9]+", "-", base.lower()).strip("-")
        f = os.path.join(PLATES_SRC, pid + ".3mf")
        fetch_artifact(entry["hash"], f, prefix="plate", suffix=".3mf")
        thumbs = []
        with zipfile.ZipFile(f) as z:
            for name in sorted(n for n in z.namelist() if re.match(r"Metadata/plate_\d+\.png$", n)):
                num = re.search(r"plate_(\d+)", name).group(1)
                tn = f"{pid}-{num}.png"
                tp = os.path.join(PLATE_THUMB_OUT, tn)
                with open(tp, "wb") as o:
                    o.write(z.read(name))
                thumbs.append(artifact_url(tp, prefix="thumb"))
            cfg = z.read("Metadata/model_settings.config").decode("utf-8", "ignore")
        raw = re.findall(r'<object\b[^>]*>\s*<metadata key="name" value="([^"]+)"', cfg)
        # Skip decorative/label objects (e.g. embossed "text_shape"); real parts are .stl
        counts = collections.Counter(n for n in raw if n.lower().endswith(".stl"))
        parts = []
        for nm, c in counts.items():
            pretty = nm.rsplit(".stl", 1)[0]
            pretty = pretty.split(" - ", 1)[1] if " - " in pretty else pretty
            parts.append({"name": pretty.replace("_", " ").strip(), "count": c,
                          "part_id": src_to_id.get(nm)})
        parts.sort(key=lambda x: -x["count"])
        out.append({"id": pid, "name": base, "download": f"{PUBLIC_BASE}/plate/{entry['hash']}.3mf",
                    "thumbs": thumbs, "parts": parts})
    json.dump(out, open(PLATES_DATA, "w"), indent="\t")
    print(f"  {len(out)} build plate(s) -> plates.generated.json (thumbs -> bucket)")


if __name__ == "__main__":
    main()
