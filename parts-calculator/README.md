# Sorter v2 — Parts Calculator

A small web tool for the [Sorter](https://basically.website) build. Pick your
**frame** and **core** colors and a **layer count**, and it tells you exactly how
much filament to order — plus lets you **download the current known-good STLs**.

The grams are not estimates: every part is sliced with OrcaSlicer and the tool
reads the slicer's own filament weight.

## How it works

Two pieces:

1. **`slicer/`** — a Python step driving OrcaSlicer. It slices every part once,
   reads `used_g`, renders a thumbnail, copies the STL, and writes the data the
   site reads. Runs on your machine *or* in GitHub Actions
   (`.github/workflows/regen-parts.yml`), which is the canonical environment.
   **It never runs in the site build.**
2. **SvelteKit app** (`src/`) — reads the generated data and does all the
   color/layer math in the browser. Fully static; Cloudflare Pages builds it.

```
slicer/
  parts.json            # manifest: every part, its section(s), qty, color role
                        #   geometry is PINNED here by hash, never committed
  filament.py           # the local data-generation step
src/lib/data/parts.generated.json   # GENERATED, committed — the app's input
```

**Nothing binary is in git** — no STL, 3MF, PNG or zip. Every asset lives on
the `sorter-v2-parts` bucket under a hash-bearing filename and is pinned from
the JSON above. See [CLAUDE.md](CLAUDE.md#storage-layout).

## Updating parts

1. Upload the STL and take the pin it prints — it goes on the bucket, not
   into the tree:

   ```
   python scripts/sync_bucket.py --upload ~/Downloads/new-part.stl
   ```

2. Add/edit entries in `slicer/parts.json` — set its `stl_hash` / `stl_id`
   from step 1, plus `quantities`, `color` (a `role`, or `fixed`, or
   `by_section`), and `optional`. Sections are `feeder`,
   `classification-channel`, `interface`, `chute`, `funnel`, `layer`,
   `lazy-susan`, `bins`, `electronics`.
3. Commit and push on a branch, then open a PR. **You do not need OrcaSlicer.**
   CI slices what changed, renders thumbnails, uploads artifacts, and commits
   the regenerated data back to your branch.

If you *do* have OrcaSlicer installed and want the numbers before pushing, run
it yourself — same script, same pinned settings:

```
/opt/homebrew/opt/python@3.11/libexec/bin/python slicer/filament.py
```

(add `--force` to re-slice/re-render everything, `--strict` to exit nonzero if
any part fails — CI always uses `--strict`.)

Slicer settings live at the top of `slicer/filament.py` (printer, infill,
supports, etc.); changing them re-slices the whole catalog. Terminology is in
[`notes/TERMINOLOGY.md`](notes/TERMINOLOGY.md).

### How long until the preview is right

Every branch gets a Cloudflare Pages preview URL. If your PR touched anything under
`slicer/`, that preview is **wrong until CI finishes** — the app reads the
committed `parts.generated.json`, not `parts.json`, so a changed part shows its
old weight and old thumbnail (and a brand-new part is missing entirely) until
the regen commit lands and Pages rebuilds.

The sequence for a parts change is: push → Pages builds your commit on **stale
data** → CI regenerates and commits back → Pages rebuilds, correct. Budget
minutes, not seconds. A PR touching nothing under `slicer/` skips regen
entirely; a change to slicer settings or the pinned Orca version re-slices the
whole catalog and takes several times longer than a single part.

**If you are automating this**, do not treat the first green check as done — CI
moves the branch head underneath you. Wait for the `regen` check to succeed,
then for the deployment on the *resulting* head SHA. Waiting on
"all checks green" is not reliable: a commit-back can leave a duplicate,
never-executed run parked in `action_required` on the PR.

The preview URL itself is stable per branch, so a link shared early stops being
wrong on its own once the second build lands — it is screenshots and scrapes
taken in that first ~2 minutes that mislead.

## Dev

```
npm install
npm run dev
```

## Build plates

Upload pre-arranged `.3mf` plates with `scripts/sync_bucket.py --upload` and pin
them in `slicer/plates.json`; they are not committed either. `filament.py`
pulls each one's embedded plate previews and reads the parts it contains; downloads
are served from the content-addressed bucket. To cross-link a plate's parts to the catalog, set a part's
`source` field in `parts.json` to the part's original filename as it appears in the 3mf.
