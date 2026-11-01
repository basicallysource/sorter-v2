#!/usr/bin/env bash
set -euo pipefail
TAG=${1:?usage: package.sh parts-backend/vX.Y.Z}
[[ "$TAG" =~ ^parts-backend/v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$ ]] || exit 2
cd "$(dirname "$0")/.."
REVISION=$(git rev-parse HEAD)
test -z "$(git status --porcelain --untracked-files=no)" || { echo 'Package a clean checkout.' >&2; exit 1; }
go test -race ./...
go vet ./...
cd ..
npm ci --no-audit --no-fund
npm run check
npm run build
cd backend
mkdir -p dist
STAGE=$(mktemp -d)
trap 'rm -rf "$STAGE"' EXIT
CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build -trimpath -ldflags "-s -w -X main.version=${TAG#parts-backend/}" -o "$STAGE/parts-backend" ./cmd/parts-backend
cp -R ../build "$STAGE/static"
COPYFILE_DISABLE=1 tar -czf dist/parts-backend-linux-amd64.tar.gz -C "$STAGE" parts-backend static
SUM=$(shasum -a 256 dist/parts-backend-linux-amd64.tar.gz | cut -d ' ' -f1)
printf '{"tag":"%s","revision":"%s","artifact":"parts-backend-linux-amd64.tar.gz","sha256":"%s","schema":1}\n' "$TAG" "$REVISION" "$SUM" > dist/release.json
