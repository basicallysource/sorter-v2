<script lang="ts">
	import { Input, InfoTip } from '$lib/components/primitives';
	import type { TuningFieldMeta, TuningValues } from '$lib/settings/tuning';

	// One tunable parameter: label, an info icon explaining it (when the backend
	// supplies a description), the default hint, and a number/checkbox input.
	// Shared by every tuning page. `values` is the page's reactive config object;
	// this row writes the edited value straight back into it.
	let {
		field,
		values = $bindable()
	}: {
		field: TuningFieldMeta;
		values: TuningValues;
	} = $props();
</script>

<div class="flex items-center gap-4">
	<label class="flex w-72 items-center gap-1.5 text-sm text-text" for={field.key}>
		<span>{field.label}</span>
		{#if field.description}
			<InfoTip text={field.description} />
		{/if}
		<span class="ml-auto shrink-0 text-xs text-text-muted">(default: {field.default})</span>
	</label>
	{#if field.type === 'bool'}
		<input
			id={field.key}
			type="checkbox"
			checked={Boolean(values[field.key])}
			onchange={(e) => (values[field.key] = e.currentTarget.checked)}
		/>
	{:else}
		<div class="w-40">
			<!-- Function binding coerces the number|boolean store to a real number
			     (the numeric branch only renders for non-bool fields). -->
			<Input
				id={field.key}
				type="number"
				bind:value={() => Number(values[field.key]), (v) => (values[field.key] = Number(v))}
			/>
		</div>
	{/if}
</div>
