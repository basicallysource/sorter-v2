<!--
	The color being fed, as a button that opens a picker: the colors used
	lately first, then the commonest, and a search of every color. A pick
	saves at once; while a run is open it starts the run's next segment.
-->
<script lang="ts">
	import ChevronDown from '@lucide/svelte/icons/chevron-down';
	import Button from '$lib/components/ui/Button.svelte';
	import ColorChoice, { type LikelyColor } from '$lib/components/ui/ColorChoice.svelte';
	import Popover from '$lib/components/ui/Popover.svelte';
	import Spinner from '$lib/components/ui/Spinner.svelte';
	import { fetchLegoColors, type BrickLinkColor } from '$lib/pieces/colors';
	import { recentColorIds, saveTrainingConfig, type TrainingState } from '$lib/training/api';
	import RunColors from './RunColors.svelte';

	let {
		base,
		training,
		onsaved
	}: {
		base: string;
		training: TrainingState;
		onsaved: (next: TrainingState) => void;
	} = $props();

	let open = $state(false);
	let palette = $state<BrickLinkColor[] | null>(null);
	let saving = $state(false);
	let error = $state<string | null>(null);

	$effect(() => {
		const from = base;
		palette = null;
		fetchLegoColors(from)
			.then((colors) => {
				if (from === base) palette = colors;
			})
			.catch(() => {
				if (from === base) palette = [];
			});
	});

	const chosen = $derived(training.config.color_ids);
	const value = $derived(chosen.length === 1 ? Number(chosen[0]) : null);

	// There is no ranking to show, so each offered color is plain.
	const offered = $derived.by<LikelyColor[]>(() => {
		const known = new Set((palette ?? []).map((c) => c.id));
		return recentColorIds(training)
			.map(Number)
			.filter((id) => known.has(id))
			.map((color_id) => ({
				color_id,
				score: 1,
				closeness: 1,
				likelihood: 1,
				distance: null,
				hue_diff: null,
				qty: null,
				lots: null,
				share: null
			}));
	});

	async function pick(id: number) {
		open = false;
		if (chosen.length === 1 && chosen[0] === String(id)) return;
		saving = true;
		error = null;
		try {
			onsaved(await saveTrainingConfig(base, { color_ids: [String(id)] }));
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
		} finally {
			saving = false;
		}
	}
</script>

<span class="inline-flex max-w-full min-w-0 flex-col gap-1">
	<Popover label="The color being fed" bind:open width="26rem">
		{#snippet trigger(props)}
			<Button {...props} size="sm" loading={saving} class="max-w-full">
				{#if training.config.colors.length > 0}
					<RunColors colors={training.config.colors} class="min-w-0 overflow-hidden" />
				{:else}
					Pick a color
				{/if}
				<ChevronDown size={14} class="shrink-0 text-ink-muted" />
			</Button>
		{/snippet}
		<div class="max-h-[min(32rem,70vh)] overflow-y-auto">
			{#if palette === null}
				<p class="flex items-center gap-2 text-sm text-ink-muted">
					<Spinner size={14} /> Loading the colors
				</p>
			{:else if palette.length === 0}
				<p class="text-sm text-ink-muted">
					The color list has not loaded: the machine has not reached Hive yet.
				</p>
			{:else}
				<ColorChoice
					{palette}
					likely={offered}
					{value}
					note="Used lately first, then the commonest"
					disabled={saving}
					onpick={pick}
				/>
			{/if}
		</div>
	</Popover>
	{#if error}<span class="text-sm text-danger-ink">{error}</span>{/if}
</span>
