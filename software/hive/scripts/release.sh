#!/usr/bin/env bash
# Ship Hive. Tags the current commit and pushes — CI builds the images and
# publishes the release, prod polls and installs itself within ~a minute.
#
#   software/hive/scripts/release.sh v0.3.0
#   software/hive/scripts/release.sh              # auto-bump patch
#
# There is no other deploy path. Nothing is built on the prod box and nothing
# is scp'd to it; see scripts/CUTOVER.md.
set -euo pipefail

BRANCH="${HIVE_RELEASE_BRANCH:-main}"

current_branch="$(git rev-parse --abbrev-ref HEAD)"
if [ "$current_branch" != "$BRANCH" ]; then
  echo "✗ on '$current_branch', releases are cut from '$BRANCH'" >&2
  exit 2
fi
if ! git diff --quiet || ! git diff --cached --quiet; then
  echo "✗ working tree is dirty — commit or stash first" >&2
  exit 2
fi

git fetch --quiet origin "$BRANCH" --tags
if [ "$(git rev-parse HEAD)" != "$(git rev-parse "origin/$BRANCH")" ]; then
  echo "✗ HEAD is not origin/$BRANCH — push or pull first" >&2
  exit 2
fi

if [ $# -ge 1 ]; then
  VER="$1"
else
  last="$(git tag -l 'hive/v*' | sort -V | tail -1)"
  if [ -z "$last" ]; then
    VER="v0.1.0"
  else
    base="${last#hive/v}"
    major="${base%%.*}"; rest="${base#*.}"; minor="${rest%%.*}"; patch="${rest#*.}"
    VER="v${major}.${minor}.$((patch + 1))"
  fi
fi
[[ "$VER" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]] || { echo "✗ version must look like v1.2.3, got '$VER'" >&2; exit 2; }

TAG="hive/$VER"
git rev-parse -q --verify "refs/tags/$TAG" >/dev/null && { echo "✗ $TAG already exists" >&2; exit 2; }

echo "▶ tagging $(git rev-parse --short HEAD) as $TAG"
git tag -a "$TAG" -m "Hive $VER"
git push origin "$TAG"

echo "▶ pushed. CI: https://github.com/basicallysource/sorter-v2/actions/workflows/hive-release.yml"
echo "  prod installs itself within ~1 min of the release publishing:"
echo "    ssh root@100.116.70.1 'journalctl -u hive-release -f'"
