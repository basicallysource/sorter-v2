import { getChute } from '$lib/api/chute';
import { getFeeder } from '$lib/api/feeder';
import type { StepperKey } from '$lib/settings/stations';

// The two ways a stepper turns, in words.
export const DIRECTION_WORDS = { cw: 'clockwise', ccw: 'counterclockwise' } as const;

// A press moves a set angle, runs a set time, or runs until Stop.
export type StepperPulseMode = 'duration' | 'degrees' | 'continuous';

export type StoredStepperPulseSettings = {
	pulseMode: StepperPulseMode;
	pulseDuration: number;
	pulseSpeed: number;
	pulseDegrees: number;
};

const DEFAULT_STEPPER_PULSE_SETTINGS: StoredStepperPulseSettings = {
	pulseMode: 'duration',
	pulseDuration: 0.25,
	pulseSpeed: 800,
	pulseDegrees: 90
};

// Every motor but the chute's turns a C-channel. Their gearing depends on the
// machine (geared or direct drive), and the chute's on its kind of chute, so
// each ratio is asked of the machine (stepperGearRatio).
export type CChannelStepperKey = Exclude<StepperKey, 'chute'>;

export function isFeederStepper(stepperKey: StepperKey): stepperKey is CChannelStepperKey {
	return stepperKey !== 'chute';
}

// The gear the channel motors' hand speeds, shakes and presets were tuned on
// (motor turns per channel turn, the geared feeder). On another drive the same
// channel motion takes motor values scaled by the machine's own ratio over this.
export const TUNED_CHANNEL_GEAR_RATIO = 130 / 12;
const TUNED_PULSE_SPEED = 800;

// How a channel motor's angles, speeds and accelerations tuned on the geared
// channels scale on a machine whose channels are geared `gearRatio`: 1 on the
// geared feeder, about 0.09 on a direct drive. The chute's values are its own.
export function channelDriveScale(stepperKey: StepperKey, gearRatio: number): number {
	return isFeederStepper(stepperKey) ? gearRatio / TUNED_CHANNEL_GEAR_RATIO : 1;
}

// The hand speed kept for a motor, for a machine whose channels are geared
// `gearRatio`. A speed kept for another drive is scaled to turn the channel as
// fast here; the untouched default becomes this drive's default.
export function pulseSpeedForDrive(stepperKey: StepperKey, gearRatio: number): number {
	const stored = loadStoredStepperPulseSetting<number>(stepperKey, 'pulseSpeed', TUNED_PULSE_SPEED);
	if (!isFeederStepper(stepperKey)) return stored;
	const keptFor = loadStoredStepperPulseSetting<number>(stepperKey, 'pulseSpeedGearRatio', 0);
	if (keptFor > 0 && Math.abs(keptFor - gearRatio) < 1e-6) return stored;
	let speed = stored;
	if (keptFor > 0) {
		speed = Math.max(1, Math.round((stored * gearRatio) / keptFor));
	} else if (stored === TUNED_PULSE_SPEED) {
		speed = Math.max(1, Math.round(TUNED_PULSE_SPEED * channelDriveScale(stepperKey, gearRatio)));
	}
	persistStoredStepperPulseSetting(stepperKey, 'pulseSpeed', speed);
	persistStoredStepperPulseSetting(stepperKey, 'pulseSpeedGearRatio', gearRatio);
	return speed;
}

export async function stepperGearRatio(baseUrl: string, stepperKey: StepperKey): Promise<number> {
	if (stepperKey === 'chute') {
		return checkedRatio(Number((await getChute(baseUrl)).gear_ratio), "the chute's");
	}
	return checkedRatio(Number((await getFeeder(baseUrl)).gear_ratio), "the C-channels'");
}

function checkedRatio(ratio: number, whose: string): number {
	if (!(Number.isFinite(ratio) && ratio > 0)) {
		throw new Error(`The machine did not say ${whose} gear ratio.`);
	}
	return ratio;
}

export const CLASSIFICATION_CHANNEL_STEPPER_LABEL = 'Classification C-channel (C4)';

export function stepperPulseStorageKey(stepperKey: StepperKey, field: string): string {
	return `stepper:${stepperKey}:${field}`;
}

export function loadStoredStepperPulseSetting<T>(
	stepperKey: StepperKey,
	field: string,
	fallback: T
): T {
	try {
		if (typeof localStorage === 'undefined') return fallback;
		const raw = localStorage.getItem(stepperPulseStorageKey(stepperKey, field));
		if (raw === null) return fallback;
		const parsed = JSON.parse(raw);
		return typeof parsed === typeof fallback ? parsed : fallback;
	} catch {
		return fallback;
	}
}

export function persistStoredStepperPulseSetting(
	stepperKey: StepperKey,
	field: string,
	value: unknown
): void {
	try {
		if (typeof localStorage === 'undefined') return;
		localStorage.setItem(stepperPulseStorageKey(stepperKey, field), JSON.stringify(value));
	} catch {
		// ignore persistence failures in the UI
	}
}

export function loadStoredStepperPulseSettings(stepperKey: StepperKey): StoredStepperPulseSettings {
	return {
		pulseMode: loadStoredStepperPulseSetting<StepperPulseMode>(
			stepperKey,
			'pulseMode',
			DEFAULT_STEPPER_PULSE_SETTINGS.pulseMode
		),
		pulseDuration: loadStoredStepperPulseSetting<number>(
			stepperKey,
			'pulseDuration',
			DEFAULT_STEPPER_PULSE_SETTINGS.pulseDuration
		),
		pulseSpeed: loadStoredStepperPulseSetting<number>(
			stepperKey,
			'pulseSpeed',
			DEFAULT_STEPPER_PULSE_SETTINGS.pulseSpeed
		),
		pulseDegrees: loadStoredStepperPulseSetting<number>(
			stepperKey,
			'pulseDegrees',
			DEFAULT_STEPPER_PULSE_SETTINGS.pulseDegrees
		)
	};
}

export async function triggerStoredStepperPulse(
	baseUrl: string,
	stepperKey: StepperKey,
	direction: 'cw' | 'ccw',
	options?: {
		gearRatio?: number;
	}
): Promise<string> {
	const settings = loadStoredStepperPulseSettings(stepperKey);
	const gearRatio = options?.gearRatio ?? (await stepperGearRatio(baseUrl, stepperKey));
	settings.pulseSpeed = pulseSpeedForDrive(stepperKey, gearRatio);

	if (settings.pulseMode === 'degrees') {
		const motorDegrees =
			settings.pulseDegrees * gearRatio * (direction === 'ccw' ? -1 : 1);
		const params = new URLSearchParams({
			stepper: stepperKey,
			degrees: String(motorDegrees),
			speed: String(settings.pulseSpeed)
		});
		const res = await fetch(`${baseUrl}/stepper/move-degrees?${params.toString()}`, {
			method: 'POST'
		});
		if (!res.ok) {
			throw new Error(await readStepperErrorMessage(res));
		}
		return `Moving ${settings.pulseDegrees}° ${DIRECTION_WORDS[direction]}.`;
	}

	const params = new URLSearchParams({
		stepper: stepperKey,
		direction,
		duration_s: String(settings.pulseDuration),
		speed: String(settings.pulseSpeed)
	});
	const res = await fetch(`${baseUrl}/stepper/pulse?${params.toString()}`, {
		method: 'POST'
	});
	if (!res.ok) {
		throw new Error(await readStepperErrorMessage(res));
	}
	return `Pulsing ${DIRECTION_WORDS[direction]}.`;
}

async function readStepperErrorMessage(res: Response): Promise<string> {
	try {
		const data = await res.json();
		if (typeof data?.detail === 'string') return data.detail;
		if (typeof data?.message === 'string') return data.message;
	} catch {
		// fall through
	}
	try {
		return await res.text();
	} catch {
		return `Request failed with status ${res.status}`;
	}
}
