import { env } from '$env/dynamic/public';

// The Station server (FastAPI on the AGX) serves this SPA as static files, so by default
// the API lives on the SAME origin the page was loaded from — open http://<host>.local:8000
// from any device on the LAN and it just works, no hardcoded address.
//
// `PUBLIC_BACKEND_BASE_URL` still overrides this for split dev (e.g. `vite dev` on a laptop
// pointing at a remote AGX). When neither applies (build-time/SSR with no window), fall back
// to localhost for local dev only.
function resolveHttpBaseUrl(): string {
	if (env.PUBLIC_BACKEND_BASE_URL) return env.PUBLIC_BACKEND_BASE_URL;
	if (typeof window !== 'undefined') return window.location.origin;
	return 'http://localhost:8000';
}

const httpBaseUrl = resolveHttpBaseUrl().replace(/\/+$/, '');

const fallbackWsBaseUrl = httpBaseUrl.startsWith('https')
	? httpBaseUrl.replace(/^https/, 'wss')
	: httpBaseUrl.replace(/^http/, 'ws');

export const backendHttpBaseUrl = httpBaseUrl;
export const backendWsBaseUrl = (env.PUBLIC_BACKEND_WS_URL ?? fallbackWsBaseUrl).replace(
	/\/+$/,
	''
);
