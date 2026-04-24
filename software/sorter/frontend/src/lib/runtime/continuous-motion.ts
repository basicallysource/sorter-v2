export type ContinuousMotionChannelKey = 'c1' | 'c2' | 'c3' | 'c4';
export type ContinuousMotionMode = 'rpm' | 'factor';

export type ContinuousMotionChannelStatus = {
	interval_s?: number;
	target_rpm?: number | null;
	nominal_degrees_per_step?: number | null;
	step_count?: number;
	skipped_count?: number;
	error_count?: number;
	last_step_at?: number | null;
	last_error?: string | null;
};

export type ContinuousMotionStatus = {
	active?: boolean;
	phase?: string;
	started_at?: number | null;
	finished_at?: number | null;
	success?: boolean | null;
	reason?: string | null;
	cancel_requested?: boolean;
	config?: {
		base_interval_s?: number;
		ratio?: number;
		channel_rpm?: Partial<Record<ContinuousMotionChannelKey, number>>;
		direct_max_speed_usteps_per_s?: number | null;
		direct_acceleration_usteps_per_s2?: number | null;
		duration_s?: number | null;
		poll_s?: number;
	};
	channels?: Partial<Record<ContinuousMotionChannelKey, ContinuousMotionChannelStatus>>;
};

export type RtStatusWithContinuousMotion = {
	maintenance?: {
		sample_transport?: ContinuousMotionStatus;
	};
};

export type StartContinuousMotionPayload = {
	base_interval_s?: number;
	ratio?: number;
	channel_rpm?: Partial<Record<ContinuousMotionChannelKey, number>>;
	direct_max_speed_usteps_per_s?: number | null;
	direct_acceleration_usteps_per_s2?: number | null;
	duration_s?: number | null;
	poll_s?: number;
};

export async function fetchContinuousMotionStatus(
	baseUrl: string
): Promise<ContinuousMotionStatus | null> {
	const response = await fetch(`${baseUrl}/api/rt/status`, { cache: 'no-store' });
	if (!response.ok) return null;
	const payload = (await response.json()) as RtStatusWithContinuousMotion;
	return payload.maintenance?.sample_transport ?? null;
}

export async function startContinuousMotion(
	baseUrl: string,
	payload: StartContinuousMotionPayload
): Promise<ContinuousMotionStatus> {
	const response = await fetch(`${baseUrl}/api/rt/sample-transport`, {
		method: 'POST',
		headers: { 'content-type': 'application/json' },
		body: JSON.stringify(payload)
	});
	const data = (await response.json().catch(() => ({}))) as {
		detail?: string;
		status?: ContinuousMotionStatus;
	};
	if (!response.ok) {
		throw new Error(data.detail ?? 'Could not start continuous motion.');
	}
	return data.status ?? { active: true, phase: 'running' };
}

export async function updateContinuousMotion(
	baseUrl: string,
	payload: StartContinuousMotionPayload
): Promise<ContinuousMotionStatus> {
	const response = await fetch(`${baseUrl}/api/rt/sample-transport/config`, {
		method: 'POST',
		headers: { 'content-type': 'application/json' },
		body: JSON.stringify(payload)
	});
	const data = (await response.json().catch(() => ({}))) as {
		detail?: string;
		status?: ContinuousMotionStatus;
	};
	if (!response.ok) {
		throw new Error(data.detail ?? 'Could not update continuous motion.');
	}
	return data.status ?? { active: true, phase: 'running' };
}

export async function cancelContinuousMotion(baseUrl: string): Promise<ContinuousMotionStatus> {
	const response = await fetch(`${baseUrl}/api/rt/sample-transport/cancel`, {
		method: 'POST'
	});
	const data = (await response.json().catch(() => ({}))) as {
		detail?: string;
		status?: ContinuousMotionStatus;
	};
	if (!response.ok) {
		throw new Error(data.detail ?? 'Could not stop continuous motion.');
	}
	return data.status ?? { active: false, phase: 'idle' };
}
