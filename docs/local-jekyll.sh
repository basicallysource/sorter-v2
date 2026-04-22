#!/usr/bin/env bash
set -euo pipefail

MODE="${1:-build}"
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

COMMON_SETUP='
  apt-get update >/dev/null &&
  apt-get install -y build-essential git pkg-config libffi-dev libxml2-dev libxslt1-dev zlib1g-dev >/dev/null &&
  gem install bundler -v 2.3.25 --no-document >/dev/null &&
  bundle _2.3.25_ install >/dev/null '

case "$MODE" in
build)
  docker run --rm \
    -v "$ROOT_DIR:/site" \
    -w /site \
    ruby:3.1-bookworm \
    bash -lc "$COMMON_SETUP && bundle _2.3.25_ exec jekyll build"
  ;;
serve)
  docker run --rm -it \
    -p 4000:4000 \
    -v "$ROOT_DIR:/site" \
    -w /site \
    ruby:3.1-bookworm \
    bash -lc "$COMMON_SETUP && bundle _2.3.25_ exec jekyll serve --host 0.0.0.0 --livereload --force_polling"
  ;;
*)
  echo "Usage: $0 [build|serve]" >&2
  exit 1
  ;;
esac
