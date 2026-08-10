#!/usr/bin/env bash
#
# Regenerate everything under electronics/wire_harness/out/ from the WireViz
# sources next to this script. This is the only way those files should ever be
# produced: the drawings, the BOMs, the PDFs and the supplier zip are all
# derived, and a hand-edit to any of them is silently reverted the next time
# this runs.
#
#   ./electronics/wire_harness/build-harness.sh
#
# out/ is gitignored; nothing rendered is ever committed. CI runs this on any
# harness change and publishes out/ to the assets bucket under the branch name
# (upload-harness.py --ref). See AGENTS.md next to this script.
#
# Needs `wireviz` and graphviz's `dot` on PATH. CI installs both; locally,
# `pip install wireviz==0.4.1` and `brew install graphviz`.
#
# Output is byte-for-byte reproducible, and that is now load-bearing rather
# than merely tidy: every artifact is published under a name containing a hash
# of its bytes, so anything that moves between runs mints a new URL for an
# unchanged drawing and demands a re-paste into the docs. Two sources of drift,
# both handled:
#
#   - dot's PDF writer stamps wall-clock time into a compressed object as
#     /CreationDate. SOURCE_DATE_EPOCH only pins it on a graphviz new enough to
#     honour it: 2.42.2, which is what Ubuntu 24.04 and therefore CI has,
#     ignores it, and two runs of identical sources produced PDFs differing in
#     exactly those 262 bytes. faketime below pins the clock dot sees, which
#     fixes it at the source rather than by patching the PDF afterwards.
#   - zip stores mtimes, so the archive is built by Python with a fixed
#     timestamp and a fixed member order instead of the zip(1) binary. It
#     contains the PDFs, so it was drifting for their reason too, and is stable
#     once they are.
#
# The version of graphviz IS part of the output: it shifts glyph positions,
# so a different one rewrites every PNG, SVG and HTML at once. CI pins it
# (2.42.2, Ubuntu 24.04's) and CI is the canonical renderer. Running this
# locally on a newer graphviz is fine and useful for looking at a change,
# but expect the images to come back different and expect CI to normalise
# them on the next push. Only bump the pin in the workflow deliberately;
# it lands as one rebaseline commit touching images and nothing else.

set -euo pipefail

cd "$(dirname "$0")/../.."

SRC=electronics/wire_harness
OUT=electronics/wire_harness/out

# Arbitrary fixed instant. Only its constancy matters. The two spellings are
# the same moment (2023-11-14T22:13:20Z) for two different consumers: tools
# that honour SOURCE_DATE_EPOCH, and faketime, which wants a date string.
export SOURCE_DATE_EPOCH=1700000000
SOURCE_DATE_STRING='2023-11-14 22:13:20'

command -v wireviz >/dev/null || { echo "build-harness: wireviz not on PATH" >&2; exit 1; }
command -v dot     >/dev/null || { echo "build-harness: graphviz 'dot' not on PATH" >&2; exit 1; }

mkdir -p "$OUT"

# Keep the .gv files as they stand before anything overwrites them, so the PDF
# step below can tell a real change from an identical re-render. A directory
# and cmp rather than an associative array: macOS still ships bash 3.2, which
# has no `declare -A`, and this script is meant to run on Spencer's Mac.
PREV=$(mktemp -d)
trap 'rm -rf "$PREV"' EXIT
for gv in "$OUT"/*.gv; do
  [ -e "$gv" ] || continue
  cp "$gv" "$PREV"/
done

# ghpst = .gv, .html, .png, .svg, .bom.tsv
wireviz "$SRC"/*.yml -f ghpst -o "$OUT"

# The sources ship inside the supplier package, so the copies served next to
# the drawings are the same bytes the drawings were generated from. rfq.txt is
# hand-written and lives with the sources; it is copied out for the same reason
# and because the WireViz docs page links it directly.
cp "$SRC"/*.yml "$SRC"/rfq.txt "$OUT"/

# dot stamps wall-clock time into the PDF as /CreationDate, inside a compressed
# object stream, and Ubuntu's graphviz ignores SOURCE_DATE_EPOCH. Two runs of
# identical sources therefore produced PDFs differing in exactly those 262
# bytes -- and, because the supplier zip contains them, a different zip too.
#
# That was survivable when renders overwrote a fixed bucket path. It is not now
# that a published name is a hash of the bytes: every CI run would mint five
# new PDF URLs and a new zip URL for an unchanged harness, and demand they be
# pasted back into the docs. So pin the clock dot sees. faketime is the whole
# fix; the PDFs come out byte-identical run to run, which makes the zip
# byte-identical too.
#
# Without faketime (a local Mac, usually) the PDFs still move every run. That
# is fine for looking at a change and is one more reason CI is the only
# renderer whose URLs get pasted -- see AGENTS.md next to this script.
#
# The instant is spelled out rather than derived from SOURCE_DATE_EPOCH:
# libfaketime's -f takes a date string and cannot parse "@<epoch>" (it fails
# with "failed to parse FAKETIME timestamp" and takes the build down with it),
# and converting one to the other needs `date -d`, which is GNU-only and this
# script runs on Spencer's Mac. Keep the two in sync if you ever change either.
if command -v faketime >/dev/null; then
  pin_clock() { faketime -f "@$SOURCE_DATE_STRING" "$@"; }
else
  echo "build-harness: faketime not on PATH, PDF timestamps will not be reproducible" >&2
  pin_clock() { "$@"; }
fi

for gv in "$OUT"/*.gv; do
  pdf="${gv%.gv}.pdf"
  # Same drawing and a PDF already on disk: re-rendering is a no-op with the
  # clock pinned, and without it would only move the embedded date. Either way
  # there is nothing to gain. CI always starts from an empty out/, so this only
  # ever fires on a local re-run.
  if [ -f "$pdf" ] && cmp -s "$gv" "$PREV/$(basename "$gv")"; then
    continue
  fi
  pin_clock dot -Tpdf "$gv" -o "$pdf"
done

python3 - "$OUT" <<'PY'
import sys, zipfile
from pathlib import Path

out = Path(sys.argv[1])
drawings = ["power", "psu-pigtail", "board-power", "steppers", "leds"]

members = ["rfq.txt"]
for d in drawings:
    members += [f"{d}.pdf", f"{d}.png", f"{d}.svg", f"{d}.html", f"{d}.bom.tsv"]
members += [f"{d}.yml" for d in drawings]

missing = [m for m in members if not (out / m).is_file()]
if missing:
    sys.exit("build-harness: missing from %s: %s" % (out, ", ".join(missing)))

# Fixed date_time and a fixed member order: same inputs, same archive bytes.
with zipfile.ZipFile(out / "sorter-v2-harness-rfq.zip", "w", zipfile.ZIP_DEFLATED) as z:
    for name in members:
        info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
        info.compress_type = zipfile.ZIP_DEFLATED
        info.external_attr = 0o644 << 16
        z.writestr(info, (out / name).read_bytes())
PY

echo "build-harness: regenerated $OUT from $SRC"
