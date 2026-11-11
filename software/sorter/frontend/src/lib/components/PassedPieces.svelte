<script lang="ts">
	/*
		How many pieces the machine has seen since the counter was last reset,
		with the reset button next to it. Every piece counts (classified, misc,
		dead), the number comes from the machine's piece records, and a reset
		only stores a baseline on the machine — the history stays intact. Polled
		like RuntimeStats, so it survives restarts and background tabs.
	*/
	import { getBackendHttpBase, machineHttpBaseUrlFromWsUrl } from '$lib/backend';
	import { getMachineContext } from '$lib/machines/context';
	import Button from '$lib/components/ui/Button.svelte';

	const ctx = getMachineContext();

	let total = $state<number | null>(null);
	let since = $state<number | null>(null);
	let confirming = $state(false);
	let confirmTimer: ReturnType<typeof setTimeout> | undefined;

	function base(): string {
		return machineHttpBaseUrlFromWsUrl(ctx.machine?.url) ?? getBackendHttpBase();
	}

	async function load() {
		try {
			const res = await fetch(`${base()}/api/pieces/counter`);
			if (!res.ok) return;
			const body = await res.json();
			total = body.total_since_reset;
			since = body.reset_at;
		} catch {
			// The next poll tries again.
		}
	}

	async function reset() {
		if (!confirming) {
			confirming = true;
			clearTimeout(confirmTimer);
			confirmTimer = setTimeout(() => (confirming = false), 3000);
			return;
		}
		confirming = false;
		try {
			const res = await fetch(`${base()}/api/pieces/counter/reset`, { method: 'POST' });
			if (!res.ok) return;
			const body = await res.json();
			total = body.total_since_reset;
			since = body.reset_at;
		} catch {
			// The next poll picks the reset up.
		}
	}

	$effect(() => {
		void ctx.machine?.url;
		load();
		const id = setInterval(load, 15000);
		return () => {
			clearInterval(id);
			clearTimeout(confirmTimer);
		};
	});

	function sinceLabel(t: number | null): string {
		if (!t) return 'never reset';
		return new Date(t * 1000).toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' });
	}
</script>

<div class="flex flex-wrap items-center gap-x-4 gap-y-2 border-b border-line px-4 py-3">
	<div class="min-w-0">
		<div class="flex items-baseline gap-2">
			<span class="num text-2xl font-semibold text-ink">{total ?? '–'}</span>
			<span class="text-sm text-ink-muted">pieces since {sinceLabel(since)}</span>
		</div>
	</div>
	<div class="ml-auto">
		<Button size="sm" variant={confirming ? 'danger' : 'secondary'} onclick={reset}>
			{confirming ? 'Really reset?' : 'Reset'}
		</Button>
	</div>
</div>
