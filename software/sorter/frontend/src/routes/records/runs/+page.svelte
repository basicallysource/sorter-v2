<script lang="ts">
	import RunsAndLots from '$lib/components/records/RunsAndLots.svelte';
	import { recordsBase } from '$lib/records/base';

	const base = recordsBase();
</script>

<svelte:head>
	<title>Runs - Records - Sorter</title>
</svelte:head>

<RunsAndLots endpointBase={base()} />
