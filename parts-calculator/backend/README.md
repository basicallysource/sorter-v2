# Parts backend

An optional Go service for test prints and assemblies. The calculator remains
statically built. The service can serve that same build and adds `/admin`,
`/test-prints`, identity login, Connect RPC, SQLite and private asset uploads.
Neither page is linked from public navigation. Hiding a page is not an access
control: every data request is authorized on the server.

This foundation is not enabled by the normal static deployment. No real boards,
credentials, identity registrations or deployment destinations are in this repo.

## Development

Use Go 1.26+, Node 26 and protoc 33.4 on a build host. From `parts-calculator`:

```sh
npm ci
bash backend/scripts/generate.sh
npm run check
npm run build
cd backend
go test -race ./...
go vet ./...
go build -trimpath -o dist/parts-backend ./cmd/parts-backend
```

The frontend build needs the repository's Git history for catalog snapshots.
Do not regenerate the CAD catalog to develop this service. Generated Go and
TypeScript RPC code is committed; change the proto first and regenerate both.
The supported transport is unary Connect JSON or protobuf over HTTP/1.1, under
`/rpc`. No websocket, Node server, external database or background model runs.

Copy `deploy/service.env.example` outside the checkout, fill in the service
origins, and supply a base64-encoded random 32-byte session key in its named
file. All origins are HTTPS, with HTTP allowed only for loopback development.
Register `PARTS_ORIGIN/auth/callback` with identity. Source the environment and
run the binary with `PARTS_STATIC_DIR` pointing at the frontend's `build`.

Boards are an operator-owned JSON list, loaded from `PARTS_BOARDS_FILE`:

```json
[
  {
    "id": "print-tests",
    "audience": "community",
    "guild_id": "100000000000000001",
    "forum_id": "100000000000000002",
    "token_sha256": "REPLACE_WITH_SHA256_OF_A_RANDOM_BOARD_TOKEN"
  }
]
```

Use a different random token of at least 32 bytes per board. The server stores
only its SHA-256 digest. The bridge stores the token in its own credential
store. Boards have distinct IDs, forums and credentials. Their audience,
guild and forum become immutable in SQLite on first startup; use a new board
ID for a different destination. Token rotation keeps the same board ID.
An empty board list is valid and publishes nothing.

## Data and authorization

- Anonymous requests receive no test data. Signed-in readers see published
  community tests. Identity's `basically-core` group can administer all tests
  and read Core tests. Identity tokens must have this site's exact origin as
  their audience. Membership and revocation are rechecked within one minute.
  Identity outages return unavailable, without treating the user as signed out.
- The browser uses sealed, HttpOnly, SameSite cookies. HTTPS cookies have the
  `__Host-` prefix. Cookie RPC requests require an exact same-origin `Origin`;
  there is no CORS grant. Scripts use an audience-bound identity bearer token.
  Mixing bearer and cookie credentials is refused.
- A bridge token can read only its board's change feed, bind threads, submit
  member events, and upload that board's evidence. It cannot create or edit
  tests, obtain private download links, or access another board. Guild, forum
  and thread binding are checked on every event and evidence upload.
- The bridge is trusted to attest Discord actors and message ownership. A
  stolen bridge credential can forge activity within that one board. Keep it
  out of browser bundles, model contexts, turn containers and general proxies.
- SQLite uses WAL, foreign keys, bounded reads, a five-second busy timeout and
  one connection. Mutations, audit records, idempotency receipts and change
  snapshots commit together. Network requests never hold a database transaction.
- Drafts never enter the feed. Publishing requires at least one Onshape
  document/version/element reference. Targets, files, kind and board are fixed
  after publication. New CAD version means a new test. States are draft → open,
  open ↔ closed, then archived; published tests cannot return to draft.
- Every entity ID and admin request ID is UUIDv7. Admin saves require the
  expected revision. Retry the identical request with the same request ID;
  changing a request under an existing ID is rejected. Feed cursors are internal
  monotonic sequence numbers, scoped and indexed by board.
- Claims are per Discord member. New claims require an open test; members can
  release their own claim after closure. Feedback edits use event timestamps;
  old events cannot overwrite newer ones, and deletion tombstones cannot be
  resurrected. All message text is data, never an instruction or rendered HTML.

## Manual authoring API

`proto/testprints/v1/testprints.proto` is the contract. The admin page performs
the same operations as a script:

1. `AdminService/SaveTest`: create a draft with a new UUIDv7 `requestId`,
   `expectedRevision: "0"`, and `test` containing title, instructions, kind,
   boardId, state `draft`, and pinned `references`.
2. Upload a file as a raw body to
   `POST /api/test-print-assets/{test_id}?filename=part.step`, with its correct
   content type and the same identity bearer credential. Attach the returned
   asset ID in the next `SaveTest`. Uploading alone does not change a test.
3. Save state `open` using the latest revision and a fresh request ID. Once
   published, title and test instructions can change, but the target cannot.

Connect JSON uses `Content-Type: application/json` and
`Connect-Protocol-Version: 1`. Int64 fields such as revision and sequence are
JSON strings. Paths include `/rpc/testprints.v1.` before the service name.

Assets are always uploaded with `visibility=private` in a dedicated namespace.
Configure an asset-service credential scoped to reading and writing only that
namespace, plus a storage budget there. The backend verifies the stored byte
count and SHA-256, persists the asset key rather than its signed URL, and
requests a fresh expiring URL only after reader authorization. A public
deduplicated asset is refused. Use a namespace never used for public uploads.
Models allow STL, STEP and 3MF; images allow PNG, JPEG and WebP. Two concurrent
uploads, 32 MiB per file, at most 32 models and 1,000 stored assets per test.
Temporary upload files are deleted on every completed request.

## Discord synchronization

Poll `DiscordBoardService/SyncChanges` every three minutes with jitter. Start
at sequence zero; request up to 100 changes, process each in order, then persist
its sequence. `hasMore` permits bounded catch-up. An idle poll returns no rows;
there is no need to scan Discord for unchanged tests.

Create one forum thread per test, then call `BindThread` with the configured
guild/forum and returned thread ID. A binding is immutable. Only after binding
may the bridge call `ApplyEvent` with `claim`, `release`, `feedback` or
`delete_feedback`. Use a stable SHA-256 event ID, the authenticated Discord
actor, message/interaction ID and its original timestamp. A delete event
retains the original author ID. Evidence uploads use the raw upload route with
`guild_id`, `forum_id` and `thread_id` query parameters, then supply the asset
IDs in the feedback event. Never send arbitrary asset-service keys or URLs.

Keep a durable bridge outbox. A timeout may mean the write committed; resend
the identical event. The receipt records its result. Do not expire receipts,
change rows or tombstones independently of bridge cursor/outbox retention.
Thread deletion or an ambiguous creation needs explicit reconciliation, not
automatic duplicate creation. Exact claims policy, structured outcomes and
short printed lookup labels can build on these APIs without changing custody
of identity, files or Discord credentials.

## Release installation

The Linux amd64 binary is statically linked. `scripts/package.sh` runs the
checks and builds the binary plus static site into one compressed archive.
The `parts-backend/vX.Y.Z` tag workflow uploads an **unsigned draft** release.
It contains no deployment credential or signing key.

After reviewing the source and successful build, an operator runs
`scripts/publish.sh TAG EXPECTED_FULL_COMMIT SSH_SIGNING_KEY`. This checks the
artifact checksum and source revision, signs `release.json` using the
`parts-backend-release` SSH signature namespace, and publishes the release.
The signing key stays outside GitHub Actions. Anyone publishing an unsigned or
tampered release cannot make the updater execute it.

Install the service and timer in `deploy/` on a Linux host behind an HTTPS
reverse proxy. The application binds loopback and runs as the dedicated
`parts-backend` user. Provision `/var/lib/parts-backend` owned by that user,
secret files readable only by it, and a root-owned `/opt/parts-backend`.
Bootstrap `/opt/parts-backend/updater` from a manually verified signed release;
the updater is intentionally a stable binary separate from `current`.
Put the independently trusted public key in root-owned
`/etc/parts-backend/allowed_signers`, in this format:

```text
parts-backend ssh-ed25519 PUBLIC_KEY_MATERIAL
```

The timer checks every five minutes with jitter. It considers only newer
stable `parts-backend/` tags, verifies the signature and checksum, rejects
archive links/traversal and oversized contents, checks the binary's version,
takes a consistent SQLite snapshot, atomically switches `current`, restarts,
and checks `/healthz` for the expected version. Failure restores a compatible
previous binary without rolling back live database contents. Failed versions
are quarantined until an operator inspects `failed-release`. A stale
`update.lock` after a killed updater requires inspection before removal.

Schema 1 is the only automatic upgrade currently accepted. A future schema
change must add an explicit migration and compatibility policy before release;
the server refuses databases newer than it understands. `-backup DESTINATION`
uses SQLite's online snapshot operation, including WAL data. Successful updates
retain the current and previous releases and the latest three update snapshots.
Keep separate off-host backups according to the operator's retention policy.
Do not restore a database over a running service. Serve RPC and login from the
same origin as the private preview. The public static host can remain separate.

## Verification and remaining rollout work

Tests cover authorization, wrong audiences, identity outages, board isolation,
idempotent concurrent saves, revision conflicts, immutable targets, ordered
events, deletion tombstones, asset ownership, byte integrity, snapshots,
signed release installation, archive boundaries and failed-health rollback.
Use fixture identity/storage/Discord endpoints for local checks; no dev auth
bypass exists in the shipped binary.

Before enabling anything, provision the private preview origin, identity
callback, dedicated asset namespace, per-board credentials, signing trust and
forum permissions. Test against staging identity/storage and a designated test
forum. None of those external changes is performed by adding this code.
