# The wire harness

WireViz sources for the Sorter V2 harness, and the pipeline that turns them
into everything the docs and a cable vendor need.

## The one idea

**Sources are in git. Renders never are. URLs are.**

`power.yml`, `steppers.yml`, `leds.yml` and `rfq.txt` are the source of truth:
small, diffable text. Reviewing a harness change means reviewing them.
Everything derived (PNG, SVG, PDF, HTML, per-cable BOM, the supplier RFQ zip)
is a build artifact, and build artifacts live in the `basically-docs` assets
bucket under a name carrying a hash of their own bytes:

    https://img.basically.website/harness/power.2c0ebc6cd1.png

**Nothing in the bucket is ever overwritten**, and nothing about these URLs is
derived at docs-build time. They are literal strings in
`docs/src/liquid/_data/harness.yml`, pasted from the render that produced them
— the same contract `docs/scripts/upload_image.py` has always had for photos,
where the tool prints a URL and you paste it into the page. Change a drawing
and its URL changes in the same commit, right next to the change, visible in
the diff. A PR preview shows the PR's drawings because the PR's data file names
them, not because anything resolved a branch.

### Why, at length, because this cost a day

The scheme this replaced wrote every render to `harness/<branch>/power.png`,
overwriting in place, and had the docs build the URL from the branch name plus
`?v=<the docs build's commit sha>`. Three things were wrong with it, and they
compounded:

1. The sha in the URL was the *docs build's*, not the drawing's. So a
   docs-only push reissued all five drawings' URLs (2.3 MB refetched for
   nothing), and a changed drawing got a new URL for an unrelated reason.
2. The object behind a URL was mutable, but the worker served it
   `cache-control: public, max-age=31536000, immutable`. That header was a
   lie.
3. The harness render and the docs build start on the *same push*. The docs
   build can win. In that window the page names `power.png?v=<newsha>` while
   the bucket still holds the previous render at that path — or a
   half-uploaded one. Whoever loads the page then pins wrong bytes for a year,
   in their own browser and in the edge cache, with no recovery but a hard
   reload they have no reason to attempt.

That is not hypothetical: it is what put a broken drawing on the live WireViz
page on 2026-08-09, visible in an already-warmed browser and fine in
incognito. A
content-addressed name fixes all three at once, because the object now exists
before any commit can name it.

`img.basically.website` is a Cloudflare Worker (`docs/scripts/img-worker/`) in
front of the bucket. Every response carries `x-img-cache: hit|miss`, which is
the evidence when somebody says a drawing looks wrong:

    curl -sI "https://img.basically.website/harness/power.<hash>.png" | grep -i x-img-cache

The origin is public and never cached, so it is the tiebreaker if the two ever
disagree:

    https://basically-docs.nyc3.digitaloceanspaces.com/harness/power.<hash>.png

Caching is no longer load-bearing for correctness here, and that is the point
of content-addressed names: a URL's bytes cannot change, so a stale cache
entry and a fresh one are the same bytes. Two caching bugs got fixed on the way
to that and are worth not reintroducing. The worker used to fetch
`ORIGIN + url.pathname`, dropping the query string before its subrequest, so
every `?v=` we appended hit one cached object which a 24h `cacheTtlByStatus`
pinned in place — a fresh render in the bucket, a day-old render on the page,
and the YAML link disagreeing with the picture above it. Zone purge could not
clear it either: the key was a `digitaloceanspaces.com` URL, not one in the
`basically.website` zone, so `purge_cache` returned success and did nothing.
The worker now caches under its own hostname with the full URL in the key
(#284, 2026-08-09). Keep both properties if you touch that file.

**If a drawing ever looks wrong again, the first question is which URL the page
is serving**, and the answer is in the page source and in
`docs/src/liquid/_data/harness.yml` — no derivation, no build sha, no branch
resolution. If the URL is the one you expect and the bytes are wrong, that is a
real cache bug worth chasing. If the URL is not the one you expect, somebody
skipped the paste.

Permanent, content-addressed copies are a release-time concern (the lockfile
mechanism in the unified parts plan), not a live-docs one. The bucket is
disposable by design: every object in it can be regenerated from git plus the
pinned toolchain.

## Changing a harness

Edit the YAML. Push. CI renders and uploads, then fails the
**Check the docs point at this render** step with the exact block of URLs to
paste into `docs/src/liquid/_data/harness.yml`. Paste it, commit, push again.
Two rounds, and the second one is copy-paste out of the job log.

That failing step is the point, not an annoyance: it is what makes it
impossible to change a drawing and leave the page serving the old one. The
upload is safe to run on every push precisely because names are content
addressed — it can only ever add objects, never replace one somebody is
already serving, and a re-render of an unchanged drawing uploads nothing.

You do not need WireViz, graphviz, or any credentials to contribute. Fork PRs
render without publishing (GitHub withholds secrets from forks), which still
proves the YAML builds; a maintainer's push publishes and produces the URLs.

To render locally (optional, for a fast inner loop):

    ./electronics/wire_harness/build-harness.sh      # renders into out/ (gitignored)
    ./electronics/wire_harness/upload-harness.py --dry-run   # names + paste block, uploads nothing

**Do not paste URLs from a local render.** graphviz's version is part of the
rendered pixels, so a local render on a different graphviz hashes differently
than CI's pinned 2.42.2 and the URLs will be for bytes CI would never produce.
Local renders are for looking at a change. CI is the only renderer whose
output gets pasted.

Credentials are the `SPACES_KEY` / `SPACES_SECRET` environment variables; CI
uses repo secrets holding a key scoped to this one bucket. Note CI is the
canonical
renderer: it pins WireViz 0.4.1 and graphviz 2.42.2, the graphviz version is
part of the rendered pixels, and a local render on a different graphviz gets
quietly normalized by the next CI run for that ref.

Disaster recovery, if the bucket is ever lost or defaced: rotate the key, run
the workflow on main (`workflow_dispatch`), done. Photos elsewhere in the
bucket are restored from an offline mirror held outside this repo.

## Linking someone to a preview

**The docs are on Cloudflare Pages.** Take the preview URL from the
`cloudflare-workers-and-pages[bot]` comment on the PR, never by deriving one:
Pages names a deployment by a hash you cannot predict, and the check's own
`details_url` is the dashboard rather than the site. The comment carries no URL
at all while the build is running, so re-read it rather than concluding there
is no preview. The wireviz page on that preview is
`/hardware/electronics/wireviz/`.

A dead `Vercel - sorter-v2-docs` check still goes green on these PRs and is not
the docs site any more. Ignore it.

## Adding a drawing

1. New `<name>.yml` source here.
2. Add `<name>` to the `drawings` list in `build-harness.sh` (the supplier
   zip's member list).
3. Add an entry (name, title, caption) to `docs/src/liquid/_data/harness.yml`.
4. Push; paste the URL block CI prints into that same entry. The check fails
   until every drawing listed there carries the six URLs
   (`png`, `svg`, `pdf`, `html`, `bom_tsv`, `yml`) from the current render,
   and fails too if you rendered a drawing you never listed.

**Overview drawings and sub-harnesses.** A drawing that is one buildable
assembly out of a bigger diagram carries `of: <parent name>` in
`harness.yml`. The WireViz page renders those one heading level down, so the
overview comes first and the assemblies a vendor actually quotes sit under
it. `power` works this way: it is the whole 24V distribution, and
`psu-pigtail` and `board-power` are the two cables it is made of. Keep a
sub-harness next to its parent in the list, the page follows list order.

They deliberately restate values that also appear on the parent. If you
change a length, gauge or connector, change it in both.

## Keep notes narrow

**Every `notes:` and `description:` is a quoted string with explicit `\n`
line breaks, wrapped at about 46 characters.** WireViz does not wrap: one long
note becomes one very wide table cell and the whole sheet stretches to fit it.
Wrapping `leds` took it from 6031px wide to 3588, and `steppers` from 2727 to
1753.

So write:

    notes: "Omron V-155-1C25, quick-connect (#187) tabs.\nThese push on, no soldering."

not a `>` folded block, which YAML joins back into one line before WireViz ever
sees it.

**Quote anything containing `#`.** An unquoted `type: Quick-connect receptacle,
#187 (4.75 x 0.5 mm tab)` silently becomes `Quick-connect receptacle,` because
` #` opens a YAML comment. It renders as a truncated string with a trailing
comma and nothing errors.

## The BOM tables on the WireViz page

Each drawing's `.bom.tsv` is rendered as a table under its image. **It is
fetched in the browser, not baked in at build time**, by the `$effect` in
`docs/src/routes/[...path]/+page.svelte` that picks up
`<div class="bom" data-bom="...">` placeholders.

Build-time was rejected because the docs build and the harness render used to
start on the same push, so a docs build that won the race would bake in a
missing or stale table and keep serving it. Content-addressed URLs removed that
race — the TSV is uploaded before any commit names it — so baking in at build
time would now be safe. It is still fetched at read time because there is no
reason to change it and the `BOM (TSV)` download link above each table is the
fallback when the fetch does not run.

The bucket sends `access-control-allow-origin: *`, so the cross-origin fetch is
fine, and the name contains the hash, so it is served immutable and honestly.

## Where this shows up in the docs

Four pages under `docs/src/content/hardware/electronics/`:

| Page | What it is |
|---|---|
| `index.md` → `/hardware/electronics/` | Wire harness: PSU spec, interconnect diagram, wire schedule, parts, open items |
| `steppers.md` → `/hardware/electronics/steppers/` | Board stepper pinout, board-to-motor mapping, the 4-to-6 position crossover |
| `order.md` → `/hardware/electronics/order/` | Order-ready cable build list for a harness vendor, every guess marked |
| `wireviz.md` → `/hardware/electronics/wireviz/` | The rendered drawings and the supplier zip. **The page that consumes the bucket.** |

The wire IDs (`W1`, `L3p`, `S1-S4`, `CH`, `RIB`) are the join key across the
schedule, the order spec, and the drawings. Renaming one means renaming it
everywhere.

## Legacy files

`10_pin.yaml` / `10pin.png` and `4_pin.yaml` / `4pin.png` are standalone
connector definitions from before this pipeline, kept deliberately (Spencer,
2026-08-08). They are not part of the rendered set: the build only picks up
`*.yml`, and their PNGs are grandfathered committed renders. Do not delete
them as cleanup, and do not take them as precedent for committing new renders.

## Status

Nothing here has been validated against the physical machine. Guessed values
are marked `GUESS` in the drawings, the order spec lists what to verify before
sending, and the harness page carries the open items. Treat it as Spencer's
July 12th 2026 notes plus engineering guesses, not measured truth.
