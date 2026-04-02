export interface ApiError {
	ok: false;
	error: string;
	code: string;
}

export interface User {
	id: string;
	email: string;
	display_name: string | null;
	github_login: string | null;
	avatar_url: string | null;
	has_password: boolean;
	role: 'member' | 'reviewer' | 'admin';
	is_active: boolean;
	created_at: string;
}

export interface Machine {
	id: string;
	name: string;
	description: string | null;
	token_prefix: string;
	last_seen_at: string | null;
	is_active: boolean;
	created_at: string;
}

export interface MachineWithToken extends Machine {
	raw_token: string;
}

export interface Sample {
	id: string;
	machine_id: string;
	upload_session_id: string;
	local_sample_id: string;
	source_role: string | null;
	capture_reason: string | null;
	captured_at: string | null;
	image_width: number | null;
	image_height: number | null;
	detection_algorithm: string | null;
	detection_bboxes: unknown | null;
	detection_count: number | null;
	detection_score: number | null;
	extra_metadata: Record<string, unknown> | null;
	review_status: 'unreviewed' | 'in_review' | 'accepted' | 'rejected' | 'conflict';
	review_count: number;
	accepted_count: number;
	rejected_count: number;
	uploaded_at: string;
	resolved_at: string | null;
}

export interface SampleDetail extends Sample {
	has_full_frame: boolean;
	has_overlay: boolean;
}

export interface SavedSampleAnnotationBody {
	id: string | null;
	purpose: string | null;
	value: string | null;
}

export interface SavedSampleAnnotation {
	id: string;
	source: 'primary' | 'candidate' | 'manual';
	shape_type: string;
	geometry: Record<string, unknown> | null;
	bodies: SavedSampleAnnotationBody[];
}

export interface SampleAnnotationsPayload {
	version: 'sorthive-annotorious-v1';
	updated_at: string | null;
	updated_by_display_name: string | null;
	annotations: SavedSampleAnnotation[];
}

export interface SaveSampleAnnotationsResponse {
	ok: boolean;
	annotation_count: number;
	data: SampleAnnotationsPayload;
}

export interface SampleClassificationPayload {
	version: 'sorthive-classification-v1';
	updated_at: string | null;
	updated_by_display_name: string | null;
	part_id: string | null;
	item_name: string | null;
	color_id: string | null;
	color_name: string | null;
}

export interface SaveSampleClassificationResponse {
	ok: boolean;
	cleared: boolean;
	data: SampleClassificationPayload | null;
}

export interface SampleReview {
	id: string;
	sample_id: string;
	reviewer_id: string;
	reviewer_display_name: string;
	decision: 'accept' | 'reject';
	notes: string | null;
	created_at: string;
	updated_at: string;
}

export interface PaginatedSamples {
	items: Sample[];
	total: number;
	page: number;
	page_size: number;
	pages: number;
}

export interface SampleFilterOptions {
	source_roles: string[];
	capture_reasons: string[];
}

export interface StatsOverview {
	total_samples: number;
	unreviewed_samples: number;
	in_review_samples: number;
	accepted_samples: number;
	rejected_samples: number;
	conflict_samples: number;
	total_machines: number;
}

export interface AuthOptions {
	github_enabled: boolean;
}

function getCsrfToken(): string | null {
	const match = document.cookie.match(/(?:^|;\s*)csrf_token=([^;]*)/);
	return match ? decodeURIComponent(match[1]) : null;
}

let refreshPromise: Promise<boolean> | null = null;
let unauthorizedHandler: (() => void) | null = null;

export function setUnauthorizedHandler(handler: (() => void) | null) {
	unauthorizedHandler = handler;
}

function buildHeaders(method: string, body?: unknown): Record<string, string> {
	const headers: Record<string, string> = {};

	if (body && !(body instanceof FormData)) {
		headers['Content-Type'] = 'application/json';
	}

	if (method !== 'GET' && method !== 'HEAD') {
		const csrf = getCsrfToken();
		if (csrf) {
			headers['X-CSRF-Token'] = csrf;
		}
	}

	return headers;
}

async function doFetch(method: string, path: string, body?: unknown): Promise<Response> {
	return fetch(path, {
		method,
		headers: buildHeaders(method, body),
		credentials: 'include',
		body: body ? (body instanceof FormData ? body : JSON.stringify(body)) : undefined
	});
}

async function refreshSession(): Promise<boolean> {
	if (!getCsrfToken()) {
		return false;
	}

	if (!refreshPromise) {
		refreshPromise = (async () => {
			try {
				const res = await doFetch('POST', '/api/auth/refresh');
				return res.ok;
			} catch {
				return false;
			}
		})().finally(() => {
			refreshPromise = null;
		});
	}

	return refreshPromise;
}

async function request<T>(
	method: string,
	path: string,
	body?: unknown,
	options: { skipRefresh?: boolean } = {}
): Promise<T> {
	let res = await doFetch(method, path, body);

	if (
		res.status === 401 &&
		!options.skipRefresh &&
		path !== '/api/auth/login' &&
		path !== '/api/auth/register' &&
		path !== '/api/auth/refresh'
	) {
		const refreshed = await refreshSession();
		if (refreshed) {
			res = await doFetch(method, path, body);
		} else {
			unauthorizedHandler?.();
		}
	}

	if (!res.ok) {
		let errorData: ApiError;
		try {
			errorData = await res.json();
		} catch {
			errorData = { ok: false, error: `HTTP ${res.status}`, code: 'HTTP_ERROR' };
		}
		throw errorData;
	}

	if (res.status === 204) {
		return undefined as T;
	}

	return res.json();
}

export const api = {
	// Auth
	register(email: string, password: string, display_name: string) {
		return request<User>('POST', '/api/auth/register', { email, password, display_name }, { skipRefresh: true });
	},
	login(email: string, password: string) {
		return request<User>('POST', '/api/auth/login', { email, password }, { skipRefresh: true });
	},
	logout() {
		return request<void>('POST', '/api/auth/logout');
	},
	me() {
		return request<User>('GET', '/api/auth/me');
	},
	authOptions() {
		return request<AuthOptions>('GET', '/api/auth/options');
	},
	githubLoginUrl(next?: string) {
		if (!next) return '/api/auth/github';
		return `/api/auth/github?${new URLSearchParams({ next }).toString()}`;
	},
	deleteAccount() {
		return request<void>('DELETE', '/api/auth/me');
	},

	// Machines
	getMachines() {
		return request<Machine[]>('GET', '/api/machines');
	},
	createMachine(name: string, description?: string) {
		return request<MachineWithToken>('POST', '/api/machines', { name, description });
	},
	updateMachine(id: string, data: { name?: string; description?: string }) {
		return request<Machine>('PATCH', `/api/machines/${id}`, data);
	},
	deleteMachine(id: string) {
		return request<void>('DELETE', `/api/machines/${id}`);
	},
	rotateToken(id: string) {
		return request<MachineWithToken>('POST', `/api/machines/${id}/rotate-token`);
	},
	purgeMachineData(id: string) {
		return request<{ ok: boolean; deleted_sessions: number; deleted_samples: number }>('POST', `/api/machines/${id}/purge`);
	},

	// Samples
	getSamples(params: {
		page?: number;
		page_size?: number;
		machine_id?: string;
		upload_session_id?: string;
		source_role?: string;
		capture_reason?: string;
		review_status?: string;
	} = {}) {
		const searchParams = new URLSearchParams();
		for (const [key, val] of Object.entries(params)) {
			if (val !== undefined && val !== null && val !== '') {
				searchParams.set(key, String(val));
			}
		}
		const qs = searchParams.toString();
		return request<PaginatedSamples>('GET', `/api/samples${qs ? '?' + qs : ''}`);
	},
	getSampleFilterOptions() {
		return request<SampleFilterOptions>('GET', '/api/samples/filter-options');
	},
	getSample(id: string) {
		return request<SampleDetail>('GET', `/api/samples/${id}`);
	},
	saveSampleAnnotations(id: string, data: { annotations: SavedSampleAnnotation[]; version?: 'sorthive-annotorious-v1' }) {
		return request<SaveSampleAnnotationsResponse>('PUT', `/api/samples/${id}/annotations`, {
			version: data.version ?? 'sorthive-annotorious-v1',
			annotations: data.annotations
		});
	},
	saveSampleClassification(
		id: string,
		data: {
			part_id?: string | null;
			item_name?: string | null;
			color_id?: string | null;
			color_name?: string | null;
		}
	) {
		return request<SaveSampleClassificationResponse>('PUT', `/api/samples/${id}/classification`, data);
	},
	deleteSample(id: string) {
		return request<void>('DELETE', `/api/samples/${id}`);
	},
	sampleImageUrl(id: string) {
		return `/api/samples/${id}/assets/image`;
	},
	sampleFullFrameUrl(id: string) {
		return `/api/samples/${id}/assets/full-frame`;
	},
	sampleOverlayUrl(id: string) {
		return `/api/samples/${id}/assets/overlay`;
	},

	// Review
	getNextReview() {
		return request<Sample | null>('GET', '/api/review/queue/next');
	},
	submitReview(sampleId: string, decision: 'accept' | 'reject', notes?: string) {
		return request<SampleReview>('POST', `/api/review/samples/${sampleId}`, { decision, notes });
	},
	getReviewHistory(sampleId: string) {
		return request<{ reviews: SampleReview[]; sample_id: string; review_status: string }>('GET', `/api/review/samples/${sampleId}/history`);
	},

	updateProfile(data: { display_name?: string; current_password?: string; new_password?: string }) {
		return request<User>('PATCH', '/api/auth/me', data);
	},

	// Admin
	getUsers() {
		return request<User[]>('GET', '/api/admin/users');
	},
	updateUser(id: string, data: { role?: string; is_active?: boolean }) {
		return request<User>('PATCH', `/api/admin/users/${id}`, data);
	},
	deleteUser(id: string) {
		return request<void>('DELETE', `/api/admin/users/${id}`);
	},

	// Stats
	getOverview() {
		return request<StatsOverview>('GET', '/api/stats/overview');
	}
};
