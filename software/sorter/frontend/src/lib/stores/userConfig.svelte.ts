/**
 * Global cached user config, mirrored to localStorage.
 *
 * This is the app's small "instant" cache: values we don't want to re-request
 * on every load and would rather show immediately from disk, then reconcile
 * with the backend once connected. Right now that's the user-chosen theme color
 * and the machine name (so the top bar paints correctly before the WebSocket
 * identity arrives), and whether the storage layers page shows its advanced
 * settings.
 *
 * Hydration is synchronous at import (reads localStorage once) so consumers can
 * read the cached value before the first paint. Every setter is equality-guarded
 * and persists on change — no `$effect`, so there is no re-entrancy / loop risk.
 */

const STORAGE_KEY = 'sorter.userConfig';

export interface UserConfigData {
	machineName: string | null;
	colorId: string | null;
	servoAdvanced: boolean;
}

const DEFAULTS: UserConfigData = {
	machineName: null,
	colorId: null,
	servoAdvanced: false
};

function readStored(): UserConfigData {
	if (typeof window === 'undefined') return { ...DEFAULTS };
	try {
		const raw = window.localStorage.getItem(STORAGE_KEY);
		if (!raw) return { ...DEFAULTS };
		const parsed = JSON.parse(raw) as Partial<UserConfigData>;
		return {
			machineName: typeof parsed.machineName === 'string' ? parsed.machineName : null,
			colorId: typeof parsed.colorId === 'string' ? parsed.colorId : null,
			servoAdvanced: parsed.servoAdvanced === true
		};
	} catch {
		return { ...DEFAULTS };
	}
}

let data = $state<UserConfigData>(readStored());

function persist(): void {
	if (typeof window === 'undefined') return;
	try {
		window.localStorage.setItem(STORAGE_KEY, JSON.stringify(data));
	} catch (e) {
		console.error('Failed to persist user config', e);
	}
}

export const userConfig = {
	get machineName(): string | null {
		return data.machineName;
	},
	get colorId(): string | null {
		return data.colorId;
	},
	get servoAdvanced(): boolean {
		return data.servoAdvanced;
	},

	setMachineName(name: string | null): void {
		if (data.machineName === name) return;
		data.machineName = name;
		persist();
	},

	setColorId(colorId: string | null): void {
		if (data.colorId === colorId) return;
		data.colorId = colorId;
		persist();
	},

	setServoAdvanced(on: boolean): void {
		if (data.servoAdvanced === on) return;
		data.servoAdvanced = on;
		persist();
	}
};
