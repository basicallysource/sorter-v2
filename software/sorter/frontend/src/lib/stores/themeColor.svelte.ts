/**
 * Runtime store for the user's chosen LEGO primary color.
 *
 * The selected color is persisted on the backend (`/api/settings/theme`) so it
 * survives reboots and is shared across browser tabs that hit the same Sorter.
 * Locally we mirror it into a Svelte 5 rune so reactive UI bits (the swatch
 * grid in the wizard / settings) can highlight the active swatch.
 *
 * Applying a color = writing four CSS variables (`--color-primary`,
 * `--color-primary-hover`, `--color-primary-dark`, `--color-primary-contrast`)
 * onto `<html>`. Tailwind v4 utilities like `bg-primary` reference those vars,
 * so the entire UI re-skins instantly without a reload.
 */

import { backendHttpBaseUrl } from '$lib/backend';
import { applyLegoColorVars, DEFAULT_COLOR_ID, getLegoColor } from '$lib/lego-colors';

let currentColorId = $state(DEFAULT_COLOR_ID);

export function getCurrentThemeColorId(): string {
	return currentColorId;
}

/**
 * Apply a color id to the document and update the local rune.
 * Does NOT persist to the backend — call `setThemeColor` for that.
 */
function applyColorIdLocally(colorId: string): void {
	const color = getLegoColor(colorId);
	currentColorId = color.id;
	applyLegoColorVars(color);
}

/**
 * Fetch the user's saved theme color from the backend and apply it.
 * Falls back to the LEGO Blue default on any failure (offline, 404, etc.) so
 * the UI always renders with a sensible primary.
 */
export async function loadThemeColor(): Promise<void> {
	if (typeof window === 'undefined') return;
	try {
		const response = await fetch(`${backendHttpBaseUrl}/api/settings/theme`);
		if (!response.ok) {
			applyColorIdLocally(DEFAULT_COLOR_ID);
			return;
		}
		const data = (await response.json()) as { color_id?: string };
		applyColorIdLocally(typeof data.color_id === 'string' ? data.color_id : DEFAULT_COLOR_ID);
	} catch {
		applyColorIdLocally(DEFAULT_COLOR_ID);
	}
}

/**
 * Update the theme color locally (instant re-skin) AND persist it.
 * If the POST fails the local change stays in place — the user still gets
 * the visual change for the rest of the session.
 */
export async function setThemeColor(colorId: string): Promise<void> {
	applyColorIdLocally(colorId);
	if (typeof window === 'undefined') return;
	try {
		await fetch(`${backendHttpBaseUrl}/api/settings/theme`, {
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify({ color_id: colorId })
		});
	} catch (error) {
		console.error('Failed to persist theme color', error);
	}
}
