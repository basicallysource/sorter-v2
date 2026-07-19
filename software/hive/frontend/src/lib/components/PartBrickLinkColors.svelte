<script lang="ts">
	import { api, type PartBrickLinkColor } from '$lib/api';
	import Spinner from '$lib/components/Spinner.svelte';

	// Marketplace prior for the labeler: which colors this mold is actually sold
	// in on BrickLink, by pieces currently for sale. A part that only exists in
	// black and yellow makes an ambiguous dark crop a much easier call. Data is
	// the cached price guide in parts.db, not a live API call.
	let { partId, partName }: { partId: string | null; partName?: string | null } = $props();

	let items = $state<PartBrickLinkColor[]>([]);
	let itemNo = $state<string | null>(null);
	let updatedAt = $state<string | null>(null);
	let loading = $state(true);
	let error = $state<string | null>(null);

	async function load(pid: string) {
		loading = true;
		error = null;
		try {
			const res = await api.partBrickLinkColors(pid, 20);
			items = res.items;
			itemNo = res.item_no;
			updatedAt = res.updated_at;
		} catch {
			error = 'Failed to load';
		} finally {
			loading = false;
		}
	}

	$effect(() => {
		const pid = partId;
		if (!pid) {
			items = [];
			itemNo = null;
			loading = false;
			return;
		}
		void load(pid);
	});

	function fmtQty(n: number): string {
		if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
		if (n >= 1_000) return `${Math.round(n / 1000)}k`;
		return String(n);
	}

	const asOf = $derived(updatedAt ? new Date(updatedAt).toLocaleDateString() : null);
</script>

<div class="border border-border bg-surface">
	<div class="border-b border-border px-3 py-2">
		<div class="text-sm font-medium text-text">Sold on BrickLink</div>
		<div class="text-xs text-text-muted">
			{#if !loading && items.length > 0}
				{partName || itemNo} · by pieces for sale{asOf ? ` · as of ${asOf}` : ''}
			{:else}
				what colors this part comes in
			{/if}
		</div>
	</div>

	{#if loading}
		<div class="flex justify-center py-8"><Spinner /></div>
	{:else if error}
		<div class="p-3 text-sm text-primary">{error}</div>
	{:else if !partId}
		<p class="p-4 text-sm text-text-muted">This piece has no identified part.</p>
	{:else if items.length === 0}
		<p class="p-4 text-sm text-text-muted">No BrickLink listings cached for this part.</p>
	{:else}
		<div class="flex flex-col">
			{#each items as it (it.color_id)}
				<div
					class="relative flex items-center gap-2 border-b border-border px-2 py-1.5 last:border-b-0"
					title={`${it.color_name} (${it.color_id}) · ${it.qty.toLocaleString()} pcs in ${it.lots.toLocaleString()} lots · ${it.qty_new.toLocaleString()} new / ${it.qty_used.toLocaleString()} used`}
				>
					<!-- Share bar sits behind the row so the color mix reads at a glance -->
					<div
						class="pointer-events-none absolute inset-y-0 left-0 bg-primary-light"
						style={`width:${(it.share * 100).toFixed(1)}%`}
					></div>
					<span
						class="relative h-4 w-4 shrink-0 border border-border {it.is_trans ? 'opacity-70' : ''}"
						style={`background:#${it.rgb ?? '000'}`}
					></span>
					<span class="relative min-w-0 flex-1 truncate text-xs text-text-muted">{it.color_name}</span>
					<span class="relative shrink-0 text-xs tabular-nums text-text-muted">{fmtQty(it.qty)}</span>
				</div>
			{/each}
		</div>
	{/if}
</div>
