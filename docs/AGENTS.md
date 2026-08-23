# Working on the docs site

This is the documentation site (`docs/`): SvelteKit + Tailwind v4,
prerendered to static HTML at build time. This file is the playbook for
adding and editing articles. Read it before touching anything here.
`README.md` covers how the engine works; this covers authoring.

## Preview

`npm run dev` (from `docs/`) runs the dev server with hot reload. Markdown,
data files, and includes all hot-reload; restart after changing
`src/lib/server/content.ts`.

## Favicon — the docs site color is yellow

Every web UI in the ecosystem shows the same basically brick on a full-bleed
colored square, and the color says which site you are looking at: Hive is red, a
machine is blue, the docs site is **yellow** (`#FFD500`). The convention, the
asset spec, and the rules for adding a site live in
`software/hive/frontend/CLAUDE.md` § Favicons. Assets are
`static/assets/favicon.ico`, `favicon-96.png`, `favicon-192.png`,
`apple-touch-icon.png`.

## Writing conventions

- **Concise. Straight content. No preamble.** State the thing and move on.
  Assembly pages read like LEGO instructions: show the target, then the steps.
- **No em dashes (`—`) in copy.** Use commas, periods, or parentheses. (The
  kicker breadcrumb is the one place they still appear, site-wide.)
- Titles are sentence case. Alt text on every image.

## Add a new article

1. Create `src/content/hardware/<section>/.../page.md` (or `index.md` for a
   landing page). The URL is the file path with a trailing slash
   (`permalink:` in frontmatter overrides).
2. Front matter:
   ```yaml
   ---
   title: Bottom interface          # sentence case
   type: how-to                     # tutorial|how-to|reference|explanation|
                                    # installation|troubleshooting|architecture|landing
   section: hardware                # drives which sidebar shows
   slug: assembly-bottom-interface  # unique
   kicker: Bin frame — Bottom interface
   lede: The base the bin frame builds up from.
   author: spencer                  # optional; see Authors
   parts_needed:                    # optional; see Parts
     - part: lazy-susan
     - part: m4-12mm-countersunk
       qty: 8
   tools_needed: [Screwdriver]      # optional, plain strings
   og_image: <full image URL>       # optional; see Link previews
   ---
   ```
   `audience`, `applies_to`, `owner`, `last_verified` come from per-section
   defaults in `src/lib/server/content.ts` — only set them to override.
3. Add it to the sidebar in `src/liquid/_data/nav.yml` under the right
   section's `pages:` (nest with `children:` — the sidebar renders
   arbitrarily deep).
4. `python3 scripts/validate_frontmatter.py` must pass.

## Link previews (`og:image`)

The `og:image` a page unfurls with is **its first `<img>`**, picked up
automatically, so most pages need nothing. Assembly pages are the exception:
they open with the parts laid out on a bench, which is a poor thumbnail for
the finished thing. Set `og_image:` in front matter to a full
`https://img.basically.website/...` URL to override it (relative paths are
resolved against the site URL). The image stays wherever it already is in the
body; this only changes what the embed shows.

## Engineering notes (`/n/<id>/`)

A note is a permanent page about something that happened, written when a part
or a decision needs a record that a changelog line cannot carry: why an export
was replaced, what was measured, what was ruled out. They are deliberately
unlike the rest of this site.

- **Minted id, no slug.** `docs/src/content/notes/<id>.md` with
  `permalink: /n/<id>/`. Get the id from
  `parts-calculator/catalog/mint_uid.py`, which draws from the same pool as
  part uids and skips ids already naming a note, so an id means one thing
  wherever you type it. A slug would be a claim that goes stale; the words
  live in the title, where being wrong later costs nothing.
- **Not in `nav.yml`, ever.** That keeps it out of the sidebar and out of
  search (both are built from the nav), so it is reachable only from whatever
  links it. Leave `section:` unset and the page renders full width with no
  sidebar.
- **Not edited after the fact.** Say so at the foot of the page. If the
  situation changes, mint a new note that supersedes it and leave the old one
  exactly where it is.
- **Link it from the thing it is about.** A part, version or candidate in
  `parts-calculator/catalog/parts.json` takes `"note": "<id>"`, and the part
  page renders "Engineering note <id>" pointing back here.

Images follow the ordinary rules below (upload, content-addressed URL, never
in git), under `notes/<id>/`. A detail image wants the full column: put a
single `<figure>` inside an `img-row` rather than using `doc-figure`, which
caps at 440px for assembly photos.

## Components (write these as raw HTML in the markdown)

Liquid includes and `site.data` still work exactly as they did under Jekyll —
pages are rendered through liquidjs at build time. Includes live in
`src/liquid/_includes/`.

- **Step heading:** `{% include step.html n="1" title="Mount the thing" %}`
  → a small "Step 1" tag over the title.
- **Figure:** `<img class="doc-figure" src="https://img.basically.website/web/…" alt="…">`
- **Side-by-side images** (share one full-width row, wrap on mobile):
  ```html
  <div class="img-row">
    <figure><img src="…" alt="…"><figcaption>optional caption</figcaption></figure>
    <figure><img src="…" alt="…"></figure>
  </div>
  ```
- **Placeholder** for a not-yet-supplied image: `<div class="img-placeholder">Image coming</div>`
  (standalone, or inside an `img-row` `<figure>`).
- **Callout:** neutral, or `callout-warning` (amber). Use for warnings/notes
  that belong in the flow of a step, NOT in the parts catalog.
  ```html
  <div class="callout callout-warning">
    <span class="callout-icon" aria-hidden="true">⚠</span>
    <p>Warning text.</p>
  </div>
  ```
- **Video (YouTube):** plain embed, 16:9 full width. No autoplay (just the normal player).
  ```html
  <div class="video-embed video-embed-wide">
    <iframe src="https://www.youtube.com/embed/VIDEO_ID" title="…"
      allow="encrypted-media; picture-in-picture; web-share" allowfullscreen loading="lazy"></iframe>
  </div>
  ```
  `video-embed-portrait` exists for true 9:16 shorts, but most videos are wide.
- **Video (a clip of your own):** `video-embed-self`, holding a real `<video>`
  whose sources come from the asset service. See **Video** below for how it
  gets there; never hand-write one of these URLs.

One Liquid caveat that did not exist under Jekyll: a loop that emits rows
inside a raw HTML `<table>` must not leave blank lines between rows (the
markdown parser would close the HTML block). The renderer trims tag-only
lines, so normal `{% for %}` loops are fine as-is.

## Images — the workflow

**Images are not in git.** Originals and web versions live in the
`basically-docs` DO Spaces bucket, served at `https://img.basically.website`
(Cloudflare Worker in `scripts/img-worker/`). Ask the user **which folder the
pics are in** (Downloads, Desktop, VLC Snapshots, etc.). Then do all of this
yourself:

> The worker is not deployed by CI. It ships by hand, from this directory:
> `CLOUDFLARE_API_TOKEN=… npx wrangler deploy` in `docs/scripts/img-worker/`.
> Merging a change to `worker.js` therefore changes nothing on its own —
> deploy it, then check a real URL. Cloudflare keeps prior versions, so the
> rollback is a redeploy of the previous one.
>
> Two things to expect. `wrangler` exits non-zero on
> `/zones/<id>/workers/routes` unless the token also carries Workers Routes
> edit; the upload has already happened by then and the custom domain is
> already attached, so it is noise. And every response carries
> `x-img-cache: hit|miss` — check it before believing anything about
> freshness, since a stale object and a fresh one look identical otherwise.

1. **Look at each image** (Read tool) to understand what it shows before naming.
2. **Upload it:**
   ```bash
   python3 docs/scripts/upload_image.py <original-file> assembly/<page>/<name>
   ```
   The script generates the web version (long side ≤ 1600px, **opaque →
   `.jpg`**, **transparent → `.png`**), uploads the full-res original to
   `originals/<path>` and the web version to `web/<path>`, and prints both URLs.
   Needs Pillow and boto3.

   **Credentials** are the `SPACES_KEY` / `SPACES_SECRET` environment
   variables, holding a key scoped to the `basically-docs` bucket. **Check for
   them rather than assuming** — `echo $SPACES_KEY` — and do not conclude from
   a past note, this file included, that you don't have them. Never commit
   them. Only if they are genuinely absent, say so and use `img-placeholder`
   divs (above) instead of guessing or embedding the image data directly in
   the page.
3. **Reference the printed web URL** in the page:
   `https://img.basically.website/web/<path>.<hash>.<jpg|png>`. Plain URL, no Liquid.
4. Commit the URL, never the image bytes. The URL works identically on PR
   previews and production, since the bucket is branch-independent.

## Video — the workflow

A clip does **not** go in the images bucket. `upload_image.py` uploads exactly
what you hand it, which is right for a photo and wrong for a phone video: tens
of megabytes of HEVC at 4K, which no browser should be asked to download to
watch two seconds of something clicking.

Video goes to the **asset service** (`assets.basically.website`, public repo
`basicallysource/asset-service`), the same one the parts calculator slices STLs
through. It keeps the original and holds derived forms beside it: an **MP4
ladder** (960 and 1920 wide, never upscaled) and a **poster** still. A page
shows the poster and downloads nothing until someone presses play.

Upload with that repo's own CLI, not with a script in here. The encoding rules
live in its `internal/derive`, and a second copy of them here would drift:

```bash
asset-service upload --derive --namespace sorter-docs ~/Downloads/IMG_7204.MOV
```

**`--derive` is not optional for anything big.** The service *queues*
derivation rather than doing it, and a standing worker elsewhere drains that
queue. That worker has a memory ceiling, and a 4K phone clip goes straight
through it: encoding 3840x2160 down to the 1920 rung wanted more than the
worker is allowed, so ffmpeg was OOM-killed. The worker restarts on failure,
re-claims the same job, and dies again, which blocks **everything** behind it
in the queue, including uploads that would have been fine on their own. From
the client all you see is `renditions_status: pending` forever, with no error
and nothing to poll (`/v1/health`, `/v1/namespaces` are 404), so you cannot
tell a busy queue from a jammed one.

`--derive` sidesteps all of that: it encodes on your machine, where the file
already is, and uploads the results. It finished the same clip in seconds.
(Diagnosed 2026-08-23, after a plain upload jammed the shared queue for an
hour.)

Then turn the manifest into markup:

```bash
python3 docs/scripts/video_embed.py sorter-docs/<name>-<hash>.mov
```

Paste the block it prints. Rules carry over from images unchanged: every URL
contains a hash of its bytes, so it is immutable and cacheable forever; nothing
binary is committed; a re-encode is a new URL.

Three things to know.

- **`validate_images.py` does not check these URLs.** It walks
  `img.basically.website/web/` only, and video is served from
  `assets.basically.website`. Nothing catches a typo in a pasted video URL, so
  load the page and press play before you push.
- **Size the player from the poster, not from an encode.** A phone shoots
  portrait into a landscape frame and sets a rotation flag, so the MP4 reports
  1920x1080 and plays 1080x1920 while the poster is a still with the rotation
  already applied. `video_embed.py` already does this; if you hand-write a
  block, do the same or the page reserves a landscape hole the video will not
  fill.
- **Nothing deletes.** `DELETE /v1/assets/<key>` is 405. An upload you regret
  is an object that stays, so do not use the real namespace as a scratchpad.

Credentials are `ASSET_SERVICE_URL` / `ASSET_SERVICE_TOKEN`, read from
`~/.config/asset-service/*.env` or the environment. **Check rather than
assume**, the same as with `SPACES_KEY`. If they are genuinely absent, say so
and leave the clip out rather than shipping a still and calling it a video.

**A still frame is not a substitute.** If the point of the shot is motion,
something clicking or spinning or falling through, either it goes up as a video
or it does not go on the page. Pulling a frame out with `ffmpeg` and captioning
it as though it moved is worse than omitting it.

**A contributor's file sometimes carries images embedded as base64 data URIs**
(e.g. `![alt](data:image/jpeg;base64,...)`) instead of as separate
attachments. Same workflow applies, decode first: extract each data URI to
its own file, then upload that file with `upload_image.py` like any other
original. Don't leave the base64 inline in the page, it defeats "images are
not in git" and bloats the repo.

**A printed part's catalog image (`parts.yml`'s `image:` field) can often be
pulled from `parts-calculator`'s own renders** instead of asking for a fresh
photo: that repo's `static/renders/<part-id>.png` is a real OrcaSlicer
thumbnail for every printed part in its catalog. Upload it the same way,
under `parts/<page>/<part-id>`.

**Names are content-addressed.** `upload_image.py` adds a hash of the generated
bytes to each object name, so a changed image always prints a new URL that can
be cached forever. Name the input path by what it shows (`step2-hole-red-square`),
not by source filename. Group step images under `assembly/<page>/`, part renders
under `parts/…`, tools under `tools/`.

**This is the invariant.** Every `img.basically.website/web/` URL in docs source
must contain the hash of its actual bytes. Never overwrite an object, use a
descriptive stable URL, add a query-string cache buster, or add browser retry
code. `npm run build` runs `scripts/validate_images.py`, which rejects a missing
image, a non-content-addressed URL, or bytes that do not match the URL hash.

## The WireViz harness

**Exactly the same rule as photos**, including the part that matters: the URL
is a literal string in the repo, and it changes when the image changes. The
only difference is that CI runs the upload instead of a person, because a
render is 23 files at once.

Sources live in `electronics/wire_harness/`. On any PR or main push touching
them, `.github/workflows/harness.yml` renders with a pinned toolchain, uploads
each artifact under a name containing a hash of its bytes
(`harness/power.2c0ebc6cd1.png`), and then **fails the build unless
`src/liquid/_data/harness.yml` already names exactly those URLs**, printing the
block to paste. So changing a drawing is: push, paste the URLs CI prints, push
again.

`src/liquid/_data/harness.yml` carries the display list (name, title, caption,
`of:`) *and* the six URLs per drawing (`png`, `svg`, `pdf`, `html`, `bom_tsv`,
`yml`) plus the top-level `zip:`. Nothing in `src/lib/server/content.ts`
derives harness URLs any more — `resolveHarness()`, `site.harness_base` and
`site.harness_v` are gone. Do not reintroduce a computed harness URL: the docs
build and the harness render start on the same push, so anything the docs
compute can name bytes that have not been uploaded yet, and the `immutable`
header on the images turns that into a year-long wrong picture in the reader's
cache. That is a real outage this site had on 2026-08-09, written up in
`electronics/wire_harness/AGENTS.md`.

Adding a drawing: new YAML source, an entry in the data file, an entry in the
`drawings` list inside `build-harness.sh`, then the paste. Full pipeline doc:
`electronics/wire_harness/AGENTS.md`.

## Parts

`src/liquid/_data/parts.yml` is the catalog, keyed by id. Fields: `name`,
`image`, `page` (detail page, optional), `category` (groups the "Parts
needed" block), `length_mm` (screw length or extrusion cut length, stamped on the card
image),
`notes` (short, collected into a list under the whole block),
`caption` (small text under a single card, e.g. a cut length),
`heat_inserts: [{insert, qty}]`. ids and render filenames mirror the
`sorter-v2-filament-calculator` repo so the two merge cleanly later.

- A page lists what it needs via `parts_needed` (see front matter). Cards render
  image + name, linked to the detail page when one exists, grouped by category,
  with a quantity badge and any notes.
- **Every screw and every 2020 extrusion needs `length_mm`.** One photo stands
  in for a whole family of screws (every M5 socket head cap screw shares one
  picture), so without the length stamped on the card an M5 x 12 and an M5 x 35
  are the same card. The same is true of the extrusions, which differ only in
  cut length. The parts calculator's hardware list does the same thing for the
  same reason.
- Part detail pages live under `src/content/hardware/parts/`. Only put a part
  in the nav if it has a detail page worth linking; the catalog can hold parts
  with no page.
- `heat_inserts` on a part records which inserts it takes. There is no longer a
  central Preparation page: each assembly page opens with its own numbered
  **Preparation** step listing the inserts for the parts that page uses, with a
  photo per part (see `assembly/distribution/top-interface.md` for the pattern).
- Name the specific fastener inline in a step where it is used. When a step
  uses a screw whose size/type is not known yet, mark it with
  `<span class="fastener-todo">fastener not recorded</span>` so contributors
  can find and fill the gaps (styled in `layout.css`).
- Keep procedural warnings (torque, ordering) in a **callout on the assembly
  page**, not in a part's `notes`.

## Authors

`src/liquid/_data/authors.yml` maps an id to `{name, url}`. A page sets
`author: <id>`, or `authors: [id-one, id-two]` for multiple authors. Use
`contributors: [id-one, id-two]` for people who supplied or materially
corrected page content. The credits render under the page header. Add a person
once here; every page crediting them updates automatically.

Every page under `hardware/`, including landing and placeholder pages, must set
`author` or `authors`. `scripts/validate_frontmatter.py` enforces this.

## Deploy and PR previews

**Cloudflare Pages** builds from `docs/` — project `sorter-v2-docs`, root
directory `docs`, `npm run build` → `build/`, `NODE_VERSION=22`. Push to
`main` deploys production (docs.basically.website). **Every push to any other
branch gets an automatic preview deployment** — no setup per PR. Take the
preview URL from the PR comment or check (never derive it from the branch
name; long names get truncated). Images render identically on previews and
production because they come from `img.basically.website`, not the repo.

**Build watch paths** limit which pushes build at all. They are a Pages
project setting, not a file in this repo, so they are recorded here:

    path_includes: docs/*, electronics/wire_harness/*

A `*` matches across `/`, so `docs/*` covers `docs/src/content/x.md`. Pushes
that touch only firmware, `software/`, or hive do not build the docs.
`electronics/wire_harness/*` is in that list for historical reasons and is now
harmless either way: it was load-bearing when a harness change re-rendered into
the same bucket path and only a docs rebuild issued the `?v=<sha>` that made
browsers refetch. Harness URLs are literal strings in
`src/liquid/_data/harness.yml` now, so a drawing change always touches
`docs/*` too and would trigger a build on its own. Leaving the path in costs a
no-op build on a YAML-only push. To change the filter, edit the project's source
config (dashboard, or `PATCH /accounts/<id>/pages/projects/sorter-v2-docs`)
and update this block.

A build can always be triggered by hand, for a branch that the filter would
otherwise skip: `POST /accounts/<id>/pages/projects/sorter-v2-docs/deployments`
with `-F branch=<branch>`, or the Create deployment button on the project.

Moved off Vercel on 2026-08-09. Two reasons, in order: static asset requests
on Pages are unmetered, and the site was generating ~40k Vercel edge requests
a day against a 100-deploy-a-day Hobby account that had already rate-limited
itself out of deploying; and everything else the docs depend on
(`img.basically.website`, the DNS, the cache purge) already lives in the same
Cloudflare account. The site is `@sveltejs/adapter-static` with
`trailingSlash: 'always'` set in SvelteKit rather than in host config, so
there was nothing host-specific to port. `vercel.json` is gone.

The Pages move did break one thing silently and it is worth knowing about even
though the code is gone: `resolveHarness()` read the branch from
`VERCEL_GIT_COMMIT_REF` only, so on Pages every preview fell back to a detached
HEAD and pointed at `main`'s drawings. That whole class of bug is why harness
URLs are literal strings now and nothing about them is derived from host env
vars. If you move hosts again, no harness code needs touching.

Commit only when verified; push only when asked.
