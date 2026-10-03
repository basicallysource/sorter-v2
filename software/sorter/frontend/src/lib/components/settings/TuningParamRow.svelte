<script lang="ts">
	import Input from '$lib/components/ui/Input.svelte';
	import Switch from '$lib/components/ui/Switch.svelte';
	import SettingRow from '$lib/components/ui/SettingRow.svelte';
	import type { TuningFieldMeta, TuningValues } from '$lib/settings/tuning';

	// One tunable parameter row, shared by every tuning page: a SettingRow
	// with the backend's FIELD_META description as its help, and the
	// changed-from-default tint with its reset (which still needs Save to
	// persist, like any other edit). `values` is the page's reactive
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
	help={field.description}
	for={field.type === 'bool' ? undefined : field.key}
	{changed}
	defaultText={defaultLabel}
	onreset={revert}
>
	{#if field.type === 'bool'}
		<Switch
			checked={Boolean(values[field.key])}
			label={field.label}
			onchange={() => (values[field.key] = !values[field.key])}
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
