const ORIGIN = "https://basically-docs.nyc3.digitaloceanspaces.com";

export default {
  async fetch(request) {
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
    const upstream = await fetch(ORIGIN + url.pathname, {
      method: request.method,
      cf: { cacheEverything: true, cacheTtlByStatus: { "200-299": 86400, "400-599": 60 } },
    });
    if (!upstream.ok) {
      return new Response("not found", { status: 404 });
    }
    const headers = new Headers(upstream.headers);
    headers.delete("x-amz-request-id");
    headers.delete("x-amz-id-2");
    headers.set("access-control-allow-origin", "*");
    return new Response(upstream.body, { status: upstream.status, headers });
  },
};
