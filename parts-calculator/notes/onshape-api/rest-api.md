# Onshape REST API — notes (focus: exporting part STLs)

## TL;DR — can we export part STLs via the API?

**Yes.** The REST API can export:
- a **whole Part Studio** to one STL, or
- **one specific part** (by part id) to its own STL, or
- a Part Studio filtered to a **subset of parts** (`partIds=...`).

So we could automate the whole `inbox/` step: pull each known-good part straight
from the Onshape document as an STL instead of exporting by hand. STL is exactly
the format we feed OrcaSlicer.

Caveats: it's an async-ish flow with a **307 redirect** to a download server, and
if you use HMAC signing you must **re-sign after the redirect**. Tessellation
(facet density) is controllable via query params.

## Base URL & versioning

```
https://cad.onshape.com/api/v{N}/...     e.g. v6, v10, v12
```
Pin a version. The interactive explorer ("Glassworks") is at
https://cad.onshape.com/glassworks/explorer/ — best place to find exact paths/params.

## The d / w|v|m / e identifiers

Every call targets a document + a context + an element. Pull these from the
Onshape URL of the part studio:
```
https://cad.onshape.com/documents/{did}/w/{wid}/e/{eid}
                                    ^did      ^wid    ^eid
```
- **did** = document id
- **wvm** = one of `w` (workspace, live), `v` (version, frozen), `m` (microversion)
- **wvmid** = the id for that context. **Use a version (`v`) for reproducible exports.**
- **eid** = element id (the specific Part Studio tab)

## Auth — API keys

1. Create keys at the **Developer Portal**: https://cad.onshape.com/appstore/dev-portal
   → "API keys" → "Create new API key". Grant scopes (read is enough for export).
   The **secret is shown once** — save it. Keys are tied to your account; never commit them.
2. Two ways to authenticate:
   - **Basic auth** (simplest, fine for a local/internal script): send
     `access key` as username, `secret key` as password.
     `requests.get(url, auth=(ACCESS, SECRET), headers=...)`
   - **HMAC request signature** (required for production/redirect-following): build
     a signed `Authorization` header per request. Official helper libs:
     https://github.com/onshape-public/apikey (Python/Node samples).

Docs: https://onshape-public.github.io/docs/auth/apikeys/

## Listing parts (to get part ids)

```
GET /api/v12/parts/d/{did}/v/{vid}/e/{eid}?withThumbnails=false
```
Returns each part's `partId`, `name`, material, etc. Use the `partId` for per-part
STL export. (Part ids look like `JHD`, `JLD`, ...)

## Export endpoints

### One specific part → STL
```
GET /api/v6/parts/d/{did}/v/{vid}/e/{eid}/partid/{partid}/stl
      ?mode=binary&units=millimeter&grouping=true&scale=1
```

### Whole Part Studio → STL (optionally a subset of parts)
```
GET /api/v6/partstudios/d/{did}/v/{vid}/e/{eid}/stl
      ?mode=binary&units=millimeter&partIds=JLD,JHD
```

### Useful STL query params
- `mode` = `text` | `binary` (binary = smaller; what we want)
- `units` = `millimeter` | `inch` (use **millimeter** — matches our slicer pipeline)
- `grouping` = true (group surfaces into one solid)
- `scale` = 1
- Tessellation quality: `angularTolerance`, `chordTolerance`, `maxFacetWidth`,
  `minFacetWidth`, `resolution` (coarse/medium/fine/...). Finer = more triangles.

### The 307 redirect
Synchronous STL export returns **HTTP 307** redirecting to a transient download
URL on a modeling/translation server.
- With **basic auth**: `requests` following redirects usually just works.
- With **HMAC**: you must **re-sign** the request for the new path/host before
  following it (the signature covers method + path + query + date + nonce).
There's also a fully async path (POST a translation, poll for completion, then GET
the result) documented under Import/Export — needed for formats like STEP, but STL
has the direct synchronous endpoint above.
Import/Export docs: https://onshape-public.github.io/docs/api-adv/translation/

## Configurations (if a part studio is configurable)
1. `GET /api/.../elements/d/{did}/.../configuration` → list configuration inputs.
2. Encode a chosen configuration via the `configurationencodings` endpoint.
3. Pass the encoded string as `&configuration=...` on the STL export call.

## Rate limits
Onshape enforces per-app/per-account rate limits (HTTP 429 on exceed). For bulk
export, throttle and back off. Exports are also relatively heavy server-side, so
cache results (we already cache slices by STL bytes).

## Minimal Python sketch (basic auth)

```python
import requests
BASE = "https://cad.onshape.com"
AUTH = (ACCESS_KEY, SECRET_KEY)
H = {"Accept": "application/json"}

did, vid, eid = "...", "...", "..."   # from the Onshape URL (use a Version)

# 1) list parts
parts = requests.get(f"{BASE}/api/v12/parts/d/{did}/v/{vid}/e/{eid}",
                     auth=AUTH, headers=H).json()

# 2) export each part to a binary STL (requests follows the 307)
for p in parts:
    pid = p["partId"]
    r = requests.get(
        f"{BASE}/api/v6/parts/d/{did}/v/{vid}/e/{eid}/partid/{pid}/stl",
        params={"mode": "binary", "units": "millimeter", "grouping": "true"},
        auth=AUTH, headers={"Accept": "application/octet-stream"},
        allow_redirects=True,
    )
    open(f"{p['name']}.stl", "wb").write(r.content)
```

## How this could plug into the calculator
- Add an Onshape doc/version + element ids per part (or per part studio) to the
  manifest, plus each `partId`.
- A `slicer/fetch_onshape.py` step pulls fresh STLs into `slicer/parts/` before
  slicing — replaces the manual Onshape-export-into-inbox workflow and makes the
  "known-good iteration" literally a pinned Onshape **version**.
- Keep keys in an env var / untracked file, never committed.

## Sources
- API keys: https://onshape-public.github.io/docs/auth/apikeys/
- Quick start: https://onshape-public.github.io/docs/api-intro/quickstart/
- Import/Export (translation): https://onshape-public.github.io/docs/api-adv/translation/
- API key sample libs: https://github.com/onshape-public/apikey
- Bulk STL config export example: https://github.com/ZimengXiong/OnshapeBulkExportConfigurations
- Glassworks API explorer: https://cad.onshape.com/glassworks/explorer/
