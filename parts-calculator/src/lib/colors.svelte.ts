// Shared filament-colour configuration — the single source of truth for which
// colour each part role prints in. The 3D-parts tab owns the pickers; the
// assembly tab reads it so a part's 3D preview opens in the colour you actually
// chose rather than the neutral fallback.
//
// Colours used to live in the per-page blob in config.ts. They moved here once
// a second tab needed them; `migrate()` below reads the old blob one last time
// so existing saved builds keep their colours.

import { browser } from '$app/environment';
import { COLOR_ROLES } from '$lib/filament';
import { CONFIG_KEY } from '$lib/config';

const KEY = 'sorter-colors-v1';

export function defaultRoleColors(): Record<string, string> {
	return Object.fromEntries(COLOR_ROLES.map((r) => [r.id, r.default]));
}

// one-time read of the pre-split config blob, for builds saved before this store
function migrate(): Record<string, string> | null {
	try {
		const raw = localStorage.getItem(CONFIG_KEY);
		const c = raw ? JSON.parse(raw) : null;
		const rc = c?.roleColors;
		return rc && typeof rc === 'object' ? (rc as Record<string, string>) : null;
	} catch {
		return null;
	}
}

function load(): Record<string, string> {
	const defaults = defaultRoleColors();
	if (!browser) return defaults;
	try {
		const raw = localStorage.getItem(KEY);
		const v = raw ? JSON.parse(raw) : migrate();
		// merge over defaults so roles added since the save still get a colour
		if (v && typeof v === 'object') return { ...defaults, ...(v as Record<string, string>) };
	} catch {
		/* ignore */
	}
	return defaults;
}

export const colorStore = $state<{ roles: Record<string, string> }>({ roles: load() });

export function setRoleColor(role: string, colorId: string): void {
	colorStore.roles = { ...colorStore.roles, [role]: colorId };
}

export function resetRoleColors(): void {
	colorStore.roles = defaultRoleColors();
}

if (browser) {
	$effect.root(() => {
		$effect(() => {
			try {
				localStorage.setItem(KEY, JSON.stringify(colorStore.roles));
			} catch {
				/* storage full / disabled */
			}
		});
	});
}
