<!--
	What the chosen rule takes, as the draft stands: how many parts, the colors it
	limits them to, and the parts themselves as PartTiles, most sold first, with a
	search box to look for one and "Show more" for the rest. It asks the server
	again a moment after each change, so it follows the conditions as they are
	edited. A kit rule shows its lines instead (see KitLines).
-->
<script lang="ts">
	import { untrack } from 'svelte';
	import {
		api,
		type BinColor,
		type BinConditions,
		type ProfileBin,
		type ProfileDocument,
		type RuleMatchPart
	} from '$lib/api';
	import Button from '$lib/components/Button.svelte';
	import ColorChip from '$lib/components/ColorChip.svelte';
	import ConditionList from '$lib/components/ConditionList.svelte';
	import Input from '$lib/components/Input.svelte';
	import PartTile from '$lib/components/PartTile.svelte';
	import Spinner from '$lib/components/Spinner.svelte';
	import { plural } from './rules';

	let {
		draft,
		draftKey,
		ruleId,
		bin
	}: {
		draft: ProfileDocument;
		// Changes whenever the draft does; the parts are asked for again.
		draftKey: string;
		ruleId: string;
		// What the live preview made of the rule, for its conditions in words.
		bin: ProfileBin | undefined;
	} = $props();

	const FIRST = 24;
	const MORE = 48;
	// Colors named before "and N more".
	const COLORS_SHOWN = 10;

	let query = $state('');
	let items = $state.raw<RuleMatchPart[]>([]);
	let total = $state(0);
	let colors = $state.raw<BinColor[] | null>(null);
	let loading = $state(true);
	let loadingMore = $state(false);
	let failed = $state(false);
	let latest = 0;
	let ranOnce = false;

	$effect(() => {
		void draftKey;
		const text = query.trim();
		const mine = ++latest;
		loading = true;
		// The first look is at once; later ones wait for the typing to stop.
		const wait = ranOnce ? 300 : 0;
		ranOnce = true;
		const timer = setTimeout(async () => {
			try {
				const res = await api.previewSortingRule(
					untrack(() => draft),
					{ rule_id: ruleId, q: text, limit: FIRST }
				);
				if (mine !== latest) return;
				items = res.items;
				total = res.total;
				colors = res.colors;
				failed = false;
			} catch {
				if (mine !== latest) return;
				failed = true;
			}
			loading = false;
		}, wait);
		return () => clearTimeout(timer);
	});

	async function more() {
		const mine = latest;
		loadingMore = true;
		try {
			const res = await api.previewSortingRule(draft, {
				rule_id: ruleId,
				q: query.trim(),
				offset: items.length,
				limit: MORE
			});
			if (mine === latest) items = [...items, ...res.items];
		} catch {
			failed = true;
		}
		loadingMore = false;
	}

	const shownColors = $derived((colors ?? []).slice(0, COLORS_SHOWN));
	// A condition with nothing chosen yet is sent back with an empty list as its
	// value; it has nothing to say in words.
	function answered(conditions: BinConditions): BinConditions {
		return {
			...conditions,
			items: conditions.items
				.map((item) => ({
					...item,
					values: item.values.filter((v) => !(Array.isArray(v.value) && v.value.length === 0))
				}))
				.filter((item) => item.values.length > 0),
			groups: conditions.groups.map((group) => ({ ...group, ...answered(group) })).filter((g) => g.items.length + g.groups.length > 0)
		};
	}
	const words = $derived(bin?.conditions ? answered(bin.conditions) : null);
	const hasWords = $derived(Boolean(words && words.items.length + words.groups.length > 0));
</script>

<div class="flex flex-col gap-5 p-(--pad-panel)">
	{#if hasWords && words}
		<section class="flex flex-col gap-2">
			<h3 class="label">In words</h3>
			<ConditionList conditions={words} limit={6} />
		</section>
	{/if}

	<section class="flex flex-col gap-3">
		<div class="flex items-center justify-between gap-2">
			<h3 class="label">What matches</h3>
			{#if loading}<Spinner size={14} class="text-ink-muted" />{/if}
		</div>

		{#if failed && items.length === 0}
			<p class="text-sm text-danger-ink">The parts could not be loaded. Change the rule, or try again in a moment.</p>
		{:else}
			<div class="flex flex-wrap items-baseline gap-x-2">
				<span class="num text-2xl font-medium text-ink">{total.toLocaleString('en-US')}</span>
				<span class="text-sm text-ink-muted">{total === 1 ? 'part matches' : 'parts match'}, the most sold first</span>
			</div>

			{#if colors !== null && colors.length > 0}
				<div class="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm">
					<span class="text-ink-muted">Only in</span>
					{#each shownColors as color (color.id)}
						<ColorChip name={color.name} rgb={color.rgb} class="text-ink" />
					{/each}
					{#if colors.length > shownColors.length}
						<span class="text-ink-muted">and {plural(colors.length - shownColors.length, 'more color')}</span>
					{/if}
				</div>
			{/if}

			<Input
				type="search"
				size="sm"
				placeholder="Search these parts"
				aria-label="Search the parts that match"
				autocomplete="off"
				bind:value={query}
			/>

			{#if items.length > 0}
				<div class="grid grid-cols-2 gap-x-3 gap-y-4 sm:grid-cols-3">
					{#each items as part (part.part_num)}
						<PartTile
							layout="tile"
							name={part.name}
							imgUrl={part.img_url}
							bricklinkId={part.bricklink_id}
							partNum={part.part_num}
						/>
					{/each}
				</div>
				{#if items.length < total}
					<div>
						<Button size="sm" loading={loadingMore} onclick={more}>
							Show more of the {total.toLocaleString('en-US')}
						</Button>
					</div>
				{/if}
			{:else if !loading}
				<p class="rounded-control bg-well px-3 py-6 text-center text-sm text-ink-muted">
					{query.trim()
						? `No matching part has "${query.trim()}" in its name or number.`
						: hasWords
							? 'No part matches these conditions.'
							: 'Nothing to match yet. Choose a field and a value.'}
				</p>
			{/if}
		{/if}
	</section>
</div>
