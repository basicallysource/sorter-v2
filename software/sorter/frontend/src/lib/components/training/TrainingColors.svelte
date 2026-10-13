<!--
	The colors of the next training run: the chosen ones as chips that can be
	removed, then a color choice to add another. Each change saves at once.
	While a run is collecting (`locked`) the colors stay as they are.
-->
<script lang="ts">
	import X from '@lucide/svelte/icons/x';
	import ColorChip from '$lib/components/ui/ColorChip.svelte';
	import ColorChoice, { type LikelyColor } from '$lib/components/ui/ColorChoice.svelte';
	import Spinner from '$lib/components/ui/Spinner.svelte';
	import { fetchLegoColors, findLegoColor, type BrickLinkColor } from '$lib/pieces/colors';
	import { saveTrainingConfig, type TrainingState } from '$lib/training/api';

	let {
		base,
		training,
		locked = false,
		onsaved
	}: {
		base: string;
		training: TrainingState;
		locked?: boolean;
		onsaved: (next: TrainingState) => void;
	} = $props();

	// The commonest LEGO colors, by BrickLink id: Black, White, Light and Dark
	// Bluish Gray, Red, Blue, Yellow, Tan, Reddish Brown, Green, Dark Tan, Orange.
	const COMMON = [11, 1, 86, 85, 5, 7, 3, 2, 88, 6, 69, 4];

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
	const chips = $derived(
		chosen.map((id) => {
			const color = training.config.colors.find((c) => c.id === id);
			const known = findLegoColor(id, color?.name);
			return {
				id,
				name: color?.name ?? known?.name ?? `Color ${id}`,
				rgb: color?.rgb ?? known?.hex ?? null
			};
		})
	);
	// Every color not chosen yet.
	const choices = $derived((palette ?? []).filter((c) => !chosen.includes(String(c.id))));

	// Offered before any search: the colors of earlier runs, newest first, then
	// the commonest. There is no ranking to show, so each is plain.
	const offered = $derived.by<LikelyColor[]>(() => {
		const available = new Set(choices.map((c) => c.id));
		const ids: number[] = [];
		const add = (id: number) => {
			if (available.has(id) && !ids.includes(id)) ids.push(id);
		};
		for (const run of training.runs) for (const id of run.color_ids) add(Number(id));
		for (const id of COMMON) add(id);
		return ids.map((color_id) => ({
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

	async function save(ids: string[]) {
		saving = true;
		error = null;
		try {
			onsaved(await saveTrainingConfig(base, { color_ids: ids }));
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
		} finally {
			saving = false;
		}
	}
</script>

<div class="flex flex-col gap-3">
	{#if chips.length > 0}
		<div class="flex flex-wrap items-center gap-1.5">
			{#each chips as chip (chip.id)}
				<span
					class="inline-flex min-h-6 max-w-full min-w-0 items-center gap-1 rounded-badge bg-hover py-0.5 pl-2 text-sm text-ink {locked
						? 'pr-2'
						: 'pr-0.5'}"
				>
					<ColorChip name={chip.name} rgb={chip.rgb} />
					{#if !locked}
						<button
							type="button"
							aria-label="Remove {chip.name}"
							title="Remove {chip.name}"
							disabled={saving}
							onclick={() => save(chosen.filter((id) => id !== chip.id))}
							class="inline-flex size-5 shrink-0 items-center justify-center rounded-item text-ink-muted transition-colors hover:bg-pressed hover:text-ink disabled:opacity-45"
						>
							<X size={14} />
						</button>
					{/if}
				</span>
			{/each}
		</div>
	{/if}

	{#if locked}
		<p class="text-sm text-ink-muted">Pause the machine to change the colors.</p>
	{:else if palette === null}
		<p class="flex items-center gap-2 text-sm text-ink-muted">
			<Spinner size={14} /> Loading the colors
		</p>
	{:else if palette.length === 0}
		<p class="text-sm text-ink-muted">
			The color list has not loaded: the machine has not reached Hive yet.
		</p>
	{:else}
		<ColorChoice
			palette={choices}
			likely={offered}
			note={training.runs.length > 0
				? 'Colors of earlier runs, then the commonest'
				: 'The commonest LEGO colors'}
			disabled={saving}
			onpick={(id) => save([...chosen, String(id)])}
		/>
	{/if}

	{#if error}<p class="text-sm text-danger-ink">{error}</p>{/if}
</div>
