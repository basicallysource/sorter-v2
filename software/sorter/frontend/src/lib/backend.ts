import { env } from '$env/dynamic/public';

// SPENCER TODO: search function to find this on the local network, shhould not hardcode the address
const fallbackHttpBaseUrl = 'http://localhost:8000';
const rawHttpBaseUrl = env.PUBLIC_BACKEND_BASE_URL ?? fallbackHttpBaseUrl;
const httpBaseUrl = rawHttpBaseUrl.replace(/\/+$/, '');
const supervisorPort = (env.PUBLIC_BACKEND_SUPERVISOR_PORT ?? '8001').trim();
const rawSupervisorBaseUrl = env.PUBLIC_BACKEND_SUPERVISOR_BASE_URL?.replace(/\/+$/, '') ?? null;

const fallbackWsBaseUrl = httpBaseUrl.startsWith('https')
	? httpBaseUrl.replace(/^https/, 'wss')
	: httpBaseUrl.replace(/^http/, 'ws');

export const backendHttpBaseUrl = httpBaseUrl;
export const backendWsBaseUrl = (env.PUBLIC_BACKEND_WS_URL ?? fallbackWsBaseUrl).replace(
	/\/+$/,
	''
);
export const backendSupervisorBaseUrl =
	rawSupervisorBaseUrl ?? supervisorHttpBaseUrlFromBackendHttpBaseUrl(httpBaseUrl);

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

export function supervisorHttpBaseUrlFromBackendHttpBaseUrl(
	backendBaseUrl: string | null | undefined
): string | null {
	if (rawSupervisorBaseUrl) return rawSupervisorBaseUrl;
	if (!backendBaseUrl) return null;
	try {
		const parsed = new URL(backendBaseUrl);
		parsed.port = supervisorPort;
		return parsed.toString().replace(/\/+$/, '');
	} catch {
		return null;
	}
}

export type BackendRestartRequestResult = {
	ok: boolean;
	mode: 'supervisor' | 'backend' | 'none';
};

export type BackendConnectionProbeResult = {
	backendOk: boolean;
	supervisorOk: boolean;
	supervisorState: string | null;
	backendRunning: boolean;
	backendHealthy: boolean;
	restartRequested: boolean;
};

export async function requestBackendRestart(
	backendBaseUrl: string,
	timeoutMs = 4000
): Promise<BackendRestartRequestResult> {
	const supervisorBaseUrl = supervisorHttpBaseUrlFromBackendHttpBaseUrl(backendBaseUrl);
	if (supervisorBaseUrl) {
		try {
			const response = await fetch(`${supervisorBaseUrl}/api/supervisor/restart`, {
				method: 'POST',
				signal: AbortSignal.timeout(timeoutMs)
			});
			if (response.ok) {
				return { ok: true, mode: 'supervisor' };
			}
		} catch {
			// Fall back to the legacy in-process restart path when no supervisor is available.
		}
	}

	try {
		const response = await fetch(`${backendBaseUrl}/api/system/restart`, {
			method: 'POST',
			signal: AbortSignal.timeout(timeoutMs)
		});
		if (response.ok) {
			return { ok: true, mode: 'backend' };
		}
	} catch {
		// The backend may already be down.
	}

	return { ok: false, mode: 'none' };
}

export async function probeBackendConnection(
	backendBaseUrl: string,
	options?: {
		backendTimeoutMs?: number;
		supervisorTimeoutMs?: number;
	}
): Promise<BackendConnectionProbeResult> {
	const backendTimeoutMs = options?.backendTimeoutMs ?? 2500;
	const supervisorTimeoutMs = options?.supervisorTimeoutMs ?? 1500;

	try {
		const response = await fetch(`${backendBaseUrl}/health`, {
			signal: AbortSignal.timeout(backendTimeoutMs)
		});
		if (response.ok) {
			return {
				backendOk: true,
				supervisorOk: false,
				supervisorState: null,
				backendRunning: true,
				backendHealthy: true,
				restartRequested: false
			};
		}
	} catch {
		// Try supervisor next.
	}

	const supervisorBaseUrl = supervisorHttpBaseUrlFromBackendHttpBaseUrl(backendBaseUrl);
	if (supervisorBaseUrl) {
		try {
			const response = await fetch(`${supervisorBaseUrl}/api/supervisor/status`, {
				signal: AbortSignal.timeout(supervisorTimeoutMs)
			});
			if (response.ok) {
				const data = await response.json();
				return {
					backendOk: false,
					supervisorOk: true,
					supervisorState:
						typeof data?.supervisor_state === 'string' ? data.supervisor_state : null,
					backendRunning: Boolean(data?.backend_running),
					backendHealthy: Boolean(data?.backend_healthy),
					restartRequested: Boolean(data?.restart_requested)
				};
			}
		} catch {
			// Supervisor unavailable too.
		}
	}

	return {
		backendOk: false,
		supervisorOk: false,
		supervisorState: null,
		backendRunning: false,
		backendHealthy: false,
		restartRequested: false
	};
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
		const probe = await probeBackendConnection(backendBaseUrl, {
			backendTimeoutMs: timeoutMs,
			supervisorTimeoutMs: Math.min(timeoutMs, 1500)
		});
		if (probe.backendOk) {
			return true;
		}
		await new Promise((resolve) => setTimeout(resolve, intervalMs));
	}

	return false;
}
