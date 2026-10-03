<!--
	What happens to the pieces no rule takes: one choice, not three switches. The
	rest all go to one bin, or to a bin for each BrickLink category, each
	Rebrickable category, or each color. A fallback by color needs the sorter's
	current software, which is said when it is chosen.

	Below it, what the machine does when a piece's category has no bin and none
	is free: stop and ask (the machine's own setting), send it to Everything
	else, or share a bin, so a run with more categories than bins keeps going.
-->
<script lang="ts">
	import Alert from '$lib/components/Alert.svelte';
	import RadioGroup from '$lib/components/RadioGroup.svelte';
	import { plural, type FallbackChoice, type NoBinChoice } from './rules';

	let {
		choice,
		noBin,
		requires,
		restParts,
		onchange,
		onnobin
	}: {
		choice: FallbackChoice;
		noBin: NoBinChoice;
		// What a sorter must be able to do to run the profile as it is now.
		requires: string[];
		// How many parts no rule and no fallback bin takes, when known.
		restParts: number | null;
		onchange: (choice: FallbackChoice) => void;
		onnobin: (choice: NoBinChoice) => void;
	} = $props();

	const needsNewSoftware = $derived(choice === 'color' || requires.includes('color_fallback'));
</script>

<div class="flex flex-col gap-5">
	<p class="text-sm text-ink-muted">
		A piece goes to the first rule that takes it. The pieces no rule takes go here.
	</p>

	<RadioGroup
		label="Where the rest go"
		name="fallback"
		value={choice}
		options={[
			{ value: 'none', label: 'All together', help: 'Every piece no rule takes goes to Everything else.' },
			{
				value: 'bl_category',
				label: 'BrickLink categories',
				help: 'Sorted by BrickLink category, such as Brick, Plate or Tile.'
			},
			{
				value: 'rb_category',
				label: 'Rebrickable categories',
				help: 'Sorted by Rebrickable category.'
			},
			{ value: 'color', label: 'Color', help: 'Sorted by color, whatever the part.' }
		]}
		{onchange}
	/>

	{#if needsNewSoftware}
		<Alert tone="info" title="Needs the sorter's current software">
			A machine on older software cannot run a profile that sorts the rest by color.
		</Alert>
	{/if}

	{#if restParts !== null && choice !== 'color'}
		<p class="border-t border-line pt-4 text-sm text-ink-muted">
			{plural(restParts, 'part')} in the catalog {restParts === 1 ? 'goes' : 'go'} to the bin for everything else.
		</p>
	{/if}

	<div class="border-t border-line pt-5">
		<RadioGroup
			label="When the bins run out"
			name="no-bin"
			value={noBin}
			options={[
				{
					value: 'machine',
					label: 'Stop and ask',
					help: "The machine's own setting: it waits for someone to give the new category a bin."
				},
				{
					value: 'misc',
					label: 'Send it to Everything else',
					help: 'A category that finds no free bin goes with everything else, and the run keeps going.'
				},
				{
					value: 'share',
					label: 'Share a bin',
					help: 'The least filled bin takes the new category too, and the run keeps going.'
				}
			]}
			onchange={onnobin}
		/>
	</div>
</div>
