const ORIGIN = "https://basically-docs.nyc3.digitaloceanspaces.com";

const IMMUTABLE = "public, max-age=31536000, immutable";
const MUTABLE = "public, max-age=60";

// What may be cached for a year. Two things qualify, and the difference
// matters:
//
//   1. A content-addressed name -- `harness/power.2021d6c5f7.png`, where the
//      hex is a hash of the bytes. Nothing can ever be served under that name
//      but those bytes, so `immutable` is a fact about the object.
//   2. A URL carrying `?v=<sha>`, which is a promise by the caller that the
//      path is a snapshot. Photos work this way (upload_image.py + a name
//      nobody reuses) and it is only as good as that discipline.
//
// The harness used to rely on (2) over a path that was overwritten on every
// render, which made the header a lie and pinned a stale drawing in readers'
// caches for a year. It relies on (1) now. Do not "simplify" this back to the
// query check alone: a content-addressed URL has no reason to carry a buster,
// and without the name rule it would be served with the short TTL.
// Matches the hash segment anywhere in the filename, not just before the last
// dot: `power.514757618c.bom.tsv` keeps its whole `.bom.tsv` suffix chain, so
// anchoring to a single trailing extension would miss every BOM.
const CONTENT_ADDRESSED = /\.[0-9a-f]{10,}\./;

function cacheControlFor(url) {
  if (CONTENT_ADDRESSED.test(url.pathname)) return IMMUTABLE;
  return url.searchParams.has("v") ? IMMUTABLE : MUTABLE;
}

export default {
  async fetch(request, env, ctx) {
    if (request.method !== "GET" && request.method !== "HEAD") {
      return new Response("method not allowed", { status: 405 });
    }
    const url = new URL(request.url);
    if (url.pathname === "/") {
      return new Response("basically docs image host", {
        status: 200,
        headers: { "content-type": "text/plain" },
      });
    }

    // Cache under this hostname, keyed on the full URL including `?v=`. Two
    // things depend on that: a new render is a new key, so the buster actually
    // busts; and the key is a basically.website URL, so the zone's purge_cache
    // API can reach the object when we need to force it.
    const cache = caches.default;
    const key = new Request(url.toString(), { method: "GET" });

    // `x-img-cache` is the only window into this cache from outside. Without
    // it the 2026-08-09 staleness took hours to pin down, because a stale
    // object and a fresh one are indistinguishable over the wire.
    let response = await cache.match(key);
    let hit = true;
    if (!response) {
      hit = false;
      // The subrequest must not be served from Cloudflare's own cache: that
      // entry is keyed on the Spaces URL with no `?v=` in it, which is the
      // exact staleness this worker exists to avoid — and .png is a
      // default-cached extension, so it happens without anyone asking. Belt
      // and braces: tell the edge not to cache it, and carry the buster
      // upstream so the key differs anyway. Spaces ignores unknown query
      // params on GET (verified), it just wants the path.
      const upstream = await fetch(ORIGIN + url.pathname + url.search, {
        cf: { cacheEverything: true, cacheTtlByStatus: { "200-599": -1 } },
      });
      if (!upstream.ok) {
        return new Response("not found", { status: 404 });
      }
      const headers = new Headers(upstream.headers);
      headers.delete("x-amz-request-id");
      headers.delete("x-amz-id-2");
      headers.delete("age");
      headers.delete("cf-cache-status");
      headers.set("access-control-allow-origin", "*");
      headers.set("cache-control", cacheControlFor(url));
      response = new Response(upstream.body, { status: upstream.status, headers });
      ctx.waitUntil(cache.put(key, response.clone()));
    }

    response = new Response(request.method === "HEAD" ? null : response.body, {
      status: response.status,
      headers: response.headers,
    });
    response.headers.set("x-img-cache", hit ? "hit" : "miss");
    return response;
  },
};
