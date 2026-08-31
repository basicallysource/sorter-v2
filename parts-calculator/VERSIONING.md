# Versioning: how parts are identified, revised, and removed

The short version of how this catalog handles change. When someone asks "can
we delete this part?" or "how do I revise this?", this page is the answer to
point at. The authored source of truth is `catalog/parts.json`; the mechanics
live in `catalog/generate.py` and are enforced by CI.

## Identity: the uid

Every part, hardware item, assembly, version, and candidate gets a **uid** when
it is added (`catalog/mint_uid.py`). A uid names one design revision. It is the
string engraved into printed plastic, and the site serves a permanent page at
`/u/<uid>` for every uid ever minted.

**A uid is a permanent promise.** Once minted, it must keep resolving forever —
someone may hold a print with it stamped on, or a link to its page. CI
(`scripts/check_generated_pins.py`) fails any change that drops a uid from
`parts.json`. There is no override; entries are never deleted.

## Revising a part

A revision is an **addition**, never an edit-in-place:

1. New geometry is exported and published; its bytes get a new content hash and
   therefore a new URL. Old URLs keep serving forever (the asset service has no
   delete or overwrite operation — see the "Artifacts and the asset service"
   section of `CLAUDE.md`).
2. The new revision gets a new uid. `stamp_versions.py` archives the outgoing
   design into the part's `versions[]` with its uid and `stl_hash` (the sha256
   of its final bytes). Historical geometry is fetched by that pin — never
   reconstructed from git history.
3. The new `versions[]` entry declares its **`breaking` bit** (next section).
4. Regenerate (`catalog/generate.py`) and commit source and generated data
   together in the same change.

A **candidate** is a revision under test for a part's slot: its own uid and
`stl_hash`, no version number until adopted. Candidates are never deleted,
only marked `superseded_by` / `rejected_at`.

## The `breaking` bit

From 2026-08-31, every new `versions[]` entry — part or assembly — declares
`breaking: true | false`. It answers exactly one question about exactly one
node:

> **Can an old physical instance of THIS node still be used in its place?**

For a part an instance is a print; for an assembly it is an assembled unit.
`false`: old instances stay interchangeable with the new revision. `true`:
old instances don't fit or function in the current design — scrap for
current builds (still valid for building the archived old structure they
came from).

The rules that keep the bit meaningful:

- **Each node speaks only for itself.** An assembly can be reworked inside —
  parts merged, members swapped — and still be `breaking: false` if it mates
  outward the same way; whoever holds the old assembled unit keeps using it.
- **Bits are set bottom-up at authoring time, on the nodes the change
  touched.** A change is recorded on the node that owns what changed:
  geometry → the part; membership or quantities → the assembly that owns
  the lines. Then ask the same question one level up, and stop as soon as
  the answer is false. There is never a search for "what broke" after the
  fact — the causal chain and the edit are the same thing.
- **First versions and new identities carry no bit.** Nothing older exists
  to break. A replacement design is a *new* part or assembly (new uid, v1),
  not a revision of the thing it replaces — the replaced one is retired from
  the lines that used it, unrevised.
- **Unused ≠ breaking.** A part whose slot disappeared is removed from
  lines (see below); its geometry didn't stop fitting anything. Never use
  `breaking` to express removal.
- **Candidates carry no bit.** A candidate is a parallel experiment, not a
  revision; the judgment happens on the version minted if it is adopted.

Why: whether any old print fits today's machine becomes *computable* from
the chain of bits — never reconstructed from memory or CAD archaeology.
`scripts/check_versioning.py` (CI) refuses a new revision without its bit.

## Revising an assembly

A structural change to an assembly's `lines` — a member removed or replaced,
a quantity changed — is a revision and must be **stamped** in the same
change:

1. Bump the assembly's `version`.
2. Append a `versions[]` entry: new version number, `date`, `message`, its
   `breaking` bit, `"commit": null` (pending).
3. After committing, run `catalog/stamp_versions.py`: it ties the entry to
   its commit and snapshots the superseded lines with each member's uid of
   the day, so the box as built then reads back part by part.

One exemption: purely *adding* lines to a `stub`/`partial` assembly is
completing the record of what was always physically there, not changing the
design — no stamp needed. The moment a line is removed or altered, or the
assembly is no longer partial, the full rule applies. CI enforces both
halves (`scripts/check_versioning.py`).

## Removing a part from the machine

The entry never leaves `parts.json` — its **usage** does:

1. **Remove it from every assembly and section.** With zero references it
   drops out of the BOM, the buy list, layer counts, and the all-parts bundle.
   For a builder, it no longer exists.
2. **Retire the entry in place.** In its `description`/`note`, record that it
   is unused as of the date, why it was removed, and what replaced it — plus a
   "do not re-add" warning if old docs or photos still show it.
3. **Update the docs pages** that had steps using it.
4. **Regenerate and commit** source + generated together.
5. **Leave the assets alone.** STLs, renders, and stamped downloads stay at
   their hash URLs by design; they cost nothing and old links keep working.

Worked example: `washer-m3-15`, retired in
[#479](https://github.com/basicallysource/sorter-v2/pull/479).

## What never happens

- Deleting an entry from `parts.json` (CI refuses).
- Reusing a uid, or minting a new uid for unchanged geometry (a re-export of
  the same design is a new hash under the same uid).
- Deleting or overwriting an asset (the service cannot).
- Hand-editing `src/lib/data/catalog.generated.json` (it is an output).
- A new revision without its `breaking` bit, or a structural change to an
  assembly's lines without a version stamp (CI refuses both, from
  2026-08-31; `scripts/check_versioning.py`).
- Compatibility claims between arbitrary version pairs. Compatibility is
  computed from the chain of `breaking` bits; anything the chain can't
  derive is honestly unknown.
