<script lang="ts">
	import Spinner from './Spinner.svelte';

	let { ssid, seconds }: { ssid: string; seconds: number } = $props();
</script>

<section class="setup-panel flex flex-col items-center gap-5 px-6 py-10 text-center">
	<span class="text-primary"><Spinner size={32} /></span>
	<div class="flex flex-col gap-2">
		<h1 class="text-2xl font-bold break-words text-text">Joining {ssid}</h1>
		<p class="text-sm text-text-muted">
			{seconds > 60 ? 'This is taking longer than usual.' : 'This can take up to a minute.'}
			Keep this page open.
		</p>
	</div>
</section>
