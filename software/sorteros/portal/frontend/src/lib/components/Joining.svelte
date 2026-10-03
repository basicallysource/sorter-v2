<script lang="ts">
	import Spinner from './Spinner.svelte';

	let {
		ssid,
		seconds,
		setupSsid,
		liveJoin
	}: { ssid: string; seconds: number; setupSsid: string | null; liveJoin: boolean } = $props();
</script>

<section class="flex flex-col items-center gap-5 rounded-panel bg-surface px-6 py-10 text-center">
	<span class="text-primary-ink"><Spinner size={32} /></span>
	<div class="flex flex-col gap-2">
		<h1 class="text-2xl font-semibold tracking-tight break-words text-ink">Joining {ssid}</h1>
		{#if liveJoin}
			<p class="text-sm text-balance text-ink-muted">
				{seconds > 60 ? 'This is taking longer than usual.' : 'This can take up to a minute.'}
				Keep this page open. If it closes, rejoin {setupSsid ?? "the Sorter's setup network"} to see
				how it went.
			</p>
		{:else}
			<p class="text-sm text-balance text-ink-muted">
				Your phone loses this page while the Sorter joins. If
				{setupSsid ?? "the Sorter's setup network"} comes back, rejoin it to see why.
			</p>
		{/if}
	</div>
</section>
