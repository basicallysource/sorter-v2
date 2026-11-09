// The chute: which kind it is, its settings, its home sensor and its
// calibrations (backend server/routers/chute.py). Code that behaves
// differently per kind of chute reads the facts here (turns_freely,
// falls_through, home_on, ...), never the kind's name.

import { getJson, postJson } from './http';

export type HomeOn = 'switch' | 'magnet';

// One kind of chute (backend subsystems/distribution/chute_variants.py).
export type ChuteVariantInfo = {
	key: string;
	label: string;
	summary: string;
	turns_freely: boolean;
	falls_through: boolean;
	fixed_bottom_door: boolean;
	home_on: HomeOn;
};

// A bin, every index counted from 0.
export type BinAddress = {
	layer_index: number;
	section_index: number;
	bin_index: number;
};

export type ChuteSettings = {
	num_sections: number;
	section_width_deg: number;
	first_section_offset_deg: number;
	section_pitch_deg: number;
	pillar_width_deg: number;
	// The older name for the first section's offset.
	first_bin_center: number;
	endstop_active_high: boolean;
	operating_speed_microsteps_per_second: number;
	position_check: boolean;
	position_check_every: number;
	home_pin_channel: number;
	variant: string;
	variant_label: string;
	// Whether the kind of chute was saved, rather than assumed.
	variant_saved: boolean;
	variants: ChuteVariantInfo[];
	turns_freely: boolean;
	// A piece no door catches falls out of the bottom into a tray.
	falls_through: boolean;
	fixed_bottom_door: boolean;
	home_on: HomeOn;
	// How far the chute turns from home; null when it turns without limit.
	max_angle_deg: number | null;
	gear_ratio: number;
	gear_ratio_measured: boolean;
	// Where the pieces no bin takes go, on a chute nothing falls out of.
	discard_bin: BinAddress | null;
};

export type ChuteLive = {
	live_available: boolean;
	// The home sensor reads as found: the switch pressed, or the magnet over the sensor.
	endstop_triggered: boolean | null;
	raw_endstop_high: boolean | null;
	endstop_active_high: boolean | null;
	endstop_error?: string;
	stepper_direction_inverted?: boolean | null;
	current_angle: number | null;
	homed?: boolean | null;
	home_pin_channel: number | null;
};

type Saved = { ok: true; settings: ChuteSettings; message?: string; applied_live?: boolean };

export function getChute(base: string): Promise<ChuteSettings> {
	return getJson<ChuteSettings>(base, '/api/hardware-config/chute');
}

export function getChuteLive(base: string): Promise<ChuteLive> {
	return getJson<ChuteLive>(base, '/api/hardware-config/chute/live');
}

// Any of the chute's settings; the ones left out stay as saved.
export type ChuteChanges = Partial<{
	first_bin_center: number;
	pillar_width_deg: number;
	endstop_active_high: boolean;
	operating_speed_microsteps_per_second: number;
	position_check: boolean;
	position_check_every: number;
}>;

export function saveChute(base: string, changes: ChuteChanges): Promise<Saved> {
	return postJson<Saved>(base, '/api/hardware-config/chute', changes);
}

export function saveChuteVariant(
	base: string,
	variant: string
): Promise<Saved & { restart_needed: boolean; message: string }> {
	return postJson(base, '/api/hardware-config/chute/variant', { variant });
}

// The discard bin, or null to have none.
export function saveDiscardBin(base: string, bin: BinAddress | null): Promise<Saved> {
	return postJson<Saved>(base, '/api/hardware-config/chute/discard-bin', bin ?? {});
}

// Homes the chute on its switch or its magnet; answers when it is done.
export function findChuteHome(base: string): Promise<{ ok: true; message: string; status: ChuteLive }> {
	return postJson(base, '/api/hardware-config/chute/calibrate/find-endstop');
}

// Stops every motor.
export function stopChute(base: string): Promise<{ ok: true; message: string }> {
	return postJson(base, '/api/hardware-config/chute/calibrate/cancel');
}

// On a chute that turns without limit: measures how many motor turns one
// turn of the chute takes, saves it and homes again.
export function measureChuteTurn(
	base: string
): Promise<{ ok: true; gear_ratio: number; homed: boolean; message: string; settings: ChuteSettings }> {
	return postJson(base, '/api/hardware-config/chute/calibrate/measure-turn');
}

export function sameBin(a: BinAddress | null | undefined, b: BinAddress | null | undefined): boolean {
	return (
		!!a &&
		!!b &&
		a.layer_index === b.layer_index &&
		a.section_index === b.section_index &&
		a.bin_index === b.bin_index
	);
}
