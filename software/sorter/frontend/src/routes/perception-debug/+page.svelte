<script lang="ts">
	import { getBackendHttpBase, machineHttpBaseUrlFromWsUrl } from '$lib/backend';
	import AppShell from '$lib/components/AppShell.svelte';
	import Button from '$lib/components/ui/Button.svelte';
	import MediaTile from '$lib/components/ui/MediaTile.svelte';
	import PageHeader from '$lib/components/ui/PageHeader.svelte';
	import Panel from '$lib/components/ui/Panel.svelte';
	import SegmentedControl from '$lib/components/ui/SegmentedControl.svelte';
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
	<title>Perception debug - Sorter</title>
</svelte:head>

<AppShell>
	<div class="mx-auto flex w-full max-w-[1600px] flex-col gap-(--gap-panels) px-4 py-6 sm:px-6">
		<PageHeader title="Perception debug" description="Annotated frames from perception, one per channel." />

		<Panel>
			<div class="flex flex-col gap-4">
				<div class="flex flex-wrap items-center gap-2">
					<SegmentedControl
						label="Which inference to view"
						value={mode}
						options={[
							{ value: 'cropped', label: 'Cropped (production)' },
							{ value: 'fullframe', label: 'Full frame (debug)' }
						]}
						onchange={setMode}
					/>
					<Button variant="primary" onclick={refresh}>Refresh</Button>
				</div>
				{#if mode === 'cropped'}
					<p class="max-w-4xl text-sm text-ink-muted">
						Exactly what perception infers and decides on. Green boxes are detections the mask filter kept;
						they drive the machine. Orange boxes are raw model detections the filter rejected. Cyan is the
						channel polygon mask, the white rectangle is the crop the model actually saw, and the magenta dot
						is the rotation center. Runtime zones are overlaid from the active channel zones: blue is drop,
						red is exit only, and magenta fill is precise. The panel also shows the live slot state those
						pipelines are consuming.
					</p>
				{:else}
					<p class="max-w-4xl text-sm text-ink-muted">
						The same model run on the whole frame, with no polygon crop, as a second inference per cycle. Use
						it to tell "the crop is excluding pieces" from "the model isn't detecting them". Green boxes are
						full-frame detections whose center lands in the channel mask; orange boxes are outside it. The
						same runtime drop, exit and precise zones are drawn here, so the full-frame comparison still
						lines up with the real machine logic.
					</p>
				{/if}
			</div>
		</Panel>

		<div class="grid grid-cols-1 gap-(--gap-panels) xl:grid-cols-2">
			{#each channels as channel (channel.id)}
				<MediaTile title={channel.label} expandable>
					{#if failed[channel.id]}
						<p class="px-6 text-center text-sm text-ink-muted">
							No frame is available: the worker is not wired, or no inference cycle has run yet.
						</p>
					{:else}
						<img
							class="absolute inset-0 h-full w-full object-contain"
							src={srcFor(channel.id)}
							alt={`Annotated perception frame for ${channel.label}`}
							onerror={() => (failed = { ...failed, [channel.id]: true })}
						/>
					{/if}
				</MediaTile>
			{/each}
		</div>
	</div>
</AppShell>
