<script lang="ts">
	import { onDestroy, onMount } from 'svelte';
	import { backendHttpBaseUrl, machineHttpBaseUrlFromWsUrl } from '$lib/backend';
	import { getMachineContext } from '$lib/machines/context';
	import TrackedPieceDetailModal from './TrackedPieceDetailModal.svelte';

	type HistoryItem = {
		global_id: number;
		created_at: number;
		finished_at: number;
		duration_s: number;
		roles: string[];
		handoff_count: number;
		segment_count: number;
		total_hit_count: number;
		live: boolean;
		composite_jpeg_b64?: string;
	};

	const ctx = getMachineContext();

	function effectiveBase(): string {
		return machineHttpBaseUrlFromWsUrl(ctx.machine?.url) ?? backendHttpBaseUrl;
	}

	let items = $state<HistoryItem[]>([]);
	let pollTimer: ReturnType<typeof setInterval> | null = null;
	let selectedId = $state<number | null>(null);

	async function load() {
		try {
			const res = await fetch(`${effectiveBase()}/api/feeder/tracking/history?limit=30`);
			if (!res.ok) return;
			const json = await res.json();
			items = Array.isArray(json?.items) ? json.items : [];
		} catch {
			// ignore
		}
	}

	function formatHashId(id: number): string {
		// Mirrors backend format_track_label: Knuth multiplicative hash mod 10000.
		const mixed = (id * 2654435761) >>> 0;
		return (mixed % 10000).toString().padStart(4, '0');
	}

	function formatDuration(seconds: number): string {
		if (seconds < 1) return `${(seconds * 1000).toFixed(0)}ms`;
		if (seconds < 60) return `${seconds.toFixed(1)}s`;
		const m = Math.floor(seconds / 60);
		return `${m}m ${Math.floor(seconds % 60)}s`;
	}

	function formatRoles(roles: string[]): string {
		const short = roles.map((r) => r.replace('c_channel_', 'C'));
		return short.join(' → ');
	}

	onMount(() => {
		void load();
		pollTimer = setInterval(() => void load(), 2000);
	});

	onDestroy(() => {
		if (pollTimer !== null) {
			clearInterval(pollTimer);
			pollTimer = null;
		}
	});
</script>

<div class="flex h-full min-h-0 flex-col border border-border bg-surface">
	<div class="flex-shrink-0 border-b border-border px-3 py-2 text-sm font-semibold text-text">
		Tracked Pieces
	</div>

	<div class="min-h-0 flex-1 overflow-auto">
		{#if items.length === 0}
			<div class="px-3 py-4 text-xs text-text-muted">
				No pieces tracked yet.
			</div>
		{:else}
			<div class="grid grid-cols-4 gap-2 p-2">
				{#each items as item (item.global_id)}
					<button
						type="button"
						onclick={() => (selectedId = item.global_id)}
						class="group relative flex flex-col items-stretch border border-border bg-bg text-left text-xs text-text hover:border-primary/70"
					>
						<div class="relative aspect-square w-full bg-black">
							{#if item.composite_jpeg_b64}
								<img
									src={`data:image/jpeg;base64,${item.composite_jpeg_b64}`}
									alt=""
									class="block h-full w-full object-cover"
								/>
							{:else}
								<div class="flex h-full w-full items-center justify-center text-xs text-text-muted">
									{item.live ? '…' : '—'}
								</div>
							{/if}
							<span
								class={`absolute top-1 left-1 inline-block h-1.5 w-1.5 rounded-full ${
									item.live ? 'bg-success' : 'bg-text-muted/70'
								}`}
								aria-hidden="true"
							></span>
							{#if item.handoff_count > 0}
								<span class="absolute top-1 right-1 border border-primary bg-bg/80 px-1 text-xs font-medium text-primary">
									H
								</span>
							{/if}
						</div>
						<div class="flex flex-col gap-0.5 px-1.5 py-1">
							<span class="font-mono font-medium leading-none">#{formatHashId(item.global_id)}</span>
							<span class="truncate text-text-muted leading-none">{formatRoles(item.roles)}</span>
							<span class="text-text-muted leading-none">{formatDuration(item.duration_s)}</span>
						</div>
					</button>
				{/each}
			</div>
		{/if}
	</div>
</div>

{#if selectedId !== null}
	<TrackedPieceDetailModal
		globalId={selectedId}
		onClose={() => (selectedId = null)}
	/>
{/if}
