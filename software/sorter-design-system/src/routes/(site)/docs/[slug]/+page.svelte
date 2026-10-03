<script lang="ts">
	import { page } from '$app/state';
	import { error } from '@sveltejs/kit';
	import Doc from '$lib/site/Doc.svelte';
	import { docs } from '$lib/site/docs';

	const doc = $derived.by(() => {
		const found = docs.find((d) => d.slug === page.params.slug);
		if (!found) error(404, 'No such doc');
		return found;
	});
</script>

{#key doc.slug}
	<Doc {doc} />
{/key}
