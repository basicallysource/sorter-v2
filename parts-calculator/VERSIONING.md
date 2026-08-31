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
3. Regenerate (`catalog/generate.py`) and commit source and generated data
   together in the same change.

A **candidate** is a revision under test for a part's slot: its own uid and
`stl_hash`, no version number until adopted. Candidates are never deleted,
only marked `superseded_by` / `rejected_at`.

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
