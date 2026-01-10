<script lang="ts">
	import { onMount } from 'svelte';
	import { connectWebSocket } from '$lib/api/ws';
	import type { SocketEvent } from '$lib/api/events';

	let ws: WebSocket | null = null;
	let events: SocketEvent[] = $state([]);

	onMount(() => {
		ws = connectWebSocket(
			'ws://localhost:8000/ws',
			(event) => {
				if (event.tag === 'heartbeat') {
					console.log(`[HEARTBEAT] timestamp: ${event.data.timestamp}`);
				} else {
					console.log('Received event:', event);
				}
				events.push(event);
			}
		);

		return () => {
			ws?.close();
		};
	});
</script>

<h1>Sorter UI</h1>
<p>WebSocket connected to backend</p>

<h2>Events:</h2>
<ul>
	{#each events as event}
		<li>
			{#if event.tag === 'heartbeat'}
				<strong>Heartbeat</strong>: {new Date(event.data.timestamp * 1000).toLocaleTimeString()}
			{:else}
				{JSON.stringify(event)}
			{/if}
		</li>
	{/each}
</ul>
