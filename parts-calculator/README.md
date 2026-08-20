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
   **It never runs on Vercel.**
2. **SvelteKit app** (`src/`) — reads the generated data and does all the
   color/layer math in the browser. Fully static; deploys to Vercel as-is.

```
slicer/
  parts.json            # manifest: every part, its section(s), qty, color role
  parts/<section>/*.stl # source STLs (the known-good iteration)
  filament.py           # the local data-generation step
src/lib/data/parts.generated.json   # GENERATED, committed — the app's input
static/renders/*.png                # GENERATED, committed — thumbnails
```

## Updating parts

1. Drop new STLs into `slicer/parts/<section>/` (sections: `feeder`,
   `classification-channel`, `interface`, `chute`, `funnel`, `layer`,
   `lazy-susan`, `bins`, `electronics`).
2. Add/edit entries in `slicer/parts.json` — set `quantities`, `color`
   (a `role`, or `fixed`, or `by_section`), and `optional`.
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

Every branch gets a Vercel preview URL. If your PR touched anything under
`slicer/`, that preview is **wrong until CI finishes** — the app reads the
committed `parts.generated.json`, not `parts.json`, so a changed part shows its
old weight and old thumbnail (and a brand-new part is missing entirely) until
the regen commit lands and Vercel rebuilds.

Measured on this repo (84 parts):

| What the PR changes | CI regen | Preview correct after |
| --- | --- | --- |
| Nothing under `slicer/` (UI, copy, docs) | not triggered | ~25 s |
| One part's STL or `parts.json` entry | ~70 s | **~2 min** |
| N parts | ~65 s + ~4 s each | ~2 min |
| Slicer settings or the pinned Orca version | ~7 min (all parts) | ~7.5 min |

The sequence for a parts change is: push → Vercel builds your commit (~25 s,
**stale data**) → CI regenerates and commits back (~70 s) → Vercel rebuilds
(~25 s, correct).

**If you are automating this**, do not treat the first green Vercel check as
done — CI moves the branch head underneath you. Wait for the `regen` check to
succeed, then for the Vercel deployment on the *resulting* head SHA. Waiting on
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

STLs/3mfs are committed as normal Git objects (not LFS) so Vercel serves the real files.

## Build plates

Drop pre-arranged `.3mf` plates into `slicer/plates/` (auto-discovered). `filament.py`
pulls each one's embedded plate previews and reads the parts it contains; downloads
are served from the content-addressed bucket. To cross-link a plate's parts to the catalog, set a part's
`source` field in `parts.json` to the part's original filename as it appears in the 3mf.
