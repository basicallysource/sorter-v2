<script lang="ts">
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import { onMount } from 'svelte';

	onMount(() => {
		void goto(`/profiles/${page.params.id}/edit`, { replaceState: true });
	});
</script>

<div class="mx-auto max-w-lg py-12 text-center text-sm text-gray-500">
	Redirecting to the profile editor...
</div>
