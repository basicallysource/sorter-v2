<script lang="ts">
	import { ChevronLeft, ChevronRight, Download } from 'lucide-svelte';
	import type { LifetimeDay } from './RecordsStats.svelte';

	let {
		daily,
		exportUrl
	}: {
		daily: LifetimeDay[];
		exportUrl: string;
	} = $props();

	// Two-week blocks; rows arrive newest-first from the backend, so block 0 is
	// the current fortnight.
	const BLOCK_SIZE = 14;
	let block = $state(0);

	const blockCount = $derived(Math.max(1, Math.ceil(daily.length / BLOCK_SIZE)));
	const rows = $derived(daily.slice(block * BLOCK_SIZE, (block + 1) * BLOCK_SIZE));

	$effect(() => {
		if (block >= blockCount) block = Math.max(0, blockCount - 1);
	});

	function formatDayLabel(day: string): string {
		const d = new Date(`${day}T00:00:00`);
		if (Number.isNaN(d.getTime())) return day;
		return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
	}

	function formatDuration(seconds: number | null | undefined): string {
		if (!seconds || seconds <= 0) return '0h 0m';
		const total_min = Math.floor(seconds / 60);
		const days = Math.floor(total_min / 1440);
		const hours = Math.floor((total_min % 1440) / 60);
		const mins = total_min % 60;
		if (days > 0) return `${days}d ${hours}h`;
		return `${hours}h ${mins}m`;
	}

	function formatPpm(ppm: number): string {
		if (!ppm || ppm <= 0) return '—';
		return ppm.toLocaleString(undefined, { maximumFractionDigits: 1 });
	}

	const rangeLabel = $derived.by(() => {
		if (rows.length === 0) return '';
		const newest = formatDayLabel(rows[0].day);
		const oldest = formatDayLabel(rows[rows.length - 1].day);
		return rows.length === 1 ? newest : `${oldest} – ${newest}`;
	});
</script>

{#if daily.length > 0}
	<div class="flex items-center justify-between gap-3">
		<h3 class="text-sm font-semibold tracking-wider text-text-muted uppercase">Daily activity</h3>
		<div class="flex items-center gap-3 text-sm text-text-muted">
			<span>{rangeLabel}</span>
			{#if blockCount > 1}
				<div class="flex border border-border">
					<button
						type="button"
						onclick={() => (block = Math.min(blockCount - 1, block + 1))}
						disabled={block >= blockCount - 1}
						aria-label="Older two weeks"
						class="border-r border-border px-2 py-1 text-text-muted hover:text-text disabled:opacity-40"
					>
						<ChevronLeft size={14} />
					</button>
					<span class="px-3 py-1 text-text">{block + 1} / {blockCount}</span>
					<button
						type="button"
						onclick={() => (block = Math.max(0, block - 1))}
						disabled={block <= 0}
						aria-label="Newer two weeks"
						class="border-l border-border px-2 py-1 text-text-muted hover:text-text disabled:opacity-40"
					>
						<ChevronRight size={14} />
					</button>
				</div>
			{/if}
			<a
				href={exportUrl}
				download
				class="inline-flex items-center justify-center gap-2 border border-border bg-surface px-2.5 py-1 text-xs font-medium text-text transition-colors hover:bg-bg"
				title="Download every recorded day as CSV"
			>
				<Download size={13} />
				Export CSV
			</a>
		</div>
	</div>
	<div class="overflow-x-auto border border-border">
		<table class="w-full border-collapse text-sm">
			<thead>
				<tr class="border-b border-border bg-surface text-left text-text-muted">
					<th class="px-3 py-2 font-semibold">Day</th>
					<th class="px-3 py-2 font-semibold">Powered</th>
					<th class="px-3 py-2 font-semibold">Sorted</th>
					<th class="px-3 py-2 font-semibold">Pieces</th>
					<th class="px-3 py-2 font-semibold">Classified</th>
					<th class="px-3 py-2 font-semibold">PPM</th>
				</tr>
			</thead>
			<tbody>
				{#each rows as d (d.day)}
					<tr class="border-b border-border last:border-b-0 hover:bg-surface">
						<td class="px-3 py-2 text-text">{formatDayLabel(d.day)}</td>
						<td class="px-3 py-2 text-text-muted">{formatDuration(d.seconds_powered)}</td>
						<td class="px-3 py-2 text-text">{formatDuration(d.seconds_sorted)}</td>
						<td class="px-3 py-2 text-text">{d.pieces_distributed.toLocaleString()}</td>
						<td class="px-3 py-2 text-text-muted">{d.pieces_classified.toLocaleString()}</td>
						<td class="px-3 py-2 text-text">
							{formatPpm(d.seconds_sorted > 0 ? (d.pieces_distributed * 60) / d.seconds_sorted : 0)}
						</td>
					</tr>
				{/each}
			</tbody>
		</table>
	</div>
{/if}
