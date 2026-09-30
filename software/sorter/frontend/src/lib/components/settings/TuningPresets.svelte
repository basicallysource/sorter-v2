<script lang="ts">
	import Button from '$lib/components/ui/Button.svelte';
	import type { TuningPreset, TuningValues } from '$lib/settings/tuning';

	// Renders a list of one-click presets for a tuning page. Clicking one merges
	// its values into the form (it does NOT auto-save) so the operator can review
	// and tweak before hitting Save. Shared so any tuning page can offer presets.
	let {
		presets,
		values = $bindable()
	}: {
		presets: TuningPreset[];
		values: TuningValues;
	} = $props();

	function apply(preset: TuningPreset) {
		values = { ...values, ...preset.values };
	}
</script>

<ul class="divide-y divide-line">
	{#each presets as preset}
		<li class="flex flex-col gap-2 px-(--pad-panel) py-(--pad-row) sm:flex-row sm:items-center sm:gap-4">
			<div class="w-44 shrink-0">
				<Button size="sm" onclick={() => apply(preset)}>{preset.label}</Button>
			</div>
			<span class="text-sm text-ink-muted">{preset.description}</span>
		</li>
	{/each}
</ul>
