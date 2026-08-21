# CLAUDE.md

Working rules for this repo. Read `notes/UNIFIED-PARTS-SYSTEM.md` before
making structural changes to the parts data model — it is the design spec
for where this is heading (unified registry across this repo, the docs, and
the BOM spreadsheet).

## What this is

A SvelteKit static site that tells you what to print/buy for a Sorter V2
build. Two halves:

- **`slicer/`** — Python + OrcaSlicer. Slices every part, reads the
  slicer's real `used_g`, renders thumbnails, writes the site's data.
  **Never runs on Vercel.** Runs locally on the Mac *or* in CI:
  `.github/workflows/regen-parts.yml` re-runs it (pinned Linux AppImage,
  headless) on any PR/push touching slicer inputs and commits the
  regenerated outputs back to the branch — so agents/bots can change parts
  data with no local slicer, and Vercel previews show the branch's own
  correct data. CI is the canonical slicer environment; slice results are
  memoized per (STL bytes + settings), so warm runs only re-slice what
  changed.
- **`src/`** — the app. Reads generated JSON, does all math in the browser.
  Fully static.

## Deploying

**Pushing/merging to `main` auto-deploys** (Vercel builds `main` on every
push). There is no separate deploy step — a commit that lands on `main` is
live. Treat every push to `main` as a production release.

## PR previews — when they are actually valid

Every branch gets a Vercel preview. **If the PR touched anything under
`slicer/`, that preview is wrong until CI's regen commit lands**: the app
reads the committed `parts.generated.json`, not `parts.json`, so a changed
part shows its old grams and old thumbnail, and a new part is missing.

Budget **~2 minutes** from push to a correct preview for a parts change
(~25 s Vercel on stale data → ~70 s regen → ~25 s Vercel on correct data).
A slicer-settings change re-slices all 84 parts: ~7.5 min. A PR touching
nothing under `slicer/` skips regen entirely: ~25 s. Full table with the
per-part cost is in [README.md](README.md#how-long-until-the-preview-is-right).

Do not report a preview as ready — or screenshot it — on the first green
Vercel check. CI moves the branch head underneath you. Wait for the `regen`
check to succeed, *then* the Vercel deployment on the resulting head SHA.
Do not wait on "all checks green": a commit-back can park a duplicate,
never-executed run in `action_required` on the PR forever.

Sharing a preview *link* early is fine — the URL is stable per branch and
self-corrects once the second build lands.

## Hard rules

**Never hand-edit generated files.** `src/lib/data/parts.generated.json`,
`src/lib/data/plates.generated.json`, and `slicer/artifacts.json` are all
outputs. The authored source of truth is `slicer/parts.json`. Edit that and
re-run the generator.

**Filament weights are measured, never estimated.** Grams come from
OrcaSlicer's own output. Do not compute weight from volume/density.

**Python is invoked by full path** (no venvs):
```
/opt/homebrew/opt/python@3.11/libexec/bin/python slicer/filament.py
```

## Artifacts and the bucket

Large binaries (STLs, 3MFs) sync to a DigitalOcean Space,
**content-addressed** at `stl/<sha256>.stl`:

```
python scripts/sync_bucket.py --dry-run   # report only
python scripts/sync_bucket.py             # upload missing + rewrite manifest
```

Credentials come from `DO_SPACES_KEY` / `DO_SPACES_SECRET` (env, or
`~/.config/do-spaces/sorter-v2-parts.env`). In CI they are repo secrets; the
regen workflow (`.github/workflows/regen-parts.yml`) runs the same script
right after slicing, then verifies every URL the generated data references
actually resolves (`scripts/check_bucket_urls.py`).

Uploads are idempotent — the key IS the content hash, and the script
head-checks before writing, so re-runs upload nothing and identical bytes
are never stored twice.

### Someone sent you a product image. What to do with it

Upload it, get a URL back, put the URL in `slicer/parts.json`:

```bash
python scripts/sync_bucket.py --upload ~/Downloads/new-board.png
```

That prints the line to paste:

```
"image_url": "https://sorter-v2-parts.nyc3.cdn.digitaloceanspaces.com/img/<hash>.png"
```

Set it on the part (or family) in `slicer/parts.json`. That is the whole
workflow. The file stays wherever it was — **never copy it into the repo.**

Images are not committed, in any form. There is no repo-file path any more:
`filament.py` hard-fails on an `image:` key and tells you to use `image_url`,
and `slicer/images/` is gitignored so the old habit can't come back.

Why it's this strict: images used to be LFS-tracked, a CI job checked out
without `lfs: true`, and the 130-byte pointer stubs got hashed into the URLs
and uploaded as the images. Every URL returned 200 with
`Content-Type: image/png` and rendered broken on production.

Because the bucket is content-addressed, **a wrong image URL is never a 404** —
it's a 200 serving the wrong bytes, which no build or type check can see.
`scripts/check_bucket_urls.py` fetches each URL and checks the bytes (magic
numbers for images; reachable, non-stub content for STLs/plates/the zip). It
runs in `regen-parts.yml` before the commit-back, and takes a file argument so
you can check an image edit without invoking the slicer:

```bash
python scripts/check_bucket_urls.py slicer/parts.json
```

### The caching invariant — do not break this

Objects are served `public, max-age=31536000, immutable`. That is safe
**only** because the URL contains the content hash: the bytes at a given URL
can never change, so a cached copy can never go stale. Two rules preserve it:

1. **Never serve a stable-name URL with long-lived cache headers.** A URL
   like `/stl/chute-core.stl`, whose content changes across part revisions,
   must not be cached aggressively. Every public artifact URL is
   hash-addressed. If a friendly-name alias is ever added, it gets a short
   TTL.
2. **Never use presigned URLs for public artifacts** — they expire. These
   are public-read objects at permanent keys.

Origin and CDN hostnames both serve the objects permanently, so switching
between them is not a breaking change. Full rationale:
`notes/UNIFIED-PARTS-SYSTEM.md` §7.

Because hashes are permanent addresses, every historical revision stays
downloadable forever with no archive to maintain — this is what lets a part
revision pin an `stl_hash` and stay retrievable indefinitely.

## Storage layout

The only binaries in git are the AUTHORED sources: `slicer/parts/**` (STL
masters, ~49 MB) and `slicer/plates/*.3mf`, plus the small generated PNGs the
site wants at build time (`static/renders/`, `static/plate-thumbs/`).

Everything served for download comes from the bucket, content-addressed:

- each part's `stl` URL and the `all_parts_zip` bundle URL in
  `parts.generated.json` (the zip is staged under gitignored
  `slicer/build/bundle/` and uploaded by `sync_bucket.py`);
- each plate's `download` URL in `plates.generated.json`;
- every product image (`image_url`, pinned in `parts.json`).

**Historical part-version geometry is pinned, not reconstructed.** Each
superseded version in `parts.json` carries `stl_hash` — the sha256 of its
final bytes, written by `stamp_versions.py` at supersession time — and
`archive_versions()` in `slicer/filament.py` fetches those bytes from the
bucket. Git history is never consulted for geometry, which is what made the
2026-08 history rewrite (dropping the old `static/stl` serving copies and 30+
committed revisions of `all-parts.zip`) safe. The pre-rewrite history is
preserved read-only at `basicallysource/parts-calculator-archive`.

## Known stale docs

`README.md`'s three known errors were fixed when CI slicing landed: the
bogus "STLs go to Git LFS automatically" line, the reference to
`slicer/PARTS_CONTEXT.md` (terminology lives in `notes/TERMINOLOGY.md`),
and the 4-item section list (there are 9 sections in `slicer/parts.json`).
