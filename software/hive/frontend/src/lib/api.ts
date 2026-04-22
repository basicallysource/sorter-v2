import { env } from '$env/dynamic/public';

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
	openrouter_configured: boolean;
	preferred_ai_model: string | null;
	role: 'member' | 'reviewer' | 'admin';
	is_active: boolean;
	created_at: string;
}

export interface Machine {
	id: string;
	name: string;
	description: string | null;
	token_prefix: string;
	last_seen_ip: string | null;
	local_ui_port: string | null;
	last_seen_at: string | null;
	is_active: boolean;
	created_at: string;
}

export interface MachineWithToken extends Machine {
	raw_token: string;
}

export interface MachineStats {
	total_samples: number;
	accepted_samples: number;
	first_capture: string | null;
	last_capture: string | null;
	total_sessions: number;
	parts_found: number;
	parts_needed: number;
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
	sample_payload: Record<string, unknown> | null;
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
	version: 'hive-annotorious-v1';
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
	version: 'hive-classification-v1';
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

export interface ProfileOwner {
	id: string;
	display_name: string | null;
	github_login: string | null;
	avatar_url: string | null;
}

export interface SortingProfileCondition {
	id: string;
	field: string;
	op: string;
	value: unknown;
}

export interface CustomSetPart {
	part_num: string;
	color_id: number;
	quantity: number;
	part_name?: string | null;
	color_name?: string | null;
	img_url?: string | null;
	part_source?: 'rebrickable' | 'bricklink';
}

export interface SortingProfileRule {
	id: string;
	rule_type?: 'filter' | 'set';
	name: string;
	match_mode: 'all' | 'any' | string;
	conditions: SortingProfileCondition[];
	children: SortingProfileRule[];
	disabled: boolean;
	// Set-specific fields
	set_source?: 'rebrickable' | 'custom';
	set_num?: string;
	include_spares?: boolean;
	set_meta?: {
		name: string;
		year: number | null;
		num_parts: number | null;
		img_url: string | null;
	};
	custom_parts?: CustomSetPart[];
}

export interface SortingProfileFallbackMode {
	rebrickable_categories: boolean;
	bricklink_categories: boolean;
	by_color: boolean;
}

export interface RuleSummary {
	name: string;
	rule_type: string;
	set_source: string | null;
	set_num: string | null;
	set_meta: { name?: string; year?: number | null; num_parts?: number | null; img_url?: string } | null;
	disabled: boolean;
	condition_count: number;
	child_count: number;
}

export interface SortingProfileVersionSummary {
	id: string;
	version_number: number;
	label: string | null;
	change_note: string | null;
	is_published: boolean;
	compiled_hash: string;
	compiled_part_count: number;
	coverage_ratio: number | null;
	created_at: string;
	rules_summary: RuleSummary[];
}

export interface SortingProfileForkSource {
	profile_id: string;
	profile_name: string;
	version_number: number | null;
}

export interface SortingProfileSummary {
	id: string;
	name: string;
	description: string | null;
	visibility: 'private' | 'unlisted' | 'public';
	profile_type: string;
	tags: string[];
	latest_version_number: number;
	latest_published_version_number: number | null;
	library_count: number;
	fork_count: number;
	created_at: string;
	updated_at: string;
	owner: ProfileOwner;
	source: SortingProfileForkSource | null;
	saved_in_library: boolean;
	is_owner: boolean;
	latest_version: SortingProfileVersionSummary | null;
	latest_published_version: SortingProfileVersionSummary | null;
}

export interface SortingProfileVersion extends SortingProfileVersionSummary {
	name: string;
	description: string | null;
	default_category_id: string;
	rules: SortingProfileRule[];
	fallback_mode: SortingProfileFallbackMode;
	compiled_stats: Record<string, unknown> | null;
	categories: Record<string, { name: string }>;
}

export interface SortingProfileDetail extends SortingProfileSummary {
	versions: SortingProfileVersionSummary[];
	current_version: SortingProfileVersion | null;
}

export interface SortingProfileSetProgressSet {
	set_num: string;
	name: string;
	total_needed: number;
	total_found: number;
	pct: number;
	updated_at: string | null;
}

export interface SortingProfileSetProgressMachine {
	machine_id: string;
	machine_name: string;
	assignment_id: string;
	desired_version_id: string | null;
	active_version_id: string | null;
	desired_version_number: number | null;
	active_version_number: number | null;
	last_synced_at: string | null;
	last_activated_at: string | null;
	overall_needed: number;
	overall_found: number;
	overall_pct: number;
	updated_at: string | null;
	sets: SortingProfileSetProgressSet[];
}

export interface SortingProfileSetProgressResponse {
	profile_id: string;
	machines: SortingProfileSetProgressMachine[];
}

export interface AiToolTraceItem {
	tool: string;
	input: Record<string, unknown>;
	output_summary: string;
	output?: Record<string, unknown> | null;
	duration_ms?: number | null;
}

export interface AiPerformance {
	request_id?: string;
	round_count?: number;
	tool_call_count?: number;
	llm_ms?: number;
	tool_ms?: number;
	total_ms?: number;
	cached_tokens?: number;
	cache_write_tokens?: number;
}

export interface SortingProfileAiMessage {
	id: string;
	role: 'user' | 'assistant';
	content: string;
	model: string | null;
	version_id: string | null;
	applied_version_id: string | null;
	selected_rule_id: string | null;
	usage: (Record<string, unknown> & { performance?: AiPerformance }) | null;
	proposal: Record<string, unknown> | null;
	tool_trace: AiToolTraceItem[];
	applied_at: string | null;
	created_at: string;
}

export interface ProfileCatalogStatus {
	running: boolean;
	last_message: string;
	pages_fetched: number;
	sync_type: string | null;
	progress_current: number | null;
	progress_total: number | null;
	cached_parts: number;
	cached_categories: number;
	cached_bricklink_categories: number;
	cached_colors: number;
	api_total: number | null;
	error: string | null;
	auto_sync_enabled: boolean;
	auto_sync_running: boolean;
	auto_sync_loop_running: boolean;
	auto_sync_plan: string[];
	auto_sync_last_checked_at: string | null;
	auto_sync_last_started_at: string | null;
	last_synced_at: Record<string, string | null>;
}

export interface ProfileCatalogSearchResult {
	part_num: string;
	name: string;
	part_cat_id: number | null;
	year_from: number | null;
	year_to: number | null;
	part_img_url: string | null;
	part_url: string | null;
	external_ids: Record<string, unknown>;
	_category_name: string;
	_bl_name: string | null;
	_bl_category_name: string | null;
}

export interface ProfileCatalogColor {
	id: number;
	name: string;
	rgb: string | null;
	is_trans: boolean;
}

export interface BrickLinkCsvImportResult {
	parts: CustomSetPart[];
	imported_rows: number;
	imported_unique_parts: number;
	warning_count: number;
	warnings: string[];
	suggested_name: string | null;
}

export interface MachineProfileAssignment {
	machine_id: string;
	profile: SortingProfileSummary | null;
	desired_version: SortingProfileVersionSummary | null;
	active_version: SortingProfileVersionSummary | null;
	artifact_hash: string | null;
	last_error: string | null;
	last_synced_at: string | null;
	last_activated_at: string | null;
}

function getApiBaseUrl(): string {
	const explicit = (env.PUBLIC_API_BASE_URL ?? '').trim().replace(/\/+$/, '');
	if (explicit) return explicit;
	if (typeof window !== 'undefined') {
		const host = window.location.hostname;
		if ((host === 'localhost' || host === '127.0.0.1') && window.location.port !== '8002') {
			return `${window.location.protocol}//${host}:8002`;
		}
	}
	return '';
}

function resolveApiPath(path: string): string {
	if (/^https?:\/\//.test(path)) return path;
	const base = getApiBaseUrl();
	return `${base}${path}`;
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
	return fetch(resolveApiPath(path), {
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
		if (!next) return resolveApiPath('/api/auth/github');
		return resolveApiPath(`/api/auth/github?${new URLSearchParams({ next }).toString()}`);
	},
	deleteAccount() {
		return request<void>('DELETE', '/api/auth/me');
	},

	// Machines
	getMachines() {
		return request<Machine[]>('GET', '/api/machines');
	},
	getMachineStats() {
		return request<Record<string, MachineStats>>('GET', '/api/machines/stats');
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
	saveSampleAnnotations(id: string, data: { annotations: SavedSampleAnnotation[]; version?: 'hive-annotorious-v1' }) {
		return request<SaveSampleAnnotationsResponse>('PUT', `/api/samples/${id}/annotations`, {
			version: data.version ?? 'hive-annotorious-v1',
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
		return resolveApiPath(`/api/samples/${id}/assets/image`);
	},
	sampleFullFrameUrl(id: string) {
		return resolveApiPath(`/api/samples/${id}/assets/full-frame`);
	},
	sampleOverlayUrl(id: string) {
		return resolveApiPath(`/api/samples/${id}/assets/overlay`);
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

	updateProfile(data: {
		display_name?: string;
		current_password?: string;
		new_password?: string;
		openrouter_api_key?: string | null;
		clear_openrouter_api_key?: boolean;
		preferred_ai_model?: string | null;
	}) {
		return request<User>('PATCH', '/api/auth/me', data);
	},

	// Profile Catalog
	getProfileCatalogStatus() {
		return request<ProfileCatalogStatus>('GET', '/api/profile-catalog/status');
	},
	startProfileCatalogSync(syncType: 'categories' | 'colors' | 'parts' | 'brickstore' | 'prices') {
		return request<{ started: boolean }>('POST', `/api/profile-catalog/sync/${syncType}`);
	},
	stopProfileCatalogSync() {
		return request<{ stopped: boolean }>('POST', '/api/profile-catalog/stop');
	},
	getProfileCatalogColors() {
		return request<{ results: ProfileCatalogColor[] }>('GET', '/api/profile-catalog/colors');
	},
	importProfileCatalogBricklinkCsv(csv_content: string, filename?: string) {
		return request<BrickLinkCsvImportResult>('POST', '/api/profile-catalog/import-bricklink-csv', {
			csv_content,
			filename
		});
	},
	searchProfileCatalogParts(params: { q?: string; cat_id?: number; limit?: number; offset?: number } = {}) {
		const searchParams = new URLSearchParams();
		for (const [key, val] of Object.entries(params)) {
			if (val !== undefined && val !== null && val !== '') {
				searchParams.set(key, String(val));
			}
		}
		const qs = searchParams.toString();
		return request<{ results: ProfileCatalogSearchResult[]; total: number; offset: number; limit: number }>(
			'GET',
			`/api/profile-catalog/search-parts${qs ? '?' + qs : ''}`
		);
	},

	searchProfileCatalogSets(query: string, params: { min_year?: number; max_year?: number } = {}) {
		const searchParams = new URLSearchParams({ q: query });
		if (params.min_year !== undefined) searchParams.set('min_year', String(params.min_year));
		if (params.max_year !== undefined) searchParams.set('max_year', String(params.max_year));
		return request<{ results: Array<{ set_num: string; name: string; year: number; num_parts: number; img_url: string | null }> }>(
			'GET',
			`/api/profile-catalog/search-sets?${searchParams.toString()}`
		);
	},

	// Sorting Profiles
	getProfiles(params: { scope?: 'discover' | 'mine' | 'library'; q?: string } = {}) {
		const searchParams = new URLSearchParams();
		if (params.scope) searchParams.set('scope', params.scope);
		if (params.q) searchParams.set('q', params.q);
		const qs = searchParams.toString();
		return request<SortingProfileSummary[]>('GET', `/api/profiles${qs ? '?' + qs : ''}`);
	},
	createSortingProfile(data: { name: string; description?: string | null; visibility?: 'private' | 'unlisted' | 'public'; tags?: string[] }) {
		return request<SortingProfileDetail>('POST', '/api/profiles', data);
	},
	getSortingProfile(id: string, versionId?: string) {
		const qs = versionId ? `?${new URLSearchParams({ version_id: versionId }).toString()}` : '';
		return request<SortingProfileDetail>('GET', `/api/profiles/${id}${qs}`);
	},
	getSortingProfileSetProgress(id: string) {
		return request<SortingProfileSetProgressResponse>('GET', `/api/profiles/${id}/set-progress`);
	},
	updateSortingProfile(id: string, data: { name?: string; description?: string | null; visibility?: 'private' | 'unlisted' | 'public'; tags?: string[] }) {
		return request<SortingProfileDetail>('PATCH', `/api/profiles/${id}`, data);
	},
	deleteSortingProfile(id: string) {
		return request<void>('DELETE', `/api/profiles/${id}`);
	},
	suggestChangeNote(id: string, data: { old_rules: SortingProfileRule[]; new_rules: SortingProfileRule[] }) {
		return request<{ change_note: string }>('POST', `/api/profiles/${id}/suggest-change-note`, data);
	},
	saveSortingProfileVersion(id: string, data: {
		name: string;
		description?: string | null;
		default_category_id?: string;
		rules: SortingProfileRule[];
		fallback_mode: SortingProfileFallbackMode;
		change_note?: string | null;
		label?: string | null;
		publish?: boolean;
	}) {
		return request<SortingProfileVersion>('POST', `/api/profiles/${id}/versions`, data);
	},
	publishSortingProfileVersion(profileId: string, versionId: string) {
		return request<SortingProfileVersion>('POST', `/api/profiles/${profileId}/versions/${versionId}/publish`);
	},
	getSortingProfileArtifact(profileId: string, versionId: string) {
		return request<{ artifact: Record<string, unknown> }>('GET', `/api/profiles/${profileId}/versions/${versionId}/artifact`);
	},
	saveSortingProfileToLibrary(id: string) {
		return request<{ ok: boolean }>('POST', `/api/profiles/${id}/library`);
	},
	removeSortingProfileFromLibrary(id: string) {
		return request<{ ok: boolean }>('DELETE', `/api/profiles/${id}/library`);
	},
	forkSortingProfile(id: string, data: { name?: string | null; description?: string | null; add_to_library?: boolean }, versionId?: string) {
		const qs = versionId ? `?${new URLSearchParams({ version_id: versionId }).toString()}` : '';
		return request<SortingProfileDetail>('POST', `/api/profiles/${id}/fork${qs}`, data);
	},
	previewSortingProfile(data: {
		name?: string;
		description?: string | null;
		default_category_id?: string;
		rules: SortingProfileRule[];
		fallback_mode: SortingProfileFallbackMode;
	}) {
		return request<Record<string, unknown>>('POST', '/api/profiles/preview', data);
	},
	previewSortingRule(data: {
		name?: string;
		description?: string | null;
		default_category_id?: string;
		rules: SortingProfileRule[];
		fallback_mode: SortingProfileFallbackMode;
	}, params: { rule_id?: string; q?: string; offset?: number; limit?: number; standalone?: boolean } = {}) {
		const searchParams = new URLSearchParams();
		for (const [key, val] of Object.entries(params)) {
			if (val !== undefined && val !== null && val !== '') {
				searchParams.set(key, String(val));
			}
		}
		const qs = searchParams.toString();
		return request<Record<string, unknown>>('POST', `/api/profiles/preview-rule${qs ? '?' + qs : ''}`, data);
	},
	getSortingProfileAiMessages(profileId: string) {
		return request<SortingProfileAiMessage[]>('GET', `/api/profiles/${profileId}/ai/messages`);
	},
	createSortingProfileAiMessage(profileId: string, data: { message: string; version_id?: string | null; selected_rule_id?: string | null }) {
		return request<SortingProfileAiMessage>('POST', `/api/profiles/${profileId}/ai/messages`, data);
	},
	async streamSortingProfileAiMessage(
		profileId: string,
		data: { message: string; version_id?: string | null; selected_rule_id?: string | null },
		onEvent: (event: { type: string; [key: string]: unknown }) => void
	): Promise<SortingProfileAiMessage> {
		const res = await fetch(resolveApiPath(`/api/profiles/${profileId}/ai/messages/stream`), {
			method: 'POST',
			headers: buildHeaders('POST', data),
			credentials: 'include',
			body: JSON.stringify(data)
		});
		if (!res.ok) {
			let errorData;
			try { errorData = await res.json(); } catch { errorData = { error: `HTTP ${res.status}` }; }
			throw errorData;
		}
		const reader = res.body!.getReader();
		const decoder = new TextDecoder();
		let buffer = '';
		let finalMessage: SortingProfileAiMessage | null = null;

		while (true) {
			const { done, value } = await reader.read();
			if (done) break;
			buffer += decoder.decode(value, { stream: true });

			const lines = buffer.split('\n');
			buffer = lines.pop() ?? '';

			for (const line of lines) {
				if (!line.startsWith('data: ')) continue;
				const jsonStr = line.slice(6).trim();
				if (!jsonStr) continue;
				try {
					const event = JSON.parse(jsonStr);
					if (event.type === 'complete' && event.message) {
						finalMessage = event.message as SortingProfileAiMessage;
					} else if (event.type === 'error') {
						throw { error: event.error || 'AI request failed', code: 'AI_ERROR' };
					} else {
						onEvent(event);
					}
				} catch (e) {
					if (e && typeof e === 'object' && 'error' in e) throw e;
				}
			}
		}

		if (!finalMessage) throw { error: 'AI did not return a response', code: 'AI_NO_RESPONSE' };
		return finalMessage;
	},
	applySortingProfileAiMessage(profileId: string, messageId: string, data: { label?: string | null; change_note?: string | null; publish?: boolean }) {
		return request<SortingProfileVersion>('POST', `/api/profiles/${profileId}/ai/messages/${messageId}/apply`, data);
	},

	// Machine Profile Assignments
	getMachineProfileAssignment(machineId: string) {
		return request<MachineProfileAssignment | null>('GET', `/api/machines/${machineId}/profile-assignment`);
	},
	assignMachineProfile(machineId: string, profileId: string, versionId: string) {
		return request<MachineProfileAssignment>('PUT', `/api/machines/${machineId}/profile-assignment`, {
			profile_id: profileId,
			version_id: versionId
		});
	},
	clearMachineProfileAssignment(machineId: string) {
		return request<void>('DELETE', `/api/machines/${machineId}/profile-assignment`);
	},

	getMachineSetProgress(machineId: string) {
		return request<{ progress: Array<{ set_num: string; set_name?: string; part_num: string; color_id: number; quantity_needed: number; quantity_found: number; updated_at: string | null }>; assignment_id: string | null }>('GET', `/api/machines/${machineId}/set-progress`);
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
	},

	// API keys (personal access tokens)
	listApiKeys() {
		return request<ApiKeySummary[]>('GET', '/api/auth/api-keys');
	},
	createApiKey(name: string, scopes?: string[]) {
		return request<ApiKeyCreateResponse>('POST', '/api/auth/api-keys', { name, scopes });
	},
	revokeApiKey(id: string) {
		return request<{ ok: boolean }>('DELETE', `/api/auth/api-keys/${id}`);
	},

	// Detection models
	getModels(params: {
		page?: number;
		page_size?: number;
		scope?: string;
		runtime?: string;
		family?: string;
		q?: string;
	} = {}) {
		const searchParams = new URLSearchParams();
		for (const [key, val] of Object.entries(params)) {
			if (val !== undefined && val !== null && val !== '') {
				searchParams.set(key, String(val));
			}
		}
		const qs = searchParams.toString();
		return request<PaginatedDetectionModels>('GET', `/api/models${qs ? '?' + qs : ''}`);
	},
	getModel(id: string) {
		return request<DetectionModelDetail>('GET', `/api/models/${id}`);
	},
	modelVariantDownloadUrl(modelId: string, variantId: string) {
		return resolveApiPath(`/api/models/${modelId}/variants/${variantId}/download`);
	},
	createModel(payload: {
		slug: string;
		name: string;
		description?: string | null;
		model_family: string;
		scopes?: string[];
		training_metadata?: Record<string, unknown>;
		is_public?: boolean;
	}) {
		return request<{ id: string; slug: string; version: number }>('POST', '/api/models', payload);
	},
	deleteModel(id: string) {
		return request<void>('DELETE', `/api/models/${id}`);
	}
};

export interface DetectionModelVariant {
	id: string;
	runtime: string;
	file_name: string;
	file_size: number;
	sha256: string;
	format_meta: Record<string, unknown> | null;
	uploaded_at: string;
}

export interface DetectionModelSummary {
	id: string;
	owner_id: string | null;
	slug: string;
	version: number;
	name: string;
	description: string | null;
	model_family: string;
	scopes: string[] | null;
	is_public: boolean;
	published_at: string;
	updated_at: string;
	variant_runtimes: string[];
}

export interface DetectionModelDetail extends DetectionModelSummary {
	training_metadata: Record<string, unknown> | null;
	variants: DetectionModelVariant[];
}

export interface ApiKeySummary {
	id: string;
	name: string;
	token_prefix: string;
	scopes: string[] | null;
	created_at: string;
	last_used_at: string | null;
	revoked_at: string | null;
}

export interface ApiKeyCreateResponse {
	summary: ApiKeySummary;
	raw_token: string;
}

export interface PaginatedDetectionModels {
	items: DetectionModelSummary[];
	total: number;
	page: number;
	page_size: number;
	pages: number;
}
