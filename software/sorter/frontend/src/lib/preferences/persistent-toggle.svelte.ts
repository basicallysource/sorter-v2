/**
 * Boolean toggle state that survives page reloads via ``localStorage``.
 *
 * Typical use inside a ``.svelte`` component:
 *
 * ```ts
 * const annotated = persistentToggle({
 *   key: () => `camera-feed:${route}:${camera}:annotated`,
 *   default: () => defaultAnnotated && layer === 'annotated',
 * });
 * ```
 *
 * In the template, access or bind the nested ``.value``:
 *
 * ```svelte
 * <input type="checkbox" bind:checked={annotated.value} />
 * {#if annotated.value} ... {/if}
 * ```
 *
 * Details:
 *
 * - **SSR-safe.** Reads and writes are ``typeof localStorage === 'undefined'``
 *   guarded so server render uses the fallback without touching window.
 * - **Reactive keys.** Pass ``key`` as a thunk to rehydrate when the key
 *   changes — e.g. a camera-scoped toggle that re-reads whenever the camera
 *   prop flips.
 * - **No default clobber.** The write-back is gated on a ``ready`` flag set
 *   in the same tick as the first read, so the SSR default never overwrites
 *   a stored value during hydration.
 * - **Legacy-compatible parsing.** Accepts both ``'0'/'1'`` and
 *   ``'false'/'true'`` strings; always writes ``'0'/'1'``.
 */

import { untrack } from 'svelte';

const LEGACY_TRUE = new Set(['1', 'true']);
const LEGACY_FALSE = new Set(['0', 'false']);

function readStoredBoolean(key: string, fallback: boolean): boolean {
	if (typeof localStorage === 'undefined') return fallback;
	try {
		const raw = localStorage.getItem(key);
		if (raw === null) return fallback;
		if (LEGACY_TRUE.has(raw)) return true;
		if (LEGACY_FALSE.has(raw)) return false;
		return fallback;
	} catch {
		return fallback;
	}
}

function writeStoredBoolean(key: string, value: boolean): void {
	if (typeof localStorage === 'undefined') return;
	try {
		localStorage.setItem(key, value ? '1' : '0');
	} catch {
		// Quota / private mode — silently ignore.
	}
}

export interface PersistentToggleOptions {
	key: string | (() => string);
	default: boolean | (() => boolean);
}

export interface PersistentToggle {
	value: boolean;
}

export function persistentToggle(options: PersistentToggleOptions): PersistentToggle {
	const getKey =
		typeof options.key === 'function' ? options.key : (() => options.key as string);
	const getDefault =
		typeof options.default === 'function'
			? options.default
			: (() => options.default as boolean);

	// Initial value is the default so SSR and first client paint agree.
	let current = $state(untrack(getDefault));
	let ready = $state(false);

	// Re-read whenever the key changes. ``ready`` flips in the same tick so the
	// write effect below sees a consistent (key, value) pair.
	$effect(() => {
		const key = getKey();
		current = readStoredBoolean(key, untrack(getDefault));
		ready = true;
	});

	// Write-back. Tracks ``current`` only; reads the key untracked so a key
	// change alone doesn't cause a write with the old value — the read effect
	// above handles that case by refreshing ``current`` first.
	$effect(() => {
		const value = current;
		if (!ready) return;
		untrack(() => writeStoredBoolean(getKey(), value));
	});

	return {
		get value() {
			return current;
		},
		set value(next: boolean) {
			current = next;
		}
	};
}
