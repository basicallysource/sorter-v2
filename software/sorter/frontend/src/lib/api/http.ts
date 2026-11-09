// Calls to the machine's backend, in one place. Every call either returns the
// body or throws an ApiError carrying the sentence the server wrote for the
// person at the machine, so a failure is never silent: an HTTP error, a
// validation error, and a 200 whose body says {"ok": false, "message": ...}
// all come out the same way.

export class ApiError extends Error {
	// The HTTP status, or 0 when the machine did not answer at all.
	readonly status: number;
	readonly body: unknown;

	constructor(message: string, status: number, body: unknown = null) {
		super(message);
		this.name = 'ApiError';
		this.status = status;
		this.body = body;
	}
}

type Method = 'GET' | 'POST' | 'PUT' | 'DELETE';

export type RequestOptions = {
	method?: Method;
	// Sent as JSON when given.
	body?: unknown;
	// Query parameters; null and undefined ones are left out.
	query?: Record<string, string | number | boolean | null | undefined>;
	signal?: AbortSignal;
};

// The sentence in an error body: FastAPI's `detail` (a string, or a list of
// validation errors), or the `message` of an {"ok": false} answer.
function sentenceFrom(body: unknown): string | null {
	if (!body || typeof body !== 'object') return typeof body === 'string' && body ? body : null;
	const record = body as Record<string, unknown>;
	const detail = record.detail;
	if (typeof detail === 'string' && detail) return detail;
	if (Array.isArray(detail) && detail.length) {
		const first = detail[0] as { msg?: unknown; loc?: unknown } | null;
		if (first && typeof first.msg === 'string') {
			const where = Array.isArray(first.loc) ? first.loc.filter((p) => p !== 'body').join(' › ') : '';
			return where ? `${where}: ${first.msg}` : first.msg;
		}
	}
	if (typeof record.message === 'string' && record.message) return record.message;
	if (typeof record.error === 'string' && record.error) return record.error;
	return null;
}

export async function request<T>(base: string, path: string, options: RequestOptions = {}): Promise<T> {
	const url = new URL(path, base.endsWith('/') ? base : `${base}/`);
	for (const [key, value] of Object.entries(options.query ?? {})) {
		if (value !== null && value !== undefined) url.searchParams.set(key, String(value));
	}
	const init: RequestInit = { method: options.method ?? 'GET', signal: options.signal };
	if (options.body !== undefined) {
		init.headers = { 'Content-Type': 'application/json' };
		init.body = JSON.stringify(options.body);
	}
	let res: Response;
	try {
		res = await fetch(url, init);
	} catch (e) {
		if (e instanceof DOMException && e.name === 'AbortError') throw e;
		throw new ApiError('The machine did not answer. Check that it is on and on the network.', 0);
	}
	const text = await res.text();
	let body: unknown = null;
	if (text) {
		try {
			body = JSON.parse(text);
		} catch {
			body = text;
		}
	}
	if (!res.ok) {
		throw new ApiError(sentenceFrom(body) ?? `The machine answered ${res.status}.`, res.status, body);
	}
	if (body && typeof body === 'object' && (body as { ok?: unknown }).ok === false) {
		throw new ApiError(sentenceFrom(body) ?? 'The machine could not do that.', res.status, body);
	}
	return body as T;
}

export function getJson<T>(base: string, path: string, options: Omit<RequestOptions, 'method' | 'body'> = {}): Promise<T> {
	return request<T>(base, path, options);
}

export function postJson<T>(base: string, path: string, body?: unknown, options: Omit<RequestOptions, 'method' | 'body'> = {}): Promise<T> {
	return request<T>(base, path, { ...options, method: 'POST', body });
}

// What to show for a caught error.
export function errorMessage(e: unknown, fallback = 'Something went wrong.'): string {
	if (e instanceof Error && e.message) return e.message;
	if (typeof e === 'string' && e) return e;
	return fallback;
}
