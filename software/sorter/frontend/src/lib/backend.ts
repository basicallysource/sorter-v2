const BACKEND_PORT = 8000;

export function getBackendHttpBase(): string {
	if (typeof window === 'undefined') return `http://localhost:${BACKEND_PORT}`;
	const { protocol, hostname } = window.location;
	return `${protocol}//${hostname}:${BACKEND_PORT}`;
}

export function getBackendWsBase(): string {
	return getBackendHttpBase().replace(/^http/, 'ws');
}

export function machineHttpBaseUrlFromWsUrl(wsUrl: string | null | undefined): string | null {
	if (!wsUrl) return null;
	try {
		const parsed = new URL(wsUrl);
		const protocol = parsed.protocol === 'wss:' ? 'https:' : 'http:';
		return `${protocol}//${parsed.host}`;
	} catch {
		return null;
	}
}

export function machineWsUrlFromHttpBaseUrl(
	backendBaseUrl: string | null | undefined
): string | null {
	if (!backendBaseUrl) return null;
	try {
		const parsed = new URL(backendBaseUrl);
		parsed.protocol = parsed.protocol === 'https:' ? 'wss:' : 'ws:';
		parsed.pathname = '/ws';
		parsed.search = '';
		parsed.hash = '';
		return parsed.toString();
	} catch {
		return null;
	}
}

// The supervisor that served this page restarts its backend even when the
// backend no longer answers. A backend on another host, or a page from the
// dev server, is asked to exit instead, and its supervisor starts it again.
export async function requestBackendRestart(
	backendBaseUrl: string,
	timeoutMs = 4000
): Promise<boolean> {
	const urls = [`${backendBaseUrl}/api/system/restart`];
	if (new URL(backendBaseUrl).hostname === window.location.hostname) {
		urls.unshift('/api/supervisor/restart');
	}
	for (const url of urls) {
		try {
			const response = await fetch(url, { method: 'POST', signal: AbortSignal.timeout(timeoutMs) });
			if (response.ok) return true;
		} catch {
			// the next way, if there is one
		}
	}
	return false;
}

export async function backendHealthy(backendBaseUrl: string, timeoutMs = 2500): Promise<boolean> {
	try {
		const response = await fetch(`${backendBaseUrl}/health`, {
			signal: AbortSignal.timeout(timeoutMs)
		});
		return response.ok;
	} catch {
		return false;
	}
}

export async function waitForBackend(
	backendBaseUrl: string,
	options?: {
		initialDelayMs?: number;
		maxAttempts?: number;
		intervalMs?: number;
		timeoutMs?: number;
	}
): Promise<boolean> {
	const initialDelayMs = options?.initialDelayMs ?? 1500;
	const maxAttempts = options?.maxAttempts ?? 30;
	const intervalMs = options?.intervalMs ?? 500;
	const timeoutMs = options?.timeoutMs ?? 2000;

	await new Promise((resolve) => setTimeout(resolve, initialDelayMs));

	for (let attempt = 0; attempt < maxAttempts; attempt++) {
		if (await backendHealthy(backendBaseUrl, timeoutMs)) return true;
		await new Promise((resolve) => setTimeout(resolve, intervalMs));
	}

	return false;
}

