// What this sorter shares with each Hive: the calls to the machine's
// /api/sharing routes, and the small helpers the Data pages, the setup step and
// the Hive section share.

// One thing a Hive can receive. A required one is always shared and has no
// switch; the others are on or off, for every Hive and for each Hive.
export type SharingStream = {
	key: string;
	label: string;
	// One or two sentences: what it is for, shown behind an info icon.
	info: string;
	kind: 'telemetry' | 'records' | 'pictures';
	size: 'small' | 'large';
	required: boolean;
	default: boolean;
};

// A Hive the machine is connected to, and what it receives.
export type SharingTarget = {
	id: string;
	name: string;
	url: string;
	enabled: boolean;
	is_primary: boolean;
	// What this Hive actually gets.
	effective: Record<string, boolean>;
	// Only the streams set differently for this Hive than for every Hive.
	overrides: Record<string, boolean>;
};

export type SharingConsent = {
	current_version: number;
	// The version the person agreed to; null before they have.
	version: number | null;
	accepted_at: string | null;
	// Nothing is shared until the person agrees.
	needs_consent: boolean;
	// They agreed to an older version: what is shared has changed.
	needs_review: boolean;
};

export type Sharing = {
	streams: SharingStream[];
	defaults: Record<string, boolean>;
	// What every Hive gets unless it is set differently, per optional stream.
	every_hive: Record<string, boolean>;
	// The streams whose value for every Hive the person chose.
	every_hive_set: string[];
	targets: SharingTarget[];
	consent: SharingConsent;
};

// A kind of upload: what the stats are counted by, and the stream that
// decides whether it is sent.
export type StatsKind = {
	key: string;
	label: string;
	stream: string;
	size: 'small' | 'large';
};

// One kind's numbers for one Hive, an entry per hour of `hour_starts`; the last
// is the current, partial hour.
export type KindSeries = {
	sent: number[];
	sent_bytes: number[];
	// Never to be uploaded: skipped to keep up, or deleted before they were sent.
	dropped: number[];
	dropped_bytes: number[];
	// The backlog at the end of the hour; null where it was not known.
	waiting: (number | null)[];
};

export type StatsTarget = {
	id: string;
	name: string;
	reachable: boolean;
	series: Record<string, KindSeries>;
	// Seconds of the hour that uploads waited for the upload budget.
	budget_wait_s: number[];
	waiting_now: Record<string, number>;
	last_sent_at: Record<string, number | null>;
	upload_budget: { bytes_per_minute: number; files_per_minute: number } | null;
};

// What is stored on this machine for one kind, until the Hives that should have
// it do.
export type LocalKind = {
	key: string;
	label: string;
	count: number;
	bytes: number;
	cap_bytes: number | null;
	// Not yet on every Hive that should have it.
	waiting: number;
};

export type SharingStats = {
	now: number;
	hour_starts: number[];
	kinds: StatsKind[];
	targets: StatsTarget[];
	local: LocalKind[];
	disk: { free_bytes: number | null; min_free_bytes: number };
};

// The reason a request failed: the backend's `detail` when it gave one.
function reason(body: unknown, status: number): string {
	const detail = (body as { detail?: unknown } | null)?.detail;
	if (typeof detail === 'string' && detail) return detail;
	if (Array.isArray(detail) && typeof detail[0]?.msg === 'string') return detail[0].msg;
	return `The machine answered ${status}.`;
}

async function call<T>(base: string, path: string, method = 'GET', body?: unknown): Promise<T> {
	const res = await fetch(`${base}${path}`, {
		method,
		headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
		body: body === undefined ? undefined : JSON.stringify(body)
	});
	const data = await res.json().catch(() => null);
	if (!res.ok) throw new Error(reason(data, res.status));
	return data as T;
}

export function getSharing(base: string): Promise<Sharing> {
	return call(base, '/api/sharing');
}

// Sets values for every Hive (`targetId` null) or for one Hive. A value for a
// Hive that equals the one for every Hive removes the Hive's own.
export function saveSharing(
	base: string,
	targetId: string | null,
	values: Record<string, boolean>
): Promise<Sharing> {
	return call(base, '/api/sharing', 'POST', { target_id: targetId, values });
}

// Every Hive's values back to the defaults, or one Hive's own values removed.
export function resetSharing(base: string, targetId: string | null): Promise<Sharing> {
	return call(base, '/api/sharing/reset', 'POST', { target_id: targetId });
}

// Records the person's agreement to the notice of `version` and sets the values
// for every Hive.
export function acceptSharing(
	base: string,
	version: number,
	values: Record<string, boolean>
): Promise<Sharing> {
	return call(base, '/api/sharing/consent', 'POST', { version, values });
}

export function getSharingStats(base: string, hours: 24 | 168): Promise<SharingStats> {
	return call(base, `/api/sharing/stats?hours=${hours}`);
}

// The streams that can be turned off.
export function optionalStreams(sharing: Sharing): SharingStream[] {
	return sharing.streams.filter((stream) => !stream.required);
}

// The stream's default, from the machine's list of defaults.
export function defaultOf(sharing: Sharing, stream: SharingStream): boolean {
	return sharing.defaults[stream.key] ?? stream.default;
}

// Whether a stream is on for every Hive (`targetId` null) or for one Hive.
export function sharedWith(
	sharing: Sharing,
	stream: SharingStream,
	targetId: string | null
): boolean {
	if (stream.required) return true;
	const everyHive = sharing.every_hive[stream.key] ?? defaultOf(sharing, stream);
	if (targetId === null) return everyHive;
	const target = sharing.targets.find((t) => t.id === targetId);
	return target?.effective[stream.key] ?? everyHive;
}

// The values of the optional streams for every Hive, as the machine takes them
// when an agreement is recorded.
export function everyHiveValues(sharing: Sharing): Record<string, boolean> {
	return Object.fromEntries(
		optionalStreams(sharing).map((stream) => [stream.key, sharedWith(sharing, stream, null)])
	);
}

// The state as it will be once a change has been saved: shown at once, then
// replaced by the machine's answer.
export function withValue(
	sharing: Sharing,
	targetId: string | null,
	key: string,
	on: boolean
): Sharing {
	if (targetId === null) {
		return {
			...sharing,
			every_hive: { ...sharing.every_hive, [key]: on },
			every_hive_set: sharing.every_hive_set.includes(key)
				? sharing.every_hive_set
				: [...sharing.every_hive_set, key],
			// A Hive with no value of its own follows every Hive.
			targets: sharing.targets.map((t) =>
				key in t.overrides ? t : { ...t, effective: { ...t.effective, [key]: on } }
			)
		};
	}
	return {
		...sharing,
		targets: sharing.targets.map((target) => {
			if (target.id !== targetId) return target;
			const overrides = { ...target.overrides };
			if (on === sharing.every_hive[key]) delete overrides[key];
			else overrides[key] = on;
			return { ...target, effective: { ...target.effective, [key]: on }, overrides };
		})
	};
}
