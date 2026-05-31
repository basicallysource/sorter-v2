<script lang="ts">
	import { goto } from '$app/navigation';

	// The captive-portal probe redirects here. This page is deliberately a
	// dead-simple launcher: a captive mini-window (macOS CNA / iOS) can't be
	// escaped programmatically and closes the moment the AP drops, so we don't
	// run any real setup here. We point the user at a real browser tab at the
	// fixed address, where the full flow lives at /setup and survives the
	// network switch. The address is fixed by sorteros-ap-up.sh (gw 10.42.0.1).
	const SETUP_URL = 'http://10.42.0.1/setup';

	let copied = $state(false);
	async function copyUrl() {
		try {
			await navigator.clipboard.writeText(SETUP_URL);
			copied = true;
			setTimeout(() => (copied = false), 1500);
		} catch {
			// clipboard may be blocked in the captive window — the URL is shown
			// in full anyway, so the user can just type it.
		}
	}

	function continueHere() {
		// For Android, where the captive view is usually a real Chrome tab.
		void goto('/setup');
	}
</script>

<svelte:head>
	<title>SorterOS Setup</title>
</svelte:head>

<main class="mx-auto flex min-h-screen w-full max-w-md flex-col items-center justify-center gap-7 px-5 py-10 text-center">
	<div>
		<div class="text-sm tracking-wider text-[var(--color-text-muted)] uppercase">Welcome</div>
		<h1 class="mt-1 text-2xl font-bold">Set up your sorter</h1>
	</div>

	<p class="text-[var(--color-text-muted)]">
		Open your normal browser (Safari/Chrome) and go to the address below. Stay connected to
		<span class="text-[var(--color-text)]">SorterOS-Setup</span> — if this is a small pop-up,
		closing it won't disconnect you.
	</p>

	<div class="flex w-full flex-col items-stretch gap-2">
		<div
			class="border border-[var(--color-border)] bg-[var(--color-surface)] px-4 py-5 font-mono text-xl break-all text-[var(--color-text)]"
		>
			http://10.42.0.1/setup
		</div>
		<button
			type="button"
			onclick={copyUrl}
			class="border border-[var(--color-border)] bg-[var(--color-surface)] px-4 py-2 text-sm text-[var(--color-text-muted)] hover:text-[var(--color-text)]"
		>
			{copied ? 'Copied ✓' : 'Copy address'}
		</button>
	</div>

	<div class="flex flex-col items-center gap-1">
		<button
			type="button"
			onclick={continueHere}
			class="text-sm font-medium text-[var(--color-text)] underline underline-offset-4 hover:text-[var(--color-accent-dark)]"
		>
			Continue in this window →
		</button>
		<span class="text-xs text-[var(--color-text-muted)]/80">
			(fine on Android; on Mac/iPhone use the address above)
		</span>
	</div>
</main>
