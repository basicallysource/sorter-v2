# Sorter v2 — Parts Calculator

A small web tool for the [Sorter](https://basically.website) build. Pick your
**frame** and **core** colors and a **layer count**, and it tells you exactly how
much filament to order — plus lets you **download the current known-good STLs**.

The grams are not estimates: every part is sliced with OrcaSlicer and the tool
reads the slicer's own filament weight.

## How it works

Two pieces:

1. **`catalog/`** — a Python step driving a slicer. It slices every part once,
   reads `used_g`, renders a thumbnail, copies the STL, and writes the data the
   site reads. Runs wherever the edit happens — against a local OrcaSlicer or
   the asset service's worker — and its outputs are committed with the edit.
   **It never runs in the site build, and never in CI.**
2. **SvelteKit app** (`src/`) — reads the generated data and does all the
   color/layer math in the browser. Fully static; Cloudflare Pages builds it.

```
catalog/
  parts.json            # manifest: every part, its section(s), qty, color role
                        #   geometry is PINNED here by hash, never committed
  generate.py           # the local data-generation step
  engrave.py            # the uid stamp: where it fits on a part, and cutting it
src/lib/data/catalog.generated.json # GENERATED, committed — both sites' input
```

**Nothing binary is in git** — no STL, 3MF, PNG or zip. Every asset lives on
the `sorter-v2-parts` bucket under a hash-bearing filename and is pinned from
the JSON above. See [CLAUDE.md](CLAUDE.md#storage-layout).

## Updating parts

Every part carries a `uid`: a minted 4-character id naming its current
version — the exact thing in your hand, and what a print gets engraved with.
A new version mints a new uid; re-exporting the same design is new bytes (a
new `stl_hash`) under the same uid. Screws and laser-cut parts carry one too.

1. Mint a uid and write the entry in `catalog/parts.json` first — the uid
   exists before the STL does:

   ```
   /opt/homebrew/opt/python@3.11/libexec/bin/python catalog/mint_uid.py
   ```

   Set `uid`, plus `quantities`, `color` (a `role`, or `fixed`, or
   `by_section`), and `optional`. Sections are `feeder`,
   `classification-channel`, `interface`, `chute`, `funnel`, `layer`,
   `lazy-susan`, `bins`, `electronics`. For a new version of an existing
   part: bump `version`, replace `uid` with the fresh one, and add a
   `versions` entry with `"commit": null`; `catalog/stamp_versions.py`
   carries the old uid and hash onto the superseded entry once committed.

2. Upload the STL, named `<part-id>.stl`, and paste the `stl_hash` it
   prints — the file goes on the bucket under the entry's uid, never into
   the tree:

   ```
   python scripts/sync_bucket.py --upload ~/Downloads/chute-core.stl
   ```

3. Run the generator and commit **source and regenerated data together**:

   ```
   /opt/homebrew/opt/python@3.11/libexec/bin/python catalog/generate.py
   ```

   **You do not need OrcaSlicer.** The script picks its slicing backend on its
   own: a local OrcaSlicer when one is installed, otherwise the asset service
   (`ASSET_SERVICE_URL` / `ASSET_SERVICE_TOKEN` in the environment) — it
   uploads the changed masters, the service's worker slices them under the
   same pinned profile, and the reports come back in seconds for anything the
   service has seen before. Nothing regenerates in CI and nothing ever
   commits onto your branch.

   (`--force` re-slices/re-renders everything, `--strict` exits nonzero if
   any part fails.)

4. Push and open a PR. `check-parts` proves the generated data agrees with
   your pins and that every URL serves real bytes; if it is red, you forgot
   step 3 — run it and push again.

### Candidates

A design that is being test-printed and might become the part's next version
goes on the part as a candidate — not as a new part, not as a version:

```json
"candidates": [
  { "uid": "6sk3", "stl_hash": "…", "created_at": "2026-08-22",
    "message": "Shortened and angled. Being tested." }
]
```

Mint its uid, upload the STL under it (`python scripts/sync_bucket.py
--upload output-guide.stl --uid 6sk3`), run the generator. Every STL
downloads as `<part>-<uid>-<hash8>.stl` — from the part page, from a
candidate, and inside the all-parts zip — so the slicer project made from
it, which takes the STL's name, carries the exact version and its settings. It gets sliced,
rendered and listed on the part's page with its own download; it counts
toward nothing and has no version number — numbers are handed out in
adoption order. To promote it: move its `uid` and `stl_hash` up to the part,
bump `version`, add a `versions` entry, delete the candidate line. To iterate
on or drop one: **never delete it** — add `superseded_by` / `superseded_at`
or `rejected_at` and leave its pin, so the uid engraved on any test print
still resolves here. CI fails a change that removes a uid from `parts.json`.

### The id stamp

Every printed part's page offers its STL with the uid recessed into one face
(3.5 mm Source Code Pro Bold, 0.6 mm deep), so a print can be looked up later
at `/u/<uid>` — or typed into the "id on a print" box in the header. Nothing
to author: `catalog/engrave.py` finds every flat face the four characters fit
on, plus cylindrical and conical walls for a part running out of big flat
ones (unrolled, text bent onto the wall; never a bore, never where the text
would wrap more than ~60°), refuses any spot with under 1.6 mm of wall
behind it (1.0 mm for a 0.4 mm pocket), falls back per face from upright
3.5 mm text to sideways, then 2.5 mm, then the shallow pocket, ranks them
(the bed face first, then vertical and upward faces,
overhangs last; large flats before walls before small flats), and
`generate.py` pre-cuts up to four variants per part and
candidate, uploaded like any other artifact. The page opens on the first; the
arrow keys flip through the rest, and unticking "Engrave version id" is the
plain master. The dashboard has the same checkbox over every download it
hands out; "Download all" is the stamped bundle or the plain one
(`all_parts_zip` / `all_parts_plain_zip`) accordingly. A part too small for
the text, or whose mesh is not watertight, simply gets no stamp (the generator
lists them). Stamped bytes are memoized on (geometry, uid, parameters); a
change to the font or the sizes in `engrave.py` re-cuts the catalog.

Assemblies version the same way: every one has a `uid` and `version`, a new
version is an authored *structural* change (a line added or removed, a qty
changed — a member part revving is that part's own history), and a
candidate is a whole alternative bill of materials (`lines`) under test,
whose new parts enter the catalog with empty `quantities` so they count
toward nothing and stay out of the all-parts bundle until promoted.
`stamp_versions.py` carries a snapshot of the superseded lines, each pinned
to the member's uid at the time, so a box as built then can be read back
part by part.

A candidate may carry a `name` — what the slot is called if it is adopted
(the control-board housing candidate renames "Control board mount" on
promotion) — and, like any part, assembly or version, `images`.

### Images

Any part, assembly, candidate or version may carry pictures beyond its
render — an Onshape screenshot, a section view, a photo of it built:

```json
"images": [
  { "url": "https://img.basically.website/parts/img/<name>-<hash8>.png",
    "alt": "What the picture shows", "caption": "Optional, shown under it" }
]
```

Upload the file with `python scripts/sync_bucket.py --upload shot.png` and
paste the URL it prints; the file never enters the repo. The site shows
them as a zoomable strip on the part, hardware and assembly views.

Slicer settings live at the top of `catalog/generate.py` (printer, infill,
supports, etc.); changing them re-slices the whole catalog. Terminology is in
[`notes/TERMINOLOGY.md`](notes/TERMINOLOGY.md).

### Previews

Every branch gets a Cloudflare Pages preview URL, and it is right the first
time: the generated data travels in the same commits as the source that
produced it, so the preview never waits on anything and nothing moves the
branch head underneath you.

## Dev

```
npm install
npm run dev
```

## Build plates

Upload pre-arranged `.3mf` plates with `scripts/sync_bucket.py --upload` and pin
them in `catalog/plates.json`; they are not committed either. `generate.py`
pulls each one's embedded plate previews and reads the parts it contains; downloads
are served from the content-addressed bucket. To cross-link a plate's parts to the catalog, set a part's
`source` field in `parts.json` to the part's original filename as it appears in the 3mf.
