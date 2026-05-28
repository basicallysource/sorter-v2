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

	function srcFor(id: number): string {
		return `${base}/api/perception/debug/annotated/${id}?t=${token}`;
	}

	function refresh(): void {
		failed = {};
		token = Date.now();
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
			<p class="text-sm text-neutral-500">
				The exact cached frame each perception worker last inferred against.
				<span class="text-success-dark">Green</span> = detections the mask filter kept (these drive
				the machine); <span style="color:#cc7a00">orange</span> = raw model detections the filter
				rejected; cyan = channel polygon mask; white rect = the crop region the model actually saw;
				magenta dot = rotation center. The panel stamps the camera, resolution, and the exact model
				that produced these. Refresh to pull the current frame.
			</p>
		</div>
		<Button variant="primary" size="md" onclick={refresh}>Refresh</Button>
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
