<script lang="ts">
	import { onMount } from 'svelte';

	let ws: WebSocket | null = null;
	let events: any[] = $state([]);

	onMount(() => {
		ws = new WebSocket('ws://localhost:8000/ws');

		ws.onopen = () => {
			console.log('WebSocket connected');
		};

		ws.onmessage = (event) => {
			const data = JSON.parse(event.data);
			console.log('Received event:', data);
			events.push(data);
		};

		ws.onerror = (error) => {
			console.error('WebSocket error:', error);
		};

		ws.onclose = () => {
			console.log('WebSocket disconnected');
		};

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
		<li>{JSON.stringify(event)}</li>
	{/each}
</ul>
