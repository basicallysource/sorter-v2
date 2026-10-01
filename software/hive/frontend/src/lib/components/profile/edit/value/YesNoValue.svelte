<!--
	A condition's value when it is a yes or a no (the catalog keeps it as 1 and
	0): one control with the two choices, never a number to type.
-->
<script lang="ts">
	import SegmentedControl from '$lib/components/SegmentedControl.svelte';

	let {
		label,
		value,
		onchange
	}: {
		label: string;
		value: unknown;
		onchange: (value: unknown) => void;
	} = $props();

	const current = $derived(String(value) === '0' ? 'no' : 'yes');
</script>

<SegmentedControl
	{label}
	value={current}
	options={[
		{ value: 'yes', label: 'Yes' },
		{ value: 'no', label: 'No' }
	]}
	onchange={(next) => onchange(next === 'yes' ? 1 : 0)}
/>
