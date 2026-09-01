<script lang="ts">
	import { Input, ToggleSwitch } from '$lib/components/primitives';
	import SettingRow from '$lib/components/settings/SettingRow.svelte';
	import type { TuningFieldMeta, TuningValues } from '$lib/settings/tuning';

	// One tunable parameter row, shared by every tuning page. Wraps SettingRow:
	// info icon from the backend FIELD_META description, changed-from-default
	// highlight, and a revert button that puts the default back (still needs
	// Save to persist, same as any other edit). `values` is the page's reactive
	// config object; this row writes edits straight back into it.
	let {
		field,
		values = $bindable()
	}: {
		field: TuningFieldMeta;
		values: TuningValues;
	} = $props();

	const changed = $derived(
		field.type === 'bool'
			? Boolean(values[field.key]) !== Boolean(field.default)
			: Number(values[field.key]) !== Number(field.default)
	);

	const defaultLabel = $derived(
		field.type === 'bool' ? (field.default ? 'on' : 'off') : String(field.default)
	);

	function revert() {
		values[field.key] = field.default;
	}
</script>

<SettingRow
	label={field.label}
	description={field.description}
	forId={field.key}
	{changed}
	{defaultLabel}
	onRevert={revert}
>
	{#if field.type === 'bool'}
		<ToggleSwitch
			checked={Boolean(values[field.key])}
			label={field.label}
			onToggle={() => (values[field.key] = !values[field.key])}
		/>
	{:else}
		<div class="w-36">
			<!-- Function binding coerces the number|boolean store to a real number
			     (the numeric branch only renders for non-bool fields). -->
			<Input
				id={field.key}
				type="number"
				bind:value={() => Number(values[field.key]), (v) => (values[field.key] = Number(v))}
			/>
		</div>
	{/if}
</SettingRow>
