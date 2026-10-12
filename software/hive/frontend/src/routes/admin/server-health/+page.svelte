<script lang="ts">
	import { goto } from '$app/navigation';
	import { onMount } from 'svelte';
	import Spinner from '$lib/components/Spinner.svelte';

	onMount(() => {
		void goto('/admin/server', { replaceState: true });
	});
</script>

<div class="flex justify-center p-8"><Spinner size={32} /></div>
