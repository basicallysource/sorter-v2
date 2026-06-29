// SPA mode for adapter-static: render fully on the client and talk to the FastAPI
// Station server at runtime. No SSR/prerender — the AGX serves the built bundle as
// static files, so there is no Node server in production.
export const ssr = false;
export const prerender = false;
