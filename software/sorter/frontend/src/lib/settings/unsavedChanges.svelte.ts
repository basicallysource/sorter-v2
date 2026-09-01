// Unsaved-changes guard for the Settings pages.
//
// Every settings page is the same shape: fetch a config object, bind it to a
// form, POST it back. This watches the form against the last-saved snapshot and
// intercepts navigation while they differ.
//
// The design goal is NOT to catch every edit — it is to never fire when the
// user has no real unsaved work, because a guard that cries wolf gets clicked
// through on reflex and then fails to protect anything. So:
//
//   - Dirtiness is a *comparison against the saved snapshot*, never a flag set
//     on first keystroke. Type a value, undo it, and the page is clean again.
//   - Values are canonicalised before comparing. <input type="number"> hands
//     back strings, so a form that loaded 2000 and was never touched reads back
//     "2000"; comparing raw would mark every page dirty on load.
//   - It stays disarmed until a snapshot exists (i.e. the initial load
//     finished) and while a save is in flight.
//   - Navigation we trigger ourselves, after the user has chosen, is exempt.

import { beforeNavigate, goto } from '$app/navigation';

export type UnsavedGuardOptions = {
	// Live form state. Called on every comparison, so keep it cheap.
	current: () => unknown;
	// The page's own save. Resolve on success, throw/reject on failure — a
	// failed save must not let the navigation through.
	save: () => Promise<void>;
	// False while the page is still loading or otherwise not ready to guard.
	ready?: () => boolean;
};

function canonicalize(value: unknown): unknown {
	if (Array.isArray(value)) return value.map(canonicalize);
	if (value && typeof value === 'object') {
		const source = value as Record<string, unknown>;
		const out: Record<string, unknown> = {};
		// Key order is an implementation detail of whatever produced the object;
		// sorting keeps a re-fetched config from looking different to a typed one.
		for (const key of Object.keys(source).sort()) out[key] = canonicalize(source[key]);
		return out;
	}
	if (typeof value === 'string') {
		const trimmed = value.trim();
		// Number inputs round-trip through strings. "2000" and 2000 are the same
		// setting; treating them as different is the classic phantom-dirty bug.
		if (trimmed !== '' && Number.isFinite(Number(trimmed))) return Number(trimmed);
	}
	return value;
}

function fingerprint(value: unknown): string {
	return JSON.stringify(canonicalize(value));
}

export function createUnsavedGuard(options: UnsavedGuardOptions) {
	// null until the first markSaved() — an unloaded page has nothing to lose.
	let snapshot = $state<string | null>(null);
	let busy = $state(false);
	let pendingUrl = $state<string | null>(null);
	let error = $state<string | null>(null);
	// Set only while we re-issue a navigation the user already approved, so our
	// own goto() doesn't bounce off the guard it just cleared.
	let releasing = false;

	const ready = () => (options.ready ? options.ready() : true);

	const isDirty = $derived.by(() => {
		if (snapshot === null || busy || !ready()) return false;
		return fingerprint(options.current()) !== snapshot;
	});

	// Call after a successful load or save: this is the state we can return to.
	function markSaved() {
		snapshot = fingerprint(options.current());
	}

	function close() {
		pendingUrl = null;
		error = null;
	}

	async function saveAndLeave() {
		busy = true;
		error = null;
		try {
			await options.save();
		} catch (e: any) {
			// Keep the dialog up with the reason; leaving now would discard the
			// very edits the user asked us to keep.
			error = e?.message ?? 'Failed to save';
			busy = false;
			return;
		}
		markSaved();
		busy = false;
		leave();
	}

	function discardAndLeave() {
		// Adopt the current values as the snapshot rather than reverting them —
		// the page is being torn down anyway, and this makes the guard fall
		// silent for the re-issued navigation.
		markSaved();
		leave();
	}

	function leave() {
		const url = pendingUrl;
		close();
		if (!url) return;
		releasing = true;
		goto(url).finally(() => {
			releasing = false;
		});
	}

	beforeNavigate((nav) => {
		if (releasing || !isDirty) return;
		// A full page unload can't host a custom dialog; the browser's own
		// "leave site?" prompt is the only option there, wired up below.
		if (nav.type === 'leave') return;
		if (!nav.to?.url) return;
		nav.cancel();
		pendingUrl = nav.to.url.href;
		error = null;
	});

	$effect(() => {
		if (!isDirty) return;
		const onBeforeUnload = (event: BeforeUnloadEvent) => {
			event.preventDefault();
			// Required by older browsers; the message itself is never shown.
			event.returnValue = '';
		};
		window.addEventListener('beforeunload', onBeforeUnload);
		return () => window.removeEventListener('beforeunload', onBeforeUnload);
	});

	return {
		get isDirty() {
			return isDirty;
		},
		get promptUrl() {
			return pendingUrl;
		},
		get busy() {
			return busy;
		},
		get error() {
			return error;
		},
		markSaved,
		saveAndLeave,
		discardAndLeave,
		stay: close
	};
}

export type UnsavedGuard = ReturnType<typeof createUnsavedGuard>;
