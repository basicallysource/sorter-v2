# Working on the docs site

This is the Jekyll documentation site (`docs/`), deployed via **Vercel**. This
file is the playbook for adding and editing articles. Read it before touching
anything here.

## Preview

`./serve.sh start` runs Jekyll at `http://localhost:4000` (watch + livereload).
`./serve.sh {status|logs|restart|stop}`. Restart after `_config.yml` or `_data`
changes; markdown/CSS/includes hot-reload.

## Writing conventions

- **Concise. Straight content. No preamble.** State the thing and move on.
  Assembly pages read like LEGO instructions: show the target, then the steps.
- **No em dashes (`—`) in copy.** Use commas, periods, or parentheses. (The
  kicker breadcrumb is the one place they still appear, site-wide.)
- Titles are sentence case. Alt text on every image.

## Add a new article

1. Create `hardware/<section>/.../page.md` (or `index.md` for a landing page).
2. Front matter:
   ```yaml
   ---
   layout: default
   title: Bottom interface          # sentence case
   type: how-to                     # tutorial|how-to|reference|explanation|
                                    # installation|troubleshooting|architecture|landing
   section: hardware                # drives which sidebar shows
   slug: assembly-bottom-interface  # unique
   kicker: Bin frame — Bottom interface
   lede: The base the bin frame builds up from.
   permalink: /hardware/assembly/distribution/bin-frame/bottom-interface/
   author: spencer                  # optional; see Authors
   parts_needed:                    # optional; see Parts
     - part: lazy-susan
     - part: m4-12mm-countersunk
       qty: 8
   tools_needed: [Screwdriver]      # optional, plain strings
   ---
   ```
   `audience`, `applies_to`, `owner`, `last_verified` come from per-section
   defaults in `_config.yml` — only set them to override.
3. Add it to the sidebar in `_data/nav.yml` under the right section's `pages:`
   (nest with `children:` — the sidebar renders arbitrarily deep).
4. `python3 scripts/validate_frontmatter.py` must pass.

## Components (write these as raw HTML in the markdown)

- **Step heading:** `{% include step.html n="1" title="Mount the thing" %}`
  → a small "Step 1" tag over the title.
- **Figure:** `<img class="doc-figure" src="{{ '/assets/img/…' | relative_url }}" alt="…">`
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
- **Video:** plain embed, 16:9 full width. No autoplay (just the normal player).
  ```html
  <div class="video-embed video-embed-wide">
    <iframe src="https://www.youtube.com/embed/VIDEO_ID" title="…"
      allow="encrypted-media; picture-in-picture; web-share" allowfullscreen loading="lazy"></iframe>
  </div>
  ```
  `video-embed-portrait` exists for true 9:16 shorts, but most videos are wide.

## Images — the workflow

Ask the user **which folder the pics are in** (Downloads, Desktop, VLC
Snapshots, etc.). Then do all of this yourself:

1. **Look at each image** (Read tool) to understand what it shows before naming.
2. **Keep the original** in `_img-src/`, mirroring the path it'll be served at.
   Example: an image for `/assets/img/assembly/bottom-interface/step1.jpg`
   has its original at `_img-src/assembly/bottom-interface/step1.png`
   (same base name; original keeps its true extension). `_img-src/` is Git LFS
   and never deployed (Jekyll ignores underscore dirs).
3. **Generate web versions:** `python3 scripts/optimize_images.py`. It downscales
   (long side ≤ 1600px) and writes to `assets/img/…` — **opaque → `.jpg`**,
   **transparent → `.png`**. Reference the web path in the page with the
   extension the script produced (photos are `.jpg`, transparent renders `.png`).
4. Commit **both** the original and the generated web version. **Only the
   originals (`_img-src/`) are LFS.** The deployed web versions under
   `docs/assets/` are committed as **normal git blobs** — Vercel does not
   materialize LFS objects on deploy, so LFS-tracked images serve as broken
   pointer files. Keep web images small enough for plain git (that's what
   `optimize_images.py` is for).

Name images by what they show (`step2-hole-red-square.jpg`), not by source
filename. Group step images under `assets/img/assembly/<page>/`, part renders
under `assets/img/parts/…`, tools under `assets/img/tools/`.

## Parts

`_data/parts.yml` is the catalog, keyed by id. Fields: `name`, `image`,
`page` (detail page, optional), `category` (groups the "Parts needed" block),
`notes` (short, shown under the block), `heat_inserts: [{insert, qty}]`.
ids and render filenames mirror the `sorter-v2-filament-calculator` repo so the
two merge cleanly later.

- A page lists what it needs via `parts_needed` (see front matter). Cards render
  image + name, linked to the detail page when one exists, grouped by category,
  with a quantity badge and any notes.
- Part detail pages live under `hardware/parts/`. Only put a part in the nav if
  it has a detail page worth linking; the catalog can hold parts with no page.
- The **Preparation** page (`hardware/preparation/`) auto-lists every part with
  `heat_inserts` — add that field and the part appears in the checklist.
- Keep procedural warnings (torque, ordering) in a **callout on the assembly
  page**, not in a part's `notes`.

## Authors

`_data/authors.yml` maps an id to `{name, url}`. A page sets `author: <id>` and
the byline resolves in the meta footer. Add a contributor once here; every page
crediting them updates automatically.

## Deploy

Vercel builds from `docs/`. **Vercel does not resolve Git LFS**, so deployed
files must be normal git blobs (see Images). The LFS originals in `_img-src/`
are fine because they're excluded from the build. Run `optimize_images.py`
before pushing when `_img-src` changed. Commit only when verified; push only
when asked.
