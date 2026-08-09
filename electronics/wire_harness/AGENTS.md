# The wire harness

WireViz sources for the Sorter V2 harness, and the pipeline that turns them
into everything the docs and a cable vendor need.

## The one idea

**Sources are in git. Renders never are.**

`power.yml`, `steppers.yml`, `leds.yml` and `rfq.txt` are the source of truth:
small, diffable text. Reviewing a harness change means reviewing them.
Everything derived (PNG, SVG, PDF, HTML, per-cable BOM, the supplier RFQ zip)
is a build artifact, and build artifacts live in the `basically-docs` assets
bucket, addressed by git ref:

    https://img.basically.website/harness/<branch>/power.png

Refs are mutable, exactly like git branches: pushing to a branch overwrites
that branch's prefix. The docs derive the prefix for whatever ref they're
building (`resolveHarness()` in `docs/src/lib/server/content.ts`), so a PR preview shows the PR's
drawings and production shows main's. Objects carry a short cache TTL and the
docs append a per-deploy `?v=` buster, so nobody ever sees a stale drawing for
more than about a minute.

That last sentence was false from the day it was written until 2026-08-09, and
it is worth knowing why, because the failure was silent and cost a day of
looking at the wrong drawing. `img.basically.website` is a Cloudflare Worker
(`docs/scripts/img-worker/`), and it used to fetch `ORIGIN + url.pathname`,
dropping the query string before the subrequest. So the cache key never
contained the buster and every `?v=` we appended hit the same cached object,
which a 24h `cacheTtlByStatus` then pinned in place — a fresh render in the
bucket, a day-old render on the page, and the YAML link on the same page
disagreeing with the picture above it. Zone purge could not clear it either:
the key was a `digitaloceanspaces.com` URL, not one in the `basically.website`
zone, so `purge_cache` returned success and did nothing. The worker now caches
under its own hostname with the query in the key. If you change that file,
keep both properties.

Permanent, content-addressed copies are a release-time concern (the lockfile
mechanism in the unified parts plan), not a live-docs one. The bucket is
disposable by design: every object in it can be regenerated from git plus the
pinned toolchain.

## Changing a harness

Edit the YAML. Push. That's all.

`.github/workflows/harness.yml` renders on any PR or main push touching this
directory and publishes to the branch's prefix, typically within ~90 seconds.
You do not need WireViz, graphviz, or any credentials to contribute, and there
is no step to remember: the preview self-corrects when the render lands. Fork
PRs render without publishing (GitHub withholds secrets from forks), which
still proves the YAML builds.

To render locally (optional, for a fast inner loop):

    ./electronics/wire_harness/build-harness.sh      # renders into out/ (gitignored)

and to publish by hand (rarely needed; CI does this):

    ./electronics/wire_harness/upload-harness.py --ref <branch>

Local creds come from `~/.config/basically/do-spaces.env`; CI uses repo
secrets holding a key scoped to this one bucket. Note CI is the canonical
renderer: it pins WireViz 0.4.1 and graphviz 2.42.2, the graphviz version is
part of the rendered pixels, and a local render on a different graphviz gets
quietly normalized by the next CI run for that ref.

Disaster recovery, if the bucket is ever lost or defaced: rotate the key, run
the workflow on main (`workflow_dispatch`), done. Photos elsewhere in the
bucket come back from the gravity mirror.

## Linking someone to a preview

Take the preview URL from Vercel's own PR comment or check, never by deriving
it from the branch name: Vercel truncates long branch names to fit DNS's
63-character label limit, so a derived
`sorter-v2-docs-git-<branch>-...vercel.app` hostname can simply not resolve.
The wireviz page on that preview is `/hardware/electronics/wireviz/`.

## Adding a drawing

1. New `<name>.yml` source here.
2. Add `<name>` to the `drawings` list in `build-harness.sh` (the supplier
   zip's member list).
3. Add an entry (name, title, caption) to `docs/src/liquid/_data/harness.yml`.

**Overview drawings and sub-harnesses.** A drawing that is one buildable
assembly out of a bigger diagram carries `of: <parent name>` in
`harness.yml`. The WireViz page renders those one heading level down, so the
overview comes first and the assemblies a vendor actually quotes sit under
it. `power` works this way: it is the whole 24V distribution, and
`psu-pigtail` and `board-power` are the two cables it is made of. Keep a
sub-harness next to its parent in the list, the page follows list order.

They deliberately restate values that also appear on the parent. If you
change a length, gauge or connector, change it in both.

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
