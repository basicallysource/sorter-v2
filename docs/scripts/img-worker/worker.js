const ORIGIN = "https://basically-docs.nyc3.digitaloceanspaces.com";

// The docs append `?v=<sha>` to every asset URL, so a URL carrying one names an
// immutable snapshot and can be cached hard. A bare URL is a mutable ref and
// gets the bucket's own short TTL.
const IMMUTABLE = "public, max-age=31536000, immutable";
const MUTABLE = "public, max-age=60";

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
    // API can reach the object when we need to force it. The query string is
    // deliberately not forwarded upstream — it identifies a version of the
    // path, not a different object in the bucket.
    const cache = caches.default;
    const key = new Request(url.toString(), { method: "GET" });

    let response = await cache.match(key);
    if (!response) {
      const upstream = await fetch(ORIGIN + url.pathname);
      if (!upstream.ok) {
        return new Response("not found", { status: 404 });
      }
      const headers = new Headers(upstream.headers);
      headers.delete("x-amz-request-id");
      headers.delete("x-amz-id-2");
      headers.set("access-control-allow-origin", "*");
      headers.set("cache-control", url.searchParams.has("v") ? IMMUTABLE : MUTABLE);
      response = new Response(upstream.body, { status: upstream.status, headers });
      ctx.waitUntil(cache.put(key, response.clone()));
    }

    if (request.method === "HEAD") {
      return new Response(null, { status: response.status, headers: response.headers });
    }
    return response;
  },
};
