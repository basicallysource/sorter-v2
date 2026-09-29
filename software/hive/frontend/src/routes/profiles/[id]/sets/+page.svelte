<script lang="ts">
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import { onMount } from 'svelte';
	import Spinner from '$lib/components/Spinner.svelte';

	onMount(() => {
		void goto(`/profiles/${page.params.id}/edit`, { replaceState: true });
	});
</script>

<div class="flex justify-center p-8"><Spinner size={32} /></div>
