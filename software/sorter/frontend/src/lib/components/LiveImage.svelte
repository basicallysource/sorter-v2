<script lang="ts">
	// One live camera view, drawn as an <img> of its newest frame. `stale` turns
	// true when no frame has come for STALE_MS; `onframe` gets the <img> each
	// time a new frame is up.
	import { onDestroy } from 'svelte';
	import { getBackendHttpBase, machineHttpBaseUrlFromWsUrl } from '$lib/backend';
	import { getMachineContext } from '$lib/machines/context';
	import { watchVideo } from '$lib/video';

	const STALE_MS = 3000;

	let {
		view,
		baseUrl = '',
		alt,
		class: className = '',
		style = '',
		stale = $bindable(false),
		onframe
	}: {
		view: string;
		baseUrl?: string;
		alt: string;
		class?: string;
		style?: string;
		stale?: boolean;
		onframe?: (img: HTMLImageElement) => void;
	} = $props();

	const ctx = getMachineContext();
	const base = $derived(
		baseUrl || machineHttpBaseUrlFromWsUrl(ctx.machine?.url) || getBackendHttpBase()
	);

	// The object URL the <img> shows or is loading, the one it showed before,
	// and the newest frame to show once the loading one is up: never more than
	// two URLs, and frames that come meanwhile are skipped.
	let src = $state<string | null>(null);
	let shown: string | null = null;
	let next: Blob | null = null;
	let lastFrameAt = 0;

	function show(jpeg: Blob) {
		fresh();
		if (src !== shown) next = jpeg;
		else src = URL.createObjectURL(jpeg);
	}

	function advance() {
		if (shown) URL.revokeObjectURL(shown);
		shown = src;
		if (next) src = URL.createObjectURL(next);
		next = null;
	}

	function fresh() {
		lastFrameAt = performance.now();
		stale = false;
	}

	$effect(() => {
		fresh();
		const stop = watchVideo(base, view, show);
		const timer = setInterval(() => (stale = performance.now() - lastFrameAt > STALE_MS), 1000);
		return () => {
			stop();
			clearInterval(timer);
		};
	});

	onDestroy(() => {
		if (shown) URL.revokeObjectURL(shown);
		if (src && src !== shown) URL.revokeObjectURL(src);
	});
</script>

<!-- Back from hidden, the page gets its frames again: not stale meanwhile. -->
<svelte:document onvisibilitychange={fresh} />

<img
	src={src ?? undefined}
	alt={src ? alt : ''}
	class={className}
	{style}
	onload={(event) => {
		advance();
		onframe?.(event.currentTarget as HTMLImageElement);
	}}
	onerror={advance}
/>
