// What the StallGuard tab works out from numbers it already has: what the
// driver's timing makes of a speed, and what a threshold would have done to a
// recording. Also the shapes of what the backend returns for a motor's
// recordings (server/routers/stallguard.py, stepper_telemetry.py).

// The driver counts TSTEP, the time of one 1/256 microstep, in ticks of its
// nominal 12 MHz clock. So a speed in µsteps/s gives a TSTEP that depends on the
// microstepping, and the driver checks for a stall only while TSTEP is at or
// under TCOOLTHRS.
const TMC_CLOCK_HZ = 12_000_000;

/** The TSTEP a motor cruises at, at `speed` µsteps/s with 1/`microsteps` stepping. */
export function tstepAtSpeed(speed: number, microsteps: number): number {
	return Math.round((TMC_CLOCK_HZ * microsteps) / (speed * 256));
}

/** The slowest speed in µsteps/s at which TSTEP is still at or under `tstep`. */
export function speedAtTstep(tstep: number, microsteps: number): number {
	return Math.ceil((TMC_CLOCK_HZ * microsteps) / (tstep * 256));
}

// A sweep's cruise filter sits a little above the TSTEP of its speed, so the
// cruise counts and the speeding up and slowing down does not. It reproduces the
// 150 the chute was tuned with at 3000 µsteps/s (TSTEP 125, 1/8 stepping).
const CRUISE_FILTER_MARGIN = 1.2;
const FALLBACK_CRUISE_TSTEP = 150;

/** The cruise TSTEP a sweep at `speed` should filter by, when nobody set one. */
export function autoCruiseTstep(speed: number | null, microsteps: number): number {
	if (speed === null || speed <= 0) return FALLBACK_CRUISE_TSTEP;
	return Math.round(tstepAtSpeed(speed, microsteps) * CRUISE_FILTER_MARGIN);
}

/** A recording's start, as the browser writes dates; a dash where it has none. */
export function fmtTime(epoch: number | null): string {
	if (!epoch) return '–';
	return new Date(epoch * 1000).toLocaleString();
}

// A motor's automatic tuning, as GET /stepper/{motor}/stallguard-auto gives it
// (stallguard_tuner.py). Only `motor`, `supported`, `auto` and `running` are
// there when the tuner does not run or does not tune the motor.
export type AutoTuning = {
	motor: string;
	supported: boolean;
	auto: boolean;
	running: boolean;
	state?: 'off' | 'waiting' | 'learning' | 'tuned';
	readings?: number;
	needed?: number;
	learned_from?: number;
	normal_low?: number | null;
	baseline_low?: number | null;
	working_harder?: boolean;
	reliable?: boolean;
	tuned_at?: number | null;
	sgthrs?: number | null;
	trigger?: number | null;
	tcoolthrs?: number | null;
	speed?: number | null;
	floor_speed?: number | null;
	changes?: {
		at: number;
		sgthrs: [number | null, number];
		tcoolthrs: [number | null, number];
		why: string;
	}[];
	error?: string | null;
};

export type Replay = {
	// The readings the driver would have looked at: the motor was moving and
	// TSTEP was at or under the speed floor.
	looked: number;
	// Of those, the ones at or under the trigger (twice SGTHRS). Each is a stall
	// the driver would have called.
	tripped: number;
	// The lowest reading it looked at.
	lowest: number | null;
};

export type Sample = { t: number; sg_result: number; cs_actual: number; tstep: number };

/** What the driver would have done with a recording, given a threshold and a speed floor. */
export function replay(samples: Sample[], sgthrs: number, tcoolthrs: number): Replay {
	let looked = 0;
	let tripped = 0;
	let lowest: number | null = null;
	for (const s of samples) {
		if (s.sg_result < 0 || s.tstep <= 0 || s.tstep > tcoolthrs) continue;
		looked += 1;
		if (lowest === null || s.sg_result < lowest) lowest = s.sg_result;
		if (s.sg_result <= 2 * sgthrs) tripped += 1;
	}
	return { looked, tripped, lowest };
}

export type RunParams = {
	// Signed: a negative speed is counterclockwise.
	speed?: number;
	direction?: string;
	duration_s?: number;
	loaded?: boolean;
	cruise_tstep?: number;
	irun?: number | null;
	acceleration?: number | null;
	microsteps?: number | null;
	stealthchop?: boolean | null;
};

export type Run = {
	id: string;
	started_at: number;
	ended_at: number | null;
	source: string;
	stepper_name: string | null;
	label: string | null;
	status: string;
	params: RunParams | null;
	sample_count: number;
	sg_min: number | null;
	sg_max: number | null;
	sg_mean: number | null;
	suggested_sgthrs: number | null;
};

export type SummaryRow = {
	stepper_name: string;
	samples: number;
	sg_min: number;
	sg_max: number;
	sg_mean: number;
	last_seen: number;
};

export type ChartPoint = { x: number; sg: number | null; cs: number | null; tstep: number | null };

// The threshold for a motor at one speed, worked out from its latest free-running
// recording and its latest stall at that speed (server-computed), with the
// trigger placed at the geometric midpoint of the gap.
export type Suggestion = {
	stepper: string;
	// The recommended TCOOLTHRS, the speed floor.
	cruise_tstep: number;
	measured_cruise_tstep: number | null;
	unloaded_floor: number | null;
	loaded_dip: number | null;
	trigger_level: number | null;
	suggested_sgthrs: number | null;
	enough_data: boolean;
	reliable: boolean;
	realistic_floor: number | null;
	speed: number | null;
	unloaded_runs: number;
	loaded_runs: number;
	detail: string;
};

export type Profile = 'constant' | 'chute_random' | 'pulsed';

// How a sweep moves the motor, and the few options an expert changes. The speed
// is not here: it is the tuning's, set in its first step.
export type SweepOptions = {
	profile: Profile;
	direction: 'cw' | 'ccw';
	duration: number;
	label: string;
	// null follows the speed (autoCruiseTstep).
	cruiseTstep: number | null;
	chuteMinDeg: number;
	chuteMaxDeg: number;
	minDeltaDeg: number;
	pulseDeg: number;
	dwellMs: number;
	jitterEvery: number;
	enterToRun: boolean;
};

export function defaultSweepOptions(motor: string): SweepOptions {
	return {
		// A constant spin only suits a free-running motor. The chute aims to angles
		// (a random go-to with a turnaround), and the rotors and the carousel pulse
		// with the odd jitter: those mirror real load.
		profile: motor === 'chute' ? 'chute_random' : 'pulsed',
		direction: 'cw',
		duration: 4,
		label: '',
		cruiseTstep: null,
		chuteMinDeg: 10,
		chuteMaxDeg: 340,
		minDeltaDeg: 30,
		pulseDeg: 30,
		dwellMs: 250,
		jitterEvery: 5,
		enterToRun: false
	};
}

/** What a sweep with these options does, in a sentence. */
export function motionSentence(o: SweepOptions): string {
	if (o.profile === 'chute_random') {
		return `Random moves, ${o.chuteMinDeg}° to ${o.chuteMaxDeg}°, ${o.duration} s. Homes first if needed.`;
	}
	if (o.profile === 'pulsed') {
		return `Short pulses with pauses, ${o.duration} s.`;
	}
	return `A steady spin, ${o.duration} s.`;
}
