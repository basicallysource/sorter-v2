<!--
	What a kit rule collects: each line of the kit as a PartTile row, with its
	color and how many are wanted. For a kit that is one of the person's own,
	this is read fresh (`reloadKey` changes when the page comes back into focus,
	so a kit edited in another tab shows what it is now). A rule from before kits
	shows the set's parts, or the parts it carried, the same way.
-->
<script lang="ts">
	import Alert from '$lib/components/Alert.svelte';
	import Button from '$lib/components/Button.svelte';
	import PartTile from '$lib/components/PartTile.svelte';
	import Spinner from '$lib/components/Spinner.svelte';
	import { untrack } from 'svelte';
	import { loadKitContents, type KitContents } from './kits';
	import { plural, type Rule } from './rules';

	let {
		rule,
		reloadKey = 0
	}: {
		rule: Rule;
		// Changes when the kit should be read again.
		reloadKey?: number;
	} = $props();

	const STEP = 24;

	// What the lines come from; only a change in it reads them again, not a
	// change to the rule's name.
	const source = $derived(
		[
			rule.id,
			rule.rule_type,
			rule.kit_id,
			rule.set_num,
			rule.set_source,
			rule.include_spares,
			rule.custom_parts?.length ?? 0,
			reloadKey
		].join('|')
	);

	let contents = $state.raw<KitContents | null>(null);
	let loading = $state(true);
	let failed = $state<string | null>(null);
	let shown = $state(STEP);
	let latest = 0;

	$effect(() => {
		void source;
		const current = untrack(() => rule);
		const mine = ++latest;
		loading = true;
		failed = null;
		loadKitContents(current, reloadKey)
			.then((loaded) => {
				if (mine !== latest) return;
				contents = loaded;
				shown = STEP;
			})
			.catch((e: { error?: string }) => {
				if (mine === latest) failed = e?.error ?? 'The kit could not be loaded.';
			})
			.finally(() => {
				if (mine === latest) loading = false;
			});
	});

	const lines = $derived(contents?.lines ?? []);
	const pieces = $derived(lines.reduce((sum, line) => sum + line.quantity, 0));
</script>

{#if failed}
	<div class="p-(--pad-panel)"><Alert tone="danger">{failed}</Alert></div>
{:else if loading && !contents}
	<p class="flex items-center gap-2 p-(--pad-panel) text-sm text-ink-muted">
		<Spinner size={14} />Loading the kit
	</p>
{:else if lines.length === 0}
	<p class="p-(--pad-panel) text-sm text-ink-muted">This kit has no parts yet.</p>
{:else}
	<p class="px-(--pad-panel) pt-4 pb-2 text-sm text-ink-muted">
		{plural(lines.length, 'line')}, {plural(pieces, 'piece')}
	</p>
	<ul class="divide-y divide-line border-t border-line">
		{#each lines.slice(0, shown) as line (line.key)}
			<li>
				<PartTile
					name={line.name}
					imgUrl={line.imgUrl}
					bricklinkId={line.bricklinkId}
					partNum={line.partNum}
					color={line.color}
					quantity={line.quantity}
				/>
			</li>
		{/each}
	</ul>
	{#if lines.length > shown}
		<div class="border-t border-line px-(--pad-panel) py-2">
			<Button variant="ghost" size="sm" onclick={() => (shown += STEP)}>
				Show more of the {lines.length.toLocaleString('en-US')} lines
			</Button>
		</div>
	{/if}
{/if}
