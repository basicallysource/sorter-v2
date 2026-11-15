// How the feeder's motors (C-channels 1 to 3) turn their channels: through a
// gear, or directly (backend hardware_settings/feeder.py). Set in the machine's
// config by hand, so this is read only.

import { getJson } from './http';

export type FeederSettings = {
	drive: string;
	// Motor turns per channel turn.
	gear_ratio: number;
};

export function getFeeder(base: string): Promise<FeederSettings> {
	return getJson<FeederSettings>(base, '/api/hardware-config/feeder');
}
