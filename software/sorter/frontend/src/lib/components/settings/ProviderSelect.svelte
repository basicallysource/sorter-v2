<script module lang="ts">
	export type ProviderInfo = {
		id: string;
		label: string;
		description: string;
	};
</script>

<script lang="ts">
	// One provider out of a few, each with its sentence: the system's RadioGroup.
	import RadioGroup from '$lib/components/ui/RadioGroup.svelte';

	let {
		options,
		selected = $bindable(''),
		active = '',
		name
	}: {
		options: ProviderInfo[];
		selected?: string;
		active?: string;
		// The radios' shared name, and the group's accessible name.
		name: string;
	} = $props();
</script>

<RadioGroup
	{name}
	label={name}
	bind:value={selected}
	options={options.map((p) => ({
		value: p.id,
		label: p.id === active ? `${p.label} (in use)` : p.label,
		help: p.description
	}))}
/>
