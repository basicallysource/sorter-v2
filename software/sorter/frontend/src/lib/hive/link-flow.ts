export const DEFAULT_HIVE_URL = 'https://hive.basicly.website';

const PENDING_LINK_KEY = 'sorter.hiveLink.pending.v1';

type PendingHiveLink = {
	state: string;
	hiveUrl: string;
	apiUrl?: string;
	targetName: string;
	createdAt: number;
};

export type HiveLinkResult = {
	completed: boolean;
	targetName?: string;
	machineName?: string;
	message?: string;
};

function isLocalHost(hostname: string): boolean {
	const host = hostname.toLowerCase();
	return host === 'localhost' || host === '127.0.0.1' || host === '::1';
}

function createState(): string {
	if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
		return crypto.randomUUID();
	}
	return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
}

function parseStoredPending(): PendingHiveLink | null {
	if (typeof sessionStorage === 'undefined') return null;
	try {
		const raw = sessionStorage.getItem(PENDING_LINK_KEY);
		if (!raw) return null;
		const parsed = JSON.parse(raw) as Partial<PendingHiveLink>;
		if (
			typeof parsed.state !== 'string' ||
			typeof parsed.hiveUrl !== 'string' ||
			typeof parsed.targetName !== 'string'
		) {
			return null;
		}
		return {
			state: parsed.state,
			hiveUrl: parsed.hiveUrl,
			apiUrl: typeof parsed.apiUrl === 'string' ? parsed.apiUrl : undefined,
			targetName: parsed.targetName,
			createdAt: typeof parsed.createdAt === 'number' ? parsed.createdAt : 0
		};
	} catch {
		return null;
	}
}

function clearHashFromAddressBar() {
	if (typeof window === 'undefined') return;
	const cleanUrl = `${window.location.pathname}${window.location.search}`;
	window.history.replaceState(null, document.title, cleanUrl);
}

function cleanPending() {
	if (typeof sessionStorage === 'undefined') return;
	sessionStorage.removeItem(PENDING_LINK_KEY);
}

function errorMessageFromResponseText(text: string): string {
	try {
		const body = JSON.parse(text);
		if (typeof body?.detail === 'string') return body.detail;
		if (typeof body?.error === 'string') return body.error;
	} catch {
		// Use the raw response body below.
	}
	return text || 'Hive link could not be saved.';
}

function safeNormalizeHiveApiBaseUrl(input: string | null | undefined): string | null {
	if (!input) return null;
	try {
		return normalizeHiveApiBaseUrl(input);
	} catch {
		return null;
	}
}

export function normalizeHiveBaseUrl(input: string): string {
	const trimmed = input.trim();
	if (!trimmed) return '';

	const withProtocol = trimmed.includes('://')
		? trimmed
		: (() => {
				const hostHint = trimmed.split('/', 1)[0].split(':', 1)[0].replace(/^\[|\]$/g, '');
				const scheme = isLocalHost(hostHint) ? 'http' : 'https';
				return `${scheme}://${trimmed}`;
			})();

	const parsed = new URL(withProtocol);
	if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') {
		throw new Error('Hive URL must start with http:// or https://.');
	}
	parsed.hash = '';
	parsed.pathname = '';
	parsed.search = '';
	return parsed.toString().replace(/\/$/, '');
}

export function normalizeHiveAppBaseUrl(input: string): string {
	const parsed = new URL(normalizeHiveBaseUrl(input));
	if (isLocalHost(parsed.hostname) && parsed.port === '8002') {
		parsed.port = '5174';
	}
	return parsed.toString().replace(/\/$/, '');
}

export function normalizeHiveApiBaseUrl(input: string): string {
	const parsed = new URL(normalizeHiveBaseUrl(input));
	if (isLocalHost(parsed.hostname) && parsed.port === '5174') {
		parsed.port = '8002';
	}
	return parsed.toString().replace(/\/$/, '');
}

export function defaultHiveTargetName(hiveUrl: string): string {
	try {
		const parsed = new URL(normalizeHiveBaseUrl(hiveUrl));
		if (isLocalHost(parsed.hostname)) return 'Local Hive';
		if (parsed.hostname === 'hive.basicly.website') return 'Hive Community';
		return parsed.hostname;
	} catch {
		return 'Hive';
	}
}

export function beginHiveLink({
	hiveUrl,
	targetName,
	machineName,
	returnPath
}: {
	hiveUrl: string;
	targetName?: string;
	machineName?: string;
	returnPath: string;
}) {
	if (typeof window === 'undefined' || typeof sessionStorage === 'undefined') {
		throw new Error('Hive linking can only be started in the browser.');
	}

	const normalizedHiveUrl = normalizeHiveAppBaseUrl(hiveUrl);
	const state = createState();
	const resolvedTargetName = (targetName ?? '').trim() || defaultHiveTargetName(normalizedHiveUrl);
	const returnTo = new URL(returnPath, window.location.origin).toString();

	const pending: PendingHiveLink = {
		state,
		hiveUrl: normalizedHiveUrl,
		apiUrl: normalizeHiveApiBaseUrl(hiveUrl),
		targetName: resolvedTargetName,
		createdAt: Date.now()
	};
	sessionStorage.setItem(PENDING_LINK_KEY, JSON.stringify(pending));

	const linkUrl = new URL('/link-machine', normalizedHiveUrl);
	linkUrl.searchParams.set('return_to', returnTo);
	linkUrl.searchParams.set('state', state);
	linkUrl.searchParams.set('target_name', resolvedTargetName);
	linkUrl.searchParams.set('sorter_origin', window.location.origin);
	const suggestedMachineName = (machineName ?? '').trim();
	if (suggestedMachineName) {
		linkUrl.searchParams.set('suggested_machine_name', suggestedMachineName);
	}

	window.location.href = linkUrl.toString();
}

export async function completeReturnedHiveLink(backendBaseUrl: string): Promise<HiveLinkResult> {
	if (typeof window === 'undefined') return { completed: false };
	if (!window.location.hash) return { completed: false };

	const hash = new URLSearchParams(window.location.hash.slice(1));
	if (hash.get('hive_link') !== '1') return { completed: false };

	clearHashFromAddressBar();

	const pending = parseStoredPending();
	if (!pending) {
		throw new Error('Hive returned a link response, but no pending Sorter link was found.');
	}
	if (hash.get('state') !== pending.state) {
		throw new Error('Hive link response could not be verified.');
	}

	const apiToken = hash.get('api_token') ?? '';
	if (!apiToken) {
		throw new Error('Hive did not return a machine token.');
	}

	const machineId = hash.get('machine_id') ?? '';
	const machineName = hash.get('machine_name') ?? '';
	const targetName = hash.get('target_name') || pending.targetName;
	const tokenPrefix = hash.get('token_prefix') ?? '';
	const hiveApiUrl =
		safeNormalizeHiveApiBaseUrl(hash.get('api_base_url')) ||
		pending.apiUrl ||
		normalizeHiveApiBaseUrl(pending.hiveUrl);
	const base = backendBaseUrl.replace(/\/+$/, '');

	const res = await fetch(`${base}/api/settings/hive/link`, {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({
			target_name: targetName,
			url: hiveApiUrl,
			api_token: apiToken,
			machine_id: machineId,
			machine_name: machineName,
			token_prefix: tokenPrefix,
			enabled: true
		})
	});

	if (!res.ok) {
		throw new Error(errorMessageFromResponseText(await res.text()));
	}

	cleanPending();
	return {
		completed: true,
		targetName,
		machineName,
		message: `Connected ${machineName || targetName} to ${hiveApiUrl}.`
	};
}
