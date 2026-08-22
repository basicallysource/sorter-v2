# CLAUDE.md

Working rules for this directory. **This was its own repository until
2026-08-20; it is now `parts-calculator/` inside `basicallysource/sorter-v2`,
with its full history.** The old `basicallysource/parts-calculator` is archived
and read-only, and pre-rewrite history is at `parts-calculator-archive`. Paths
below are relative to this directory unless they start with `.github/`, which is
the sorter-v2 repository root.

The docs site is the other half of the same catalog now: `docs/` imports
`src/lib/data/catalog.generated.json` directly, so a part edited here changes both
sites. `docs/_data/parts.yml` is deleted and is not where parts live any more.

Read `notes/UNIFIED-PARTS-SYSTEM.md` before
making structural changes to the parts data model — it is the design spec
for where this is heading (unified registry across this repo, the docs, and
the BOM spreadsheet).

## What this is

A SvelteKit static site that tells you what to print/buy for a Sorter V2
build. Two halves:

- **`catalog/`** — Python + a slicer. Slices every part, reads the
  slicer's real `used_g`, renders thumbnails, writes the site's data.
  **Never runs in the site build, and never runs in CI.** Whoever edits the
  slicer inputs runs `catalog/generate.py` and commits source and outputs
  together, in the same change. The script picks its slicing backend itself:
  a local OrcaSlicer when one is installed, otherwise the asset service
  (`ASSET_SERVICE_TOKEN` set) — an uploaded STL gets its slice reports and a
  render as derived forms, made by the service's worker on the same pinned
  profile. So no machine needs OrcaSlicer to change parts data, and a branch
  preview is correct from the first push, because the data rode in with it.
  `.github/workflows/check-parts.yml` guards every PR and push: the generated
  data must agree with the source pins (`check_generated_pins.py`) and every
  URL the site ships must serve real bytes (`check_bucket_urls.py`). Pure
  checks, about a minute; nothing commits onto your branch.
- **`src/`** — the app. Reads generated JSON, does all math in the browser.
  Fully static.

## Deploying

**Pushing/merging to `main` auto-deploys.** Cloudflare Pages project
`parts-calculator` builds from sorter-v2 with this directory as its root and
`parts-calculator/*` as its watch paths, so a commit that lands on `main` is
live at parts-calculator.basically.website. There is no separate deploy step;
treat every push to `main` as a production release. The Vercel project is
deleted — nothing here builds on Vercel any more.

## PR previews

Every branch gets a Pages preview, commented on the PR, and it is correct as
soon as it builds: the generated data is committed in the same change as the
source that produced it, so the app never waits on anything. Nothing commits
onto your branch after you push. If `check-parts` is red, the change itself is
inconsistent — regenerate and push again.

## Hard rules

**Never hand-edit generated files.** `src/lib/data/catalog.generated.json` is
an output. The authored source of truth is `catalog/parts.json`. Edit that and
re-run the generator.

**Filament weights are measured, never estimated.** Grams come from
OrcaSlicer's own output. Do not compute weight from volume/density.

**Python is invoked by full path** (no venvs):
```
/opt/homebrew/opt/python@3.11/libexec/bin/python catalog/generate.py
```

## Artifacts and the bucket

Large binaries (STLs, 3MFs) sync to a DigitalOcean Space, every filename
carrying the content hash so it is immutable by construction:

```
stl/<part>-<uid>-<hash8>.stl        render/<part>-<hash8>.png
img/<name>-<hash8>.<ext>            plate/<name>-<hash8>.3mf
```

Public URLs are served through the asset worker at
`https://img.basically.website/parts` (`PUBLIC_BASE` in `sync_bucket.py`); the
bucket's own CDN endpoint still serves the same objects, so URLs in old commits
never break. Pins are hashes, not URLs.

The `uid` in an STL's name is the part version's id from `catalog/parts.json`,
minted by `catalog/mint_uid.py` before the STL exists — every part has one,
screws included. The uid names the design revision and the hash names the
bytes: a new version is a new uid, a re-export of the same design is a new
hash under the same uid.

```
python scripts/sync_bucket.py --dry-run   # report only
python scripts/sync_bucket.py             # upload missing
```

Credentials come from `DO_SPACES_KEY` / `DO_SPACES_SECRET` (env, or
`~/.config/do-spaces/sorter-v2-parts.env`). `check-parts.yml` verifies every
URL the generated data references actually resolves
(`scripts/check_bucket_urls.py`) on each PR and push to main.

Uploads are idempotent — the key IS the content hash, and the script
head-checks before writing, so re-runs upload nothing and identical bytes
are never stored twice.

### Someone sent you a product image. What to do with it

Upload it, get a URL back, put the URL in `catalog/parts.json`:

```bash
python scripts/sync_bucket.py --upload ~/Downloads/new-board.png
```

That prints the line to paste:

```
"image_url": "https://sorter-v2-parts.nyc3.cdn.digitaloceanspaces.com/img/<hash>.png"
```

Set it on the part (or family) in `catalog/parts.json`. That is the whole
workflow. The file stays wherever it was — **never copy it into the repo.**

Images are not committed, in any form. There is no repo-file path any more:
`generate.py` hard-fails on an `image:` key and tells you to use `image_url`,
and `catalog/images/` is gitignored so the old habit can't come back.

Why it's this strict: images used to be LFS-tracked, a CI job checked out
without `lfs: true`, and the 130-byte pointer stubs got hashed into the URLs
and uploaded as the images. Every URL returned 200 with
`Content-Type: image/png` and rendered broken on production.

Because the bucket is content-addressed, **a wrong image URL is never a 404** —
it's a 200 serving the wrong bytes, which no build or type check can see.
`scripts/check_bucket_urls.py` fetches each URL and checks the bytes (magic
numbers for images; reachable, non-stub content for STLs/plates/the zip). It
runs in `check-parts.yml` on every PR, and takes a file argument so you can
check an image edit without invoking the slicer:

```bash
python scripts/check_bucket_urls.py catalog/parts.json
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

**NOTHING BINARY IS IN GIT. Not one file, authored or generated.** No STL, no
3MF, no PNG, no zip, no render. `catalog/parts/`, `catalog/plates/`,
`static/renders/` and `static/plate-thumbs/` do not exist — the history was
rewritten on 2026-08-20 to remove them, taking the repo from 376 MB to under a
megabyte packed. Do not recreate any of them, and do not "temporarily" commit a
binary to get a build working.

What git holds is JSON, code, site chrome (favicon, logo) and the DXF/SVG cut
sources under `static/dxf*`. Everything else lives on the bucket and is pinned
by hash from committed JSON:

- each part's `stl` URL and the `all_parts_zip` bundle URL in
  `catalog.generated.json` (the zip is staged under gitignored
  `catalog/build/bundle/` and uploaded by `sync_bucket.py`);
- each plate's `download` URL in the same file;
- every product image (`image_url`, pinned in `parts.json`).

**Historical part-version geometry is pinned, not reconstructed.** Each
superseded version in `parts.json` carries its `uid` and `stl_hash` — the
sha256 of its final bytes, both written by `stamp_versions.py` at supersession
time — and
`archive_versions()` in `catalog/generate.py` fetches those bytes from the
bucket. Git history is never consulted for geometry, which is what made the
2026-08 history rewrite (dropping the old `static/stl` serving copies and 30+
committed revisions of `all-parts.zip`) safe. The pre-rewrite history is
preserved read-only at `basicallysource/parts-calculator-archive`.

**Candidates are pinned the same way.** A part's `candidates` are design
revisions under test for its slot — own uid, own `stl_hash`, sliced and
rendered, no version number until adopted. They are never deleted, only
marked `superseded_by` / `rejected_at`, because a uid on a test print has to
keep resolving; `check_generated_pins.py` fails any change that drops a uid
from `parts.json`.

**Assemblies carry `uid` / `version` / `versions` / `candidates` too.** An
assembly version is an authored structural change; its superseded entries
snapshot the lines with each member's uid of the day (`stamp_versions.py`),
and a candidate is an alternative bill of materials under test. Same minting,
same retention rule.
