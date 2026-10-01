<!--
	The middle of the editor for a kit rule: its name and picture, and which kit
	it collects (its totals, where it came from, a way to change it or open it to
	edit its parts). A rule from before kits is shown the same way, as the kit it
	becomes when the profile is saved.
-->
<script lang="ts">
	import ArrowUpRight from '@lucide/svelte/icons/arrow-up-right';
	import Replace from '@lucide/svelte/icons/replace';
	import Alert from '$lib/components/Alert.svelte';
	import Button from '$lib/components/Button.svelte';
	import Field from '$lib/components/Field.svelte';
	import Input from '$lib/components/Input.svelte';
	import type { ProfileBin } from '$lib/api';
	import { kitSourceText, loadKitContents, type KitContents } from './kits';
	import RulePicture, { type Candidate } from './RulePicture.svelte';
	import { plural, type Rule } from './rules';

	let {
		rule,
		bin,
		imageUrl,
		warnings,
		ruleProblems,
		reloadKey = 0,
		onchange,
		ontoggle,
		onchoosekit
	}: {
		rule: Rule;
		bin: ProfileBin | undefined;
		imageUrl: string | null;
		warnings: string[];
		ruleProblems: string[];
		// Changes when the kit should be read again.
		reloadKey?: number;
		onchange: (rule: Rule) => void;
		ontoggle: () => void;
		onchoosekit: () => void;
	} = $props();

	const uid = $props.id();

	let contents = $state.raw<KitContents | null>(null);
	const source = $derived([rule.id, rule.kit_id, rule.set_num, rule.custom_parts?.length ?? 0, reloadKey].join('|'));

	$effect(() => {
		void source;
		let current = true;
		loadKitContents(rule, reloadKey)
			.then((loaded) => {
				if (current) contents = loaded;
			})
			.catch(() => {
				if (current) contents = null;
			});
		return () => {
			current = false;
		};
	});

	const lines = $derived(contents?.lines ?? bin?.kit?.line_count ?? 0);
	const lineCount = $derived(typeof lines === 'number' ? lines : lines.length);
	const pieceCount = $derived(
		typeof lines === 'number' ? (bin?.kit?.total_quantity ?? 0) : lines.reduce((sum, line) => sum + line.quantity, 0)
	);
	const facts = $derived(
		[
			lineCount > 0 ? `${plural(lineCount, 'line')}, ${plural(pieceCount, 'piece')}` : null,
			kitSourceText(contents?.kit ?? null, rule)
		]
			.filter(Boolean)
			.join(' · ')
	);

	async function loadCandidates(query: string): Promise<Candidate[]> {
		const needle = query.toLowerCase();
		return (contents?.lines ?? [])
			.filter((line) => line.imgUrl && (!needle || line.name.toLowerCase().includes(needle)))
			.slice(0, 24)
			.map((line) => ({
				key: line.key,
				name: line.name,
				imgUrl: line.imgUrl,
				bricklinkId: line.bricklinkId,
				partNum: line.partNum
			}));
	}
</script>

<div class="flex flex-col gap-5">
	{#if rule.disabled}
		<Alert tone="info" title="This kit is off">
			Its pieces go on to the rules below it.
			{#snippet actions()}
				<Button size="sm" onclick={ontoggle}>Turn it on</Button>
			{/snippet}
		</Alert>
	{/if}

	<div class="flex flex-col gap-4">
		<Field label="Name" for="{uid}-name">
			<Input
				id="{uid}-name"
				value={rule.name}
				autocomplete="off"
				oninput={(e) => onchange({ ...rule, name: (e.currentTarget as HTMLInputElement).value })}
			/>
		</Field>
		<RulePicture
			{imageUrl}
			own={Boolean(rule.image_url)}
			{loadCandidates}
			onchange={(url) => onchange({ ...rule, image_url: url })}
		/>
	</div>

	{#if ruleProblems.length > 0}
		<Alert tone="danger">
			{#each ruleProblems as message, i (i)}<p>{message}</p>{/each}
		</Alert>
	{/if}
	{#if warnings.length > 0}
		<Alert tone="warning">
			{#each warnings as message, i (i)}<p>{message}</p>{/each}
		</Alert>
	{/if}

	<div class="flex flex-col gap-3 border-t border-line pt-5">
		<h3 class="text-base font-semibold text-ink">Kit</h3>
		{#if rule.rule_type === 'set'}
			<Alert tone="info">
				This rule was made before kits. Saving the profile turns it into a kit that other profiles can use too.
			</Alert>
		{/if}
		{#if contents?.kit}<p class="text-sm font-medium text-ink">{contents.kit.name}</p>{/if}
		{#if facts}<p class="text-sm text-ink-muted">{facts}</p>{/if}
		<p class="text-sm text-ink-muted">
			A piece of one of its parts, in one of its colors, goes in this bin until the kit is full. Then it goes on
			to the next rule that takes it.
		</p>
		<div class="flex flex-wrap gap-2">
			{#if rule.rule_type === 'kit'}
				<Button size="sm" icon={Replace} onclick={onchoosekit}>Change kit</Button>
			{/if}
			{#if rule.kit_id}
				<Button
					size="sm"
					variant="ghost"
					icon={ArrowUpRight}
					href="/kits/{rule.kit_id}"
					target="_blank"
					rel="noopener"
				>
					Open the kit
				</Button>
			{/if}
		</div>
	</div>
</div>
