#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p .tools gen ../src/lib/gen
GOBIN="$PWD/.tools" go install google.golang.org/protobuf/cmd/protoc-gen-go@v1.36.12
GOBIN="$PWD/.tools" go install connectrpc.com/connect/cmd/protoc-gen-connect-go@v1.21.0
PATH="$PWD/.tools:$PATH" protoc -I proto --go_out=gen --go_opt=paths=source_relative \
  --connect-go_out=gen --connect-go_opt=paths=source_relative \
  --plugin=protoc-gen-es=../node_modules/.bin/protoc-gen-es \
  --es_out=../src/lib/gen --es_opt=target=ts proto/testprints/v1/testprints.proto
node --input-type=module <<'JS'
import { readFileSync, writeFileSync } from 'node:fs';
const FILE = '../src/lib/gen/testprints/v1/testprints_pb.ts';
writeFileSync(FILE, readFileSync(FILE, 'utf8').trimEnd() + '\n');
JS
