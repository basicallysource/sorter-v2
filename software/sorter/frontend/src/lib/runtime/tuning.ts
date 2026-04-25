export type RotorTuning = {
	steps_per_pulse?: number | null;
	microsteps_per_second?: number | null;
	delay_between_pulse_ms?: number | null;
	acceleration_microsteps_per_second_sq?: number | null;
};

export type RuntimeTuningChannel = {
	max_piece_count?: number | null;
	max_zones?: number | null;
	max_raw_detections?: number | null;
	intake_body_half_width_deg?: number | null;
	intake_guard_deg?: number | null;
	pulse_cooldown_s?: number | null;
	exit_handoff_min_interval_s?: number | null;
	handoff_retry_escalate_after?: number | null;
	handoff_retry_max_pulses?: number | null;
	jam_timeout_s?: number | null;
	jam_min_pulses?: number | null;
	jam_cooldown_s?: number | null;
	max_recovery_cycles?: number | null;
	advance_interval_s?: number | null;
	track_stale_s?: number | null;
	exit_near_arc_deg?: number | null;
	approach_near_arc_deg?: number | null;
	intake_near_arc_deg?: number | null;
	wiggle_stall_ms?: number | null;
	wiggle_cooldown_ms?: number | null;
	holdover_ms?: number | null;
	transport_target_rpm?: number | null;
	transport_step_deg?: number | null;
	transport_max_step_deg?: number | null;
	transport_cooldown_s?: number | null;
	transport_speed_scale?: number | null;
	classify_pretrigger_exit_lead_deg?: number | null;
	exit_approach_angle_deg?: number | null;
	exit_approach_step_deg?: number | null;
	stepper_degrees_per_tray_degree?: number | null;
	transport_acceleration_usteps_per_s2?: number | null;
	startup_purge_speed_scale?: number | null;
	startup_purge_acceleration_usteps_per_s2?: number | null;
	exit_release_shimmy_amplitude_deg?: number | null;
	exit_release_shimmy_cycles?: number | null;
	exit_release_shimmy_speed_usteps_per_s?: number | null;
	exit_release_shimmy_acceleration_usteps_per_s2?: number | null;
	idle_jog_enabled?: boolean | null;
	idle_jog_step_deg?: number | null;
	idle_jog_cooldown_s?: number | null;
	unjam_enabled?: boolean | null;
	unjam_stall_s?: number | null;
	unjam_min_progress_deg?: number | null;
	unjam_cooldown_s?: number | null;
	unjam_reverse_deg?: number | null;
	unjam_forward_deg?: number | null;
	reconcile_min_hit_count?: number | null;
	reconcile_min_score?: number | null;
	reconcile_min_age_s?: number | null;
	simulate_chute?: boolean | null;
	simulated_chute_move_s?: number | null;
	chute_settle_s?: number | null;
	fall_time_s?: number | null;
	position_timeout_s?: number | null;
	ready_timeout_s?: number | null;
	normal?: RotorTuning | null;
	precision?: RotorTuning | null;
	transport?: RotorTuning | null;
	eject?: RotorTuning | null;
};

export type RuntimeTuning = {
	version?: number;
	channels?: Record<string, RuntimeTuningChannel>;
	slots?: Record<string, number | null>;
};

export type RuntimeTuningPatch = {
	channels?: Record<string, Record<string, unknown>>;
	slots?: Record<string, number>;
};

export async function fetchRuntimeTuning(baseUrl: string): Promise<RuntimeTuning> {
	const response = await fetch(`${baseUrl}/api/rt/tuning`, { cache: 'no-store' });
	const data = (await response.json().catch(() => ({}))) as {
		detail?: string;
		tuning?: RuntimeTuning;
	};
	if (!response.ok) {
		throw new Error(data.detail ?? 'Could not load runtime tuning.');
	}
	return data.tuning ?? {};
}

export async function updateRuntimeTuning(
	baseUrl: string,
	patch: RuntimeTuningPatch
): Promise<RuntimeTuning> {
	const response = await fetch(`${baseUrl}/api/rt/tuning`, {
		method: 'POST',
		headers: { 'content-type': 'application/json' },
		body: JSON.stringify(patch)
	});
	const data = (await response.json().catch(() => ({}))) as {
		detail?: string;
		tuning?: RuntimeTuning;
	};
	if (!response.ok) {
		throw new Error(data.detail ?? 'Could not update runtime tuning.');
	}
	return data.tuning ?? {};
}
