#!/usr/bin/env bash
set -euo pipefail
TAG=${1:?usage: publish.sh parts-backend/vX.Y.Z EXPECTED_COMMIT SSH_SIGNING_KEY}
REVISION=${2:?expected full source commit required}
SIGNING_KEY=${3:?SSH signing key path required}
REPO=basicallysource/sorter-v2
[[ "$TAG" =~ ^parts-backend/v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$ ]] || exit 2
[[ "$REVISION" =~ ^[a-f0-9]{40}$ ]] || exit 2
test "$(gh release view "$TAG" -R "$REPO" --json isDraft --jq .isDraft)" = true
STAGE=$(mktemp -d)
trap 'rm -rf "$STAGE"' EXIT
gh release download "$TAG" -R "$REPO" -D "$STAGE" -p release.json -p parts-backend-linux-amd64.tar.gz
SUM=$(shasum -a 256 "$STAGE/parts-backend-linux-amd64.tar.gz" | cut -d ' ' -f1)
jq -e --arg tag "$TAG" --arg revision "$REVISION" --arg sum "$SUM" \
  '.tag == $tag and .revision == $revision and .sha256 == $sum and .schema == 1 and .artifact == "parts-backend-linux-amd64.tar.gz"' "$STAGE/release.json" >/dev/null
ssh-keygen -Y sign -f "$SIGNING_KEY" -n parts-backend-release "$STAGE/release.json"
gh release upload "$TAG" -R "$REPO" "$STAGE/release.json.sig"
gh release edit "$TAG" -R "$REPO" --draft=false --latest=false
