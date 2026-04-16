export type SortingProfileRuleSummary = {
	name: string;
	rule_type: 'set' | 'filter' | string;
	set_source?: 'custom' | 'rebrickable' | null;
	set_num?: string | null;
	set_meta?: {
		name?: string | null;
		year?: number | null;
		img_url?: string | null;
		num_parts?: number | null;
	} | null;
	disabled: boolean;
	condition_count: number;
	child_count: number;
};

export type SortingProfileVersionSummary = {
	id: string;
	version_number: number;
	label: string | null;
	change_note: string | null;
	is_published: boolean;
	compiled_part_count: number;
	coverage_ratio: number | null;
	created_at: string;
	rules_summary?: SortingProfileRuleSummary[];
};

export type SortingProfileCondition = {
	id: string;
	field: string;
	op: string;
	value: unknown;
};

export type SortingProfileCustomPart = {
	part_num: string;
	color_id?: number | null;
	quantity?: number | null;
	part_name?: string | null;
	color_name?: string | null;
};

export type SortingProfileRule = {
	id: string;
	rule_type: string;
	name: string;
	match_mode: string;
	conditions: SortingProfileCondition[];
	children: SortingProfileRule[];
	disabled: boolean;
	set_source?: 'custom' | 'rebrickable' | string | null;
	set_num?: string | null;
	include_spares?: boolean;
	set_meta?: {
		name?: string | null;
		year?: number | null;
		img_url?: string | null;
		num_parts?: number | null;
	} | null;
	custom_parts?: SortingProfileCustomPart[];
};

export type SortingProfileFallbackMode = {
	rebrickable_categories?: boolean;
	bricklink_categories?: boolean;
	by_color?: boolean;
};

export type SortingProfileVersionDetail = SortingProfileVersionSummary & {
	name: string;
	description: string | null;
	default_category_id: string;
	rules: SortingProfileRule[];
	fallback_mode: SortingProfileFallbackMode;
	compiled_stats?: {
		matched?: number;
		total_parts?: number;
		unmatched?: number;
		per_category?: Record<string, number>;
	} | null;
	categories?: Record<string, Record<string, unknown>>;
};

export type SortingProfileSummary = {
	id: string;
	name: string;
	description: string | null;
	is_owner: boolean;
	visibility: 'private' | 'unlisted' | 'public';
	profile_type?: 'rule' | 'set' | string;
	tags: string[];
	latest_version_number?: number | null;
	latest_published_version_number?: number | null;
	fork_count?: number;
	source?: unknown;
	owner?: {
		display_name?: string | null;
		github_login?: string | null;
	} | null;
	latest_version: SortingProfileVersionSummary | null;
	latest_published_version: SortingProfileVersionSummary | null;
};

export type SortingProfileDetail = SortingProfileSummary & {
	versions: SortingProfileVersionSummary[];
	current_version: SortingProfileVersionDetail | null;
};

export type SortingProfileSyncState = {
	target_id?: string | null;
	target_name?: string | null;
	target_url?: string | null;
	profile_id?: string | null;
	profile_name?: string | null;
	version_id?: string | null;
	version_number?: number | null;
	version_label?: string | null;
	artifact_hash?: string | null;
	applied_at?: string | null;
	activated_at?: string | null;
	last_error?: string | null;
	progress_last_synced_at?: string | null;
	progress_last_error?: string | null;
};

export type LocalProfileStatus = {
	path?: string | null;
	name?: string | null;
	description?: string | null;
	artifact_hash?: string | null;
	default_category_id?: string | null;
	category_count?: number | null;
	rule_count?: number | null;
	updated_at?: string | null;
	error?: string | null;
};

export type MachineProfileAssignment = {
	profile: SortingProfileSummary | null;
	desired_version: SortingProfileVersionSummary | null;
	active_version: SortingProfileVersionSummary | null;
	last_error: string | null;
	last_synced_at: string | null;
	last_activated_at: string | null;
};

export type HiveTargetLibrary = {
	id: string;
	name: string;
	url: string;
	enabled: boolean;
	machine_id: string | null;
	profiles: SortingProfileSummary[];
	assignment: MachineProfileAssignment | null;
	error: string | null;
};

export type SortingProfileLibraryResponse = {
	targets: HiveTargetLibrary[];
	sync_state: SortingProfileSyncState | null;
	local_profile: LocalProfileStatus;
};

export type PendingProfileApply = {
	key: string;
	target_id: string;
	target_name: string;
	profile_id: string;
	profile_name: string;
	version_id: string;
	version_number: number | null;
	version_label: string | null;
};

export type SortingProfileCardEntry = {
	target: HiveTargetLibrary;
	profile: SortingProfileSummary;
};
