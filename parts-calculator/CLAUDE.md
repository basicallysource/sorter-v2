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

`VERSIONING.md` is the succinct, citable statement of how parts are
identified, revised, and removed (uids, versions, candidates, retire-in-place,
the `breaking` bit, assembly version stamps). When someone asks to delete or
change a part — or revises anything — answer from, follow, and link that
page. In short: every new version entry declares `breaking: true|false`
("can an old physical instance of this node still be used in its place?"),
and a structural change to an assembly's lines must be stamped as a new
assembly version. `scripts/check_versioning.py` enforces both in CI.

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
  data must agree with the source pins (`check_generated_pins.py`), every
  URL the site ships must serve real bytes (`check_asset_urls.py`), and
  revisions must follow the versioning discipline — breaking bits declared,
  assembly line changes stamped (`check_versioning.py`, per `VERSIONING.md`).
  Pure checks, about a minute; nothing commits onto your branch.
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

## One detail view per thing

A part, a hardware item and an assembly each have exactly one detail view, and
every surface opens that same one: `PartDetail`, `HardwareDetail`,
`AssemblyDetail`, each with a thin `*DetailModal` wrapper. The parts dashboard
and the assembly tab both open the same component, so "view the PSU box" cannot
come to mean two different screens. A new place that needs to show one of these
imports the existing view; it does not write a second rendering of the same
data.

`AssemblyDetail` renders **one level**. Sub-assemblies are rows you open in
turn, and the modal keeps its own back trail — the tree page already shows the
whole thing nested, and this view exists for the opposite need: one box at a
time. Parts and hardware are handed back to the host through `onPart` /
`onHardware`, because the host already owns those modals.

**Modals stack.** Opening a part from inside an assembly puts one on top of the
other, and `Modal.svelte` keeps a module-level stack so Escape closes the front
one instead of the whole pile. Stacked modals are ordered by where they appear
in the markup, so a modal that can be opened *from* another must be rendered
before it.

## Artifacts and the asset service

Large binaries (STLs, 3MFs) live in the asset service
(`assets.basically.website`, public repo `basicallysource/asset-service`),
in the `sorter-parts` namespace. The service builds every key from the name
it is given plus a hash of the bytes, so a key is immutable by construction:

```
sorter-parts/<part>-<hash12>.stl                       master, and each
                                                       archived version of it
sorter-parts/<part>-<uid>-stamped-<face>-<hash12>.stl  the engraved downloads
sorter-parts/<name>-<hash12>.{3mf,zip,ttf}             plates, bundles, font
sorter-parts/<name>-full-<hash12>.{png,jpg}            renders and photos
```

Pins are hashes, not URLs. For anything served as uploaded — STL, 3mf, zip,
font — the URL follows from the pin, so `publish_assets.pinned_url()` can name
it without asking anyone. **Images are the exception**: the service does not
publish the file that was uploaded, it publishes a copy with the camera's
notes stripped out, so an image's URL is a fact only the service knows and it
is read off the manifest. That is why renders and product images are recorded
in the generated data and the render memo rather than derived.

The `uid` is the part version's id from `catalog/parts.json`, minted by
`catalog/mint_uid.py` before the STL exists — every part has one, screws
included. It names the design revision and it is the string recessed into the
plastic, which is why the engraved downloads carry it; the hash names the
bytes. A new version is a new uid, a re-export of the same design is a new
hash under the same uid.

```
python scripts/publish_assets.py --upload part.stl   # publish + print the pin
```

Credentials come from `ASSET_SERVICE_TOKEN` (env, or
`~/.config/asset-service/*.env`), and only publishing needs them: an asset that
is already there is looked up anonymously, so regenerating unchanged data needs
no credentials at all. `check-parts.yml` verifies every URL the generated data
references actually resolves (`scripts/check_asset_urls.py`) on each PR and
push to main.

Publishing is idempotent — the key carries the content hash, and the script
checks before writing, so re-runs send nothing and identical bytes are never
stored twice.

### Someone sent you a product image. What to do with it

Publish it, get a URL back, put the URL in `catalog/parts.json`:

```bash
python scripts/publish_assets.py --upload ~/Downloads/new-board.png
```

That prints the line to paste:

```
"image_url": "https://assets.basically.website/sorter-parts/<name>-full-<hash12>.png"
```

Set it on the part (or family) in `catalog/parts.json`. That is the whole
workflow. The file stays wherever it was — **never copy it into the repo.**
The same URL goes in an `images` list (`{url, alt, caption?}`) when it is an
extra picture rather than the product photo — an Onshape screenshot, a
section view, a photo of it built — on any part, assembly, candidate or
version. `generate.py` refuses an image without an https url and an alt.

Images are not committed, in any form. There is no repo-file path any more:
`generate.py` hard-fails on an `image:` key and tells you to use `image_url`,
and `catalog/images/` is gitignored so the old habit can't come back.

Why it's this strict: images used to be LFS-tracked, a CI job checked out
without `lfs: true`, and the 130-byte pointer stubs got hashed into the URLs
and uploaded as the images. Every URL returned 200 with
`Content-Type: image/png` and rendered broken on production.

Because assets are content-addressed, **a wrong image URL is never a 404** —
it's a 200 serving the wrong bytes, which no build or type check can see.
`scripts/check_asset_urls.py` fetches each URL and checks the bytes (magic
numbers for images; reachable, non-stub content for STLs/plates/the zip). It
runs in `check-parts.yml` on every PR, and takes a file argument so you can
check an image edit without invoking the slicer:

```bash
python scripts/check_asset_urls.py catalog/parts.json
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
sources under `static/dxf*`. Everything else lives in the asset service and is
pinned by hash from committed JSON:

- each part's `stl` URL and the `all_parts_zip` bundle URL in
  `catalog.generated.json` (the zip is staged under gitignored
  `catalog/build/bundle/` and published by `publish_assets.py`);
- each plate's `download` URL in the same file;
- every product image (`image_url`) and every extra picture
  (`images[].url`), pinned in `parts.json`.

**Historical part-version geometry is pinned, not reconstructed.** Each
superseded version in `parts.json` carries its `uid` and `stl_hash` — the
sha256 of its final bytes, both written by `stamp_versions.py` at supersession
time — and
`archive_versions()` in `catalog/generate.py` fetches those bytes by that
pin. Git history is never consulted for geometry, which is what made the
2026-08 history rewrite (dropping the old `static/stl` serving copies and 30+
committed revisions of `all-parts.zip`) safe. The pre-rewrite history is
preserved read-only at `basicallysource/parts-calculator-archive`.

**Candidates are pinned the same way.** A part's `candidates` are design
revisions under test for its slot — own uid, own `stl_hash`, sliced and
rendered, no version number until adopted. They are never deleted, only
marked `superseded_by` / `rejected_at`, because a uid on a test print has to
keep resolving; `check_generated_pins.py` fails any change that drops a uid
from `parts.json`.

**Stamped downloads are derived, never authored.** `catalog/engrave.py`
recesses the uid into a face (uppercase, 3.5 mm cap, 0.6 mm deep, Source Code
Pro Bold -- the font is a pinned published object, fetched by hash into
`build/fonts/`), and `generate.py` pre-cuts up to four face variants per
printed part and candidate into `build/stamped/`, memoized on (STL bytes, uid,
`engrave.SIGNATURE`). They ride the generated data as `stamped: [{face, stl,
normal, center}]`, best face first, empty when nothing fits; the site's part
page picks from that list; the viewer paints the pocket (found from
`center`, `normal`, `size`) in the accent colour and "show me" flies to it.
Two bundles: `all_parts_zip` ships each part's default variant,
`all_parts_plain_zip` the masters. One `IdStamp` component is the whole UI
for the concept (viewport overlay, download checkbox, dashboard checkbox). Placement is quantised and the
boolean is manifold's, so the same geometry stamps to the same bytes on any
machine -- the generator warns if a re-cut lands on a different URL than the
memo. Faces are planar facets plus cylindrical and conical walls (a smooth
walk across small dihedral angles, then a surface-of-revolution fit with
the fillets it merged with rejected as tilt outliers; unrolled exactly,
cutter bent back on; bores excluded; text turned sideways along the axis if
it would wrap past ~60°). Every spot needs 1.6 mm of wall behind a 0.6 mm
pocket, or 1.0 mm behind a 0.4 mm one (ray-cast). Per face the ladder is
3.5 mm upright, 3.5 sideways, 2.5 upright, 2.5 sideways; each variant
carries its `cap` and `depth` and a `note` when either is the fallback.
The face ranking is in `engrave.variants()` -- full-size before small
text; large flats, then walls, then small flats, inside bed / upright /
overhang classes -- and there is deliberately no per-part authoring of
where the stamp goes. The viewer's CAD mode (feature edges, grey ground)
is the default; "Shaded" is the bare surface. `/u/<uid>` is one prerendered
page per uid the catalog has ever minted.

**Assemblies carry `uid` / `version` / `versions` / `candidates` too.** An
assembly version is an authored structural change; its superseded entries
snapshot the lines with each member's uid of the day (`stamp_versions.py`),
and a candidate is an alternative bill of materials under test, optionally
carrying the `name` the slot takes if it is adopted. Same minting, same
retention rule. A structural change to an assembly's `lines` (member
removed/replaced, qty changed) MUST be stamped as a new assembly version
with its `breaking` bit — `check_versioning.py` refuses it otherwise; the
one exemption is purely additive completion of a `stub`/`partial` assembly.
See `VERSIONING.md`. A part that exists only inside a candidate assembly has
empty `quantities`: it is in no section, counts toward nothing, and is left
out of the all-parts bundle.
