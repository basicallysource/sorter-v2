<script lang="ts">
	// What a profile does with a piece, as its bins: a card for every rule and
	// kit in the order a piece meets them, one row for each bin the fallback
	// makes for the parts no rule takes (there can be hundreds), and Everything
	// else. Used for a version on Hive and for the profile the machine runs.
	import Alert from '$lib/components/ui/Alert.svelte';
	import ProfileBin, { type Bin } from '$lib/components/ui/ProfileBin.svelte';
	import Stat from '$lib/components/ui/Stat.svelte';
	import { groupBins, leftoverSentence } from '$lib/sorting-profiles/bins';
	import type { ProfileWarning, SortingProfileFallbackMode } from '$lib/sorting-profiles/types';

	type Props = {
		categories: Record<string, Bin>;
		order?: string[] | null;
		warnings?: ProfileWarning[] | null;
		fallback?: SortingProfileFallbackMode | null;
		stats?: { total_parts?: number; sorted?: number } | null;
	};

	let {
		categories,
		order = null,
		warnings = null,
		fallback = null,
		stats = null
	}: Props = $props();

	const groups = $derived(groupBins(categories, order, warnings));
	const count = $derived(groups.rules.length + groups.leftover.length + groups.rest.length);
	// Warnings about the profile as a whole, not one rule.
	const general = $derived((warnings ?? []).filter((w) => !w.rule_id));
	// Saved before bins were described: only names are known.
	const namesOnly = $derived(
		count > 0 && [...groups.rules, ...groups.leftover, ...groups.rest].every((e) => !e.bin.kind)
	);
	const total = $derived(stats?.total_parts);
	const sorted = $derived(stats?.sorted);

	function whole(n: number) {
		return n.toLocaleString('en-US');
	}
</script>

<div class="flex flex-col gap-4">
	<div class="grid gap-px overflow-hidden rounded-control bg-line sm:grid-cols-2">
		<div class="bg-well"><Stat label="Bins" value={whole(count)} /></div>
		{#if total != null && sorted != null}
			<div class="bg-well">
				<Stat
					label="Parts with a bin of their own"
					value={whole(sorted)}
					hint={sorted === total ? 'every known part' : `of ${whole(total)} known parts`}
				/>
			</div>
		{:else if total != null}
			<div class="bg-well"><Stat label="Known parts" value={whole(total)} /></div>
		{/if}
	</div>

	{#each general as warning (warning.message)}
		<Alert tone="warning">{warning.message}</Alert>
	{/each}

	{#if count === 0}
		<p class="text-ink-muted">This version has no bins.</p>
	{:else}
		{#if namesOnly}
			<p class="text-ink-muted">
				This version was saved before bins were described, so only their names are known.
			</p>
		{/if}

		{#if groups.rules.length > 0}
			<div class="flex flex-col gap-2">
				{#each groups.rules as entry (entry.id)}
					<ProfileBin bin={entry.bin} number={entry.number} warnings={entry.warnings} plane="well" />
				{/each}
			</div>
		{/if}

		{#if groups.leftover.length > 0}
			<section class="flex flex-col gap-2">
				<p class="text-ink-muted">
					{leftoverSentence(fallback).replace(/\.$/, '')} ({whole(groups.leftover.length)}
					{groups.leftover.length === 1 ? 'bin' : 'bins'}).
				</p>
				<ul class="max-h-96 divide-y divide-line overflow-y-auto rounded-control bg-well">
					{#each groups.leftover as entry (entry.id)}
						<li><ProfileBin layout="row" bin={entry.bin} plane="well" /></li>
					{/each}
				</ul>
			</section>
		{/if}

		{#if groups.rest.length > 0}
			<div class="flex flex-col gap-2">
				{#each groups.rest as entry (entry.id)}
					<ProfileBin bin={entry.bin} warnings={entry.warnings} plane="well" />
				{/each}
			</div>
		{/if}
	{/if}
</div>
