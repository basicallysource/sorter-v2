<script lang="ts">
	import { Button } from '$lib/components/primitives';
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

<div class="flex flex-col gap-3">
	{#each presets as preset}
		<div class="flex items-start gap-3">
			<div class="w-44 shrink-0">
				<Button variant="secondary" size="sm" onclick={() => apply(preset)}>
					{preset.label}
				</Button>
			</div>
			<span class="text-sm text-text-muted">{preset.description}</span>
		</div>
	{/each}
</div>
