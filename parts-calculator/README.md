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

2. Add/edit entries in `catalog/parts.json` — set its `stl_hash` / `stl_id`
   from step 1, plus `quantities`, `color` (a `role`, or `fixed`, or
   `by_section`), and `optional`. Sections are `feeder`,
   `classification-channel`, `interface`, `chute`, `funnel`, `layer`,
   `lazy-susan`, `bins`, `electronics`.
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
