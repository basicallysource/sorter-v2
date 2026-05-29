<script lang="ts">
	import { getBackendHttpBase, machineHttpBaseUrlFromWsUrl } from '$lib/backend';
	import AppHeader from '$lib/components/AppHeader.svelte';
	import { Button } from '$lib/components/primitives';
	import { getMachinesContext } from '$lib/machines/context';

	const manager = getMachinesContext();

	const channels = [
		{ id: 2, label: 'C-channel 2 (c_channel_2)' },
		{ id: 3, label: 'C-channel 3 (c_channel_3)' },
		{ id: 4, label: 'Carousel / classification (channel 4)' }
	];

	function baseUrl(): string {
		return (
			machineHttpBaseUrlFromWsUrl(
				manager.selectedMachine?.status === 'connected' ? manager.selectedMachine.url : null
			) ?? getBackendHttpBase()
		);
	}

	// Cache-busting token. Bumped on mount (so a browser refresh always pulls the
	// current frame) and by the Refresh button (on-demand re-fetch, no reload).
	let token = $state(Date.now());
	let base = $derived(baseUrl());
	let failed = $state<Record<number, boolean>>({});

	// Which inference to view per channel:
	//  - 'cropped'   : production — model runs on the polygon-bounding-rect crop.
	//  - 'fullframe' : debug — same model on the whole frame (a 2nd inference per
	//                  cycle, enabled on demand on the backend, self-expiring).
	let mode = $state<'cropped' | 'fullframe'>('cropped');
	const endpoint = $derived(mode === 'fullframe' ? 'fullframe' : 'annotated');

	// In full-frame mode the first fetch can 425 ("warming up") for one cycle
	// while the worker produces the first uncropped result; auto-refresh shortly
	// after so the image appears without the user clicking.
	let timer: ReturnType<typeof setTimeout> | undefined;
	function srcFor(id: number): string {
		return `${base}/api/perception/debug/${endpoint}/${id}?t=${token}`;
	}

	function refresh(): void {
		failed = {};
		token = Date.now();
	}

	function setMode(next: 'cropped' | 'fullframe'): void {
		mode = next;
		refresh();
		clearTimeout(timer);
		if (next === 'fullframe') {
			// Pull again after the worker has had a cycle to run the full-frame pass.
			timer = setTimeout(refresh, 800);
		}
	}
</script>

<svelte:head>
	<title>Perception debug</title>
</svelte:head>

<AppHeader />

<div class="mx-auto w-full max-w-[1600px] px-4 py-6">
	<div class="mb-4 flex items-center justify-between gap-4">
		<div>
			<h1 class="text-lg font-semibold">Perception debug — annotated frames</h1>
			{#if mode === 'cropped'}
				<p class="text-sm text-neutral-500">
					<span class="font-semibold">Cropped (production)</span> — exactly what perception infers
					and decides on. <span class="text-success-dark">Green</span> = detections the mask filter
					kept (these drive the machine); <span style="color:#cc7a00">orange</span> = raw model
					detections the filter rejected; cyan = channel polygon mask; white rect = the crop region
					the model actually saw; magenta dot = rotation center. Runtime zones are overlaid from the
					actual `ChannelDef` section sets the go-to-angle feeder and rev01 classification state machine
					read: blue = drop, red = exit-only, magenta fill = precise. The panel also shows the live
					slot state those pipelines are consuming.
				</p>
			{:else}
				<p class="text-sm text-neutral-500">
					<span class="font-semibold">Full-frame (debug)</span> — the same model run on the WHOLE
					frame, no polygon crop, as a second inference per cycle. Use it to tell "the crop is
					excluding pieces" from "the model isn't detecting them."
					<span class="text-success-dark">Green</span> = full-frame detections whose center lands in
					the channel mask; <span style="color:#cc7a00">orange</span> = outside it. The same runtime
					drop / exit / precise zones are rendered here too so the full-frame comparison still lines
					up with the real machine logic.
				</p>
			{/if}
		</div>
		<div class="flex items-center gap-2">
			<div class="flex border border-neutral-400/40">
				<button
					class="px-3 py-1.5 text-sm {mode === 'cropped'
						? 'bg-primary text-white'
						: 'text-neutral-500'}"
					onclick={() => setMode('cropped')}>Cropped (production)</button
				>
				<button
					class="px-3 py-1.5 text-sm {mode === 'fullframe'
						? 'bg-primary text-white'
						: 'text-neutral-500'}"
					onclick={() => setMode('fullframe')}>Full-frame (debug)</button
				>
			</div>
			<Button variant="primary" size="md" onclick={refresh}>Refresh</Button>
		</div>
	</div>

	<div class="grid grid-cols-1 gap-6 xl:grid-cols-2">
		{#each channels as channel (channel.id)}
			<div class="flex flex-col gap-2">
				<div class="text-xs font-semibold uppercase tracking-wider text-neutral-500">
					{channel.label}
				</div>
				{#if failed[channel.id]}
					<div
						class="flex h-48 items-center justify-center border border-neutral-400/40 bg-neutral-500/[0.06] text-sm text-neutral-500"
					>
						No frame available (worker not wired or no inference cycle yet).
					</div>
				{:else}
					<img
						class="w-full border border-neutral-400/40 bg-black"
						src={srcFor(channel.id)}
						alt={`Annotated perception frame for ${channel.label}`}
						onerror={() => (failed = { ...failed, [channel.id]: true })}
					/>
				{/if}
			</div>
		{/each}
	</div>
</div>
