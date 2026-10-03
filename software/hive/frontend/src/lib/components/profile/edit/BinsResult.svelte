<!--
	The whole profile as the draft makes it: how much of the catalog the rules
	take, the "where would a piece go" check, and every bin in the order a piece
	meets them (rules and kits, then the category or color bins the fallback
	makes, then Everything else), each as a ProfileBin row. A rule's row chooses
	it. A long run of fallback bins shows its first few.
-->
<script lang="ts">
	import type { ProfileBin as BinData, ProfileDocument, ProfilePreview } from '$lib/api';
	import Button from '$lib/components/Button.svelte';
	import ProfileBin from '$lib/components/ProfileBin.svelte';
	import Spinner from '$lib/components/Spinner.svelte';
	import RouteBox from './RouteBox.svelte';
	import { plural, REST_ID, type Rule } from './rules';

	let {
		preview,
		busy,
		draft,
		draftKey,
		rules,
		selectedId,
		warningsFor,
		onselect
	}: {
		preview: ProfilePreview | null;
		busy: boolean;
		draft: ProfileDocument;
		draftKey: string;
		rules: Rule[];
		selectedId: string | null;
		warningsFor: (id: string) => string[];
		// A rule's ID, or REST_ID for Everything else.
		onselect: (id: string) => void;
	} = $props();

	const FALLBACK_SHOWN = 12;
	let showAllFallback = $state(false);

	const order = $derived(preview?.category_order ?? []);
	const bins = $derived(preview?.categories ?? {});
	const ruleIds = $derived(order.filter((id) => bins[id]?.kind === 'rule' || bins[id]?.kind === 'kit'));
	const fallbackIds = $derived(order.filter((id) => bins[id]?.kind === 'fallback'));
	const restIds = $derived(order.filter((id) => bins[id]?.kind === 'default'));
	const shownFallback = $derived(showAllFallback ? fallbackIds : fallbackIds.slice(0, FALLBACK_SHOWN));
	const byColor = $derived(fallbackIds.length > 0 && 'rgb' in (bins[fallbackIds[0]] ?? {}));

	function numberOf(id: string): number | undefined {
		const index = rules.findIndex((rule) => rule.id === id);
		return index >= 0 ? index + 1 : undefined;
	}
</script>

{#snippet row(id: string, bin: BinData, choosable: boolean)}
	<li>
		<ProfileBin
			layout="row"
			{bin}
			number={numberOf(id)}
			warnings={warningsFor(id)}
			selected={selectedId === id || (bin.kind === 'default' && selectedId === REST_ID)}
			onclick={choosable ? () => onselect(bin.kind === 'default' ? REST_ID : id) : undefined}
		/>
	</li>
{/snippet}

<div class="flex flex-col">
	<div class="flex flex-col gap-5 p-(--pad-panel)">
		<section class="flex flex-col gap-1">
			<div class="flex items-center justify-between gap-2">
				<h3 class="label">The profile</h3>
				{#if busy}<Spinner size={14} class="text-ink-muted" />{/if}
			</div>
			{#if preview}
				<p class="text-sm text-ink">{plural(order.length, 'category', 'categories')} in this profile.</p>
				<p class="text-sm text-ink-muted">
					{preview.stats.sorted.toLocaleString('en-US')} of {preview.stats.total_parts.toLocaleString('en-US')} catalog
					parts are sorted; the rest go to Everything else.
				</p>
			{:else}
				<p class="flex items-center gap-2 text-sm text-ink-muted"><Spinner size={14} />Working out the categories</p>
			{/if}
		</section>

		<RouteBox {draft} {draftKey} {bins} {rules} onselect={(id) => onselect(id)} />
	</div>

	{#if preview}
		{#if ruleIds.length > 0}
			<h3 class="label border-t border-line px-(--pad-panel) py-2">Rules and kits</h3>
			<ul class="divide-y divide-line border-t border-line">
				{#each ruleIds as id (id)}
					{@render row(id, bins[id], true)}
				{/each}
			</ul>
		{/if}

		{#if fallbackIds.length > 0}
			<h3 class="label border-t border-line px-(--pad-panel) py-2">
				{byColor ? 'By color' : 'By category'}
			</h3>
			<ul class="divide-y divide-line border-t border-line">
				{#each shownFallback as id (id)}
					{@render row(id, bins[id], false)}
				{/each}
			</ul>
			{#if fallbackIds.length > FALLBACK_SHOWN}
				<div class="border-t border-line px-(--pad-panel) py-2">
					<Button variant="ghost" size="sm" onclick={() => (showAllFallback = !showAllFallback)}>
						{showAllFallback ? 'Show fewer' : `Show all ${fallbackIds.length.toLocaleString('en-US')} bins`}
					</Button>
				</div>
			{/if}
		{/if}

		{#if restIds.length > 0}
			<h3 class="label border-t border-line px-(--pad-panel) py-2">The rest</h3>
			<ul class="divide-y divide-line border-t border-line">
				{#each restIds as id (id)}
					{@render row(id, bins[id], true)}
				{/each}
			</ul>
		{/if}
	{/if}
</div>
