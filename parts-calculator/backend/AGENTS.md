# Parts calculator backend

One Go process, SQLite, Connect RPC. The frontend is the SvelteKit app one
directory above. `proto/` owns the contract; generated Go and TypeScript are
committed together. `scripts/generate.sh` regenerates them on the build host.

Read `README.md` for the security boundaries and local/release flow. Run
`go test -race ./...` and `go vet ./...` on the build host before pushing.
Never put real board identifiers, credentials, test content or deployment
addresses in this public repository. Integration tests use fake identity,
asset-service and Discord servers; they never contact production.

Published test targets are immutable. A new CAD version is a new test case.
Drafts and Core boards never enter community feeds. Every mutation and its
change-feed entry commit in one transaction; retries must be idempotent.
