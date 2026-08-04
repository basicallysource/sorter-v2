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
- **Video:** plain embed, 16:9 full width. No autoplay (just the normal player).
  ```html
  <div class="video-embed video-embed-wide">
    <iframe src="https://www.youtube.com/embed/VIDEO_ID" title="…"
      allow="encrypted-media; picture-in-picture; web-share" allowfullscreen loading="lazy"></iframe>
  </div>
  ```
  `video-embed-portrait` exists for true 9:16 shorts, but most videos are wide.

## Images — the workflow

**Images are not in git.** Originals and web versions live in the
`basically-docs` DO Spaces bucket, served at `https://img.basically.website`
(Cloudflare Worker in `scripts/img-worker/`). Ask the user **which folder the
pics are in** (Downloads, Desktop, VLC Snapshots, etc.). Then do all of this
yourself:

1. **Look at each image** (Read tool) to understand what it shows before naming.
2. **Upload it:**
   ```bash
   python3 docs/scripts/upload_image.py <original-file> assembly/<page>/<name>
   ```
   The script generates the web version (long side ≤ 1600px, **opaque →
   `.jpg`**, **transparent → `.png`**), uploads the full-res original to
   `originals/<path>` and the web version to `web/<path>`, and prints both URLs.
   Needs Pillow and boto3.

   **Credentials** come from either the `SPACES_KEY` / `SPACES_SECRET` env vars
   or `~/.config/basically/do-spaces.env` (`KEY=VALUE` lines). The env vars win.
   If you're an agent running somewhere other than Spencer's Mac, you almost
   certainly have neither — ask Spencer for a Spaces key scoped to the
   `basically-docs` bucket rather than assuming you can't add images. Never
   commit the credentials.
3. **Reference the printed web URL** in the page:
   `https://img.basically.website/web/<path>.<jpg|png>`. Plain URL, no Liquid.
4. Nothing image-related gets committed. The URL works identically on PR
   previews and production, since the bucket is branch-independent.

**Names are immutable.** The CDN caches for 30 days, so if an image's content
changes, upload under a new name and update the reference — never reuse a name
(the script refuses to overwrite unless `--force`). Name images by what they
show (`step2-hole-red-square`), not by source filename. Group step images under
`assembly/<page>/`, part renders under `parts/…`, tools under `tools/`.

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

## Deploy and PR previews

Vercel builds from `docs/`. Push to `main` deploys production. **Every push to
any other branch gets an automatic preview deployment** — no setup per PR. The
stable per-branch URL is:

    https://sorter-v2-docs-git-<branch>-spencer-huberts-projects.vercel.app

It always tracks the branch's latest push, is publicly viewable (no Vercel
login), and is the link to hand to reviewers. Each individual push also gets
its own frozen per-deployment URL (visible in the PR checks) if a reviewer
should sign off on one exact snapshot. Images render identically on previews
and production because they come from `img.basically.website`, not the repo.

Commit only when verified; push only when asked.
