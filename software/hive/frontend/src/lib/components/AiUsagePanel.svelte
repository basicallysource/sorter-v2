<script lang="ts">
	import { onMount } from 'svelte';
	import { api, type AiUsageSummary, type AiUsageTotals } from '$lib/api';
	import Spinner from '$lib/components/Spinner.svelte';

	let summary = $state<AiUsageSummary | null>(null);
	let loading = $state(true);
	let error = $state<string | null>(null);

	const periods: { key: keyof AiUsageSummary; label: string }[] = [
		{ key: 'week', label: 'Last 7 days' },
		{ key: 'month', label: 'Last 30 days' },
		{ key: 'year', label: 'Last year' },
		{ key: 'all_time', label: 'All time' }
	];

	onMount(async () => {
		try {
			summary = await api.getAiUsage();
		} catch (e: any) {
			error = e?.error || 'Failed to load AI usage';
		} finally {
			loading = false;
		}
	});

	function totalsFor(key: keyof AiUsageSummary): AiUsageTotals | null {
		const value = summary?.[key];
		return value && typeof value === 'object' ? (value as AiUsageTotals) : null;
	}

	// Single chat turns land around a tenth of a cent, so a flat 2dp would render
	// most of this panel as $0.00.
	function formatCost(cost: number): string {
		if (!cost) return '$0.00';
		if (cost < 0.01) return `$${cost.toFixed(4)}`;
		return `$${cost.toFixed(2)}`;
	}

	function formatCount(value: number): string {
		return value.toLocaleString();
	}
</script>

<div class="border border-border bg-bg p-4">
	<div class="mb-3 flex items-baseline justify-between gap-2">
		<h3 class="text-sm font-medium text-text">AI Spend</h3>
		<span class="text-xs text-text-muted">billed to your OpenRouter key</span>
	</div>

	{#if loading}
		<p class="flex items-center gap-1.5 text-xs text-text-muted"><Spinner size={12} /> Loading…</p>
	{:else if error}
		<p class="text-xs text-text-muted">{error}</p>
	{:else if summary}
		<div class="grid grid-cols-2 gap-px bg-border sm:grid-cols-4">
			{#each periods as period (period.key)}
				{@const totals = totalsFor(period.key)}
				<div class="bg-bg p-3">
					<div class="text-xs text-text-muted">{period.label}</div>
					<div class="mt-1 text-lg font-semibold text-text">
						{formatCost(totals?.cost_usd ?? 0)}
					</div>
					<div class="mt-1 text-xs text-text-muted">
						{formatCount(totals?.message_count ?? 0)} requests · {formatCount(totals?.total_tokens ?? 0)} tokens
					</div>
				</div>
			{/each}
		</div>
		<p class="mt-2 text-xs text-text-muted">
			{#if summary.since}
				Tracked since {new Date(summary.since).toLocaleDateString()}.
			{:else}
				No AI requests recorded yet.
			{/if}
		</p>
	{/if}
</div>
