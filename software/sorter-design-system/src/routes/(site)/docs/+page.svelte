<script lang="ts">
	import Doc from '$lib/site/Doc.svelte';
	import { docs } from '$lib/site/docs';

	const index = docs.find((d) => d.slug === 'README') ?? docs[0];
</script>

{#if index}<Doc doc={index} />{/if}
