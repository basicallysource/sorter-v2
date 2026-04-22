<script lang="ts">
	import { getMachineContext } from '$lib/machines/context';
	import type { DashboardFeedCrop } from '$lib/dashboard/crops';
	import StreamControlsOverlay from '$lib/components/StreamControlsOverlay.svelte';
	import { WifiOff, Loader2, VideoOff } from 'lucide-svelte';

	type ControlKey = 'annotations' | 'color' | 'crop' | 'zones' | 'ghosts' | 'fullscreen';

	let {
		camera,
		label = '',
		showHeader = true,
		framed = true,
		crop = null,
		showOverlay = false,
		defaultAnnotated = true,
		defaultColorCorrect = true,
		defaultCropped = undefined,
		defaultZones = true,
		controls = ['annotations'],
		layer = $bindable('annotated')
	}: {
		camera: string;
		label?: string;
		showHeader?: boolean;
		framed?: boolean;
		crop?: DashboardFeedCrop | null;
		showOverlay?: boolean;
		defaultAnnotated?: boolean;
		defaultColorCorrect?: boolean;
		defaultCropped?: boolean;
		defaultZones?: boolean;
		controls?: ControlKey[];
		layer?: 'raw' | 'annotated';
	} = $props();

	const ctx = getMachineContext();

	// Persistent per-camera toggle state — survives reloads via localStorage.
	// Keyed by camera so e.g. c_channel_2's crop toggle doesn't leak into
	// the carousel's. Falls back to the ``default*`` props when no saved
	// value exists.
	const storageKey = (key: string) => `camera-feed:${camera}:${key}`;

	function readPersisted(key: string, fallback: boolean): boolean {
		if (typeof localStorage === 'undefined') return fallback;
		try {
			const raw = localStorage.getItem(storageKey(key));
			if (raw === null) return fallback;
			return raw === '1' || raw === 'true';
		} catch {
			return fallback;
		}
	}

	function writePersisted(key: string, value: boolean) {
		if (typeof localStorage === 'undefined') return;
		try {
			localStorage.setItem(storageKey(key), value ? '1' : '0');
		} catch {
			// Quota / private mode — silently ignore.
		}
	}

	/* svelte-ignore state_referenced_locally */
	let annotated = $state(readPersisted('annotated', defaultAnnotated && layer === 'annotated'));
	/* svelte-ignore state_referenced_locally */
	let colorCorrect = $state(readPersisted('colorCorrect', defaultColorCorrect));
	// Legacy: presence of `crop` prop defaulted cropping on. Honor that unless
	// the caller explicitly sets `defaultCropped`.
	/* svelte-ignore state_referenced_locally */
	let cropped = $state(readPersisted('cropped', defaultCropped ?? crop !== null));
	/* svelte-ignore state_referenced_locally */
	let zones = $state(readPersisted('zones', defaultZones));
	/* svelte-ignore state_referenced_locally */
	let ghosts = $state(readPersisted('ghosts', false));

	// Keep legacy `layer` prop synced with new `annotated` state so existing
	// consumers (e.g. dashboard) binding to `layer` keep working.
	$effect(() => {
		layer = annotated ? 'annotated' : 'raw';
	});
	$effect(() => {
		annotated = layer === 'annotated';
	});

	// Write-back side: every toggle change writes to localStorage.
	$effect(() => { writePersisted('annotated', annotated); });
	$effect(() => { writePersisted('colorCorrect', colorCorrect); });
	$effect(() => { writePersisted('cropped', cropped); });
	$effect(() => { writePersisted('zones', zones); });
	$effect(() => { writePersisted('ghosts', ghosts); });

	const showAnnotations = $derived(controls.includes('annotations'));
	const showColor = $derived(controls.includes('color'));
	const showCrop = $derived(controls.includes('crop'));
	const showZones = $derived(controls.includes('zones'));
	const showGhosts = $derived(controls.includes('ghosts'));
	const showFullscreen = $derived(controls.includes('fullscreen'));

	let fullscreenOpen = $state(false);

	function handleFullscreenKey(event: KeyboardEvent) {
		if (event.key === 'Escape' && fullscreenOpen) {
			fullscreenOpen = false;
		}
	}

	// WS source reads the latest FrameData from the machine context and emits a
	// data:image URL. One shared WS connection feeds all cameras → no per-camera
	// HTTP slot is consumed, so the 6-connection-per-origin browser limit stops
	// biting when four CameraFeeds render side-by-side on the dashboard.
	const ws_frame = $derived(ctx.machine?.frames.get(camera as any));
	const ws_src = $derived.by(() => {
		const frame = ws_frame;
		if (!frame) return '';
		const payload = annotated && frame.annotated ? frame.annotated : frame.raw;
		return payload ? `data:image/jpeg;base64,${payload}` : '';
	});

	const health = $derived(ctx.cameraHealth.get(camera) ?? 'online');
	const is_healthy = $derived(health === 'online');

	const display_label = $derived(label || camera);
</script>

<div
	class={`flex h-full min-h-0 flex-col overflow-hidden ${
		fullscreenOpen
			? 'fixed inset-0 z-50 !h-screen !w-screen bg-black p-4'
			: framed
				? 'setup-card-shell border'
				: 'setup-card-body'
	}`}
>
	{#if showHeader}
		<div class="setup-card-header flex flex-shrink-0 items-center justify-between px-3 py-2 text-sm">
			<span class="font-medium text-text">{display_label}</span>
		</div>
	{/if}
	<div class={`relative flex-1 overflow-hidden ${showOverlay ? 'bg-[#04070B]' : 'setup-card-body'}`}>
		{#if cropped && crop}
			{@const box = crop.viewBox}
			{@const rc = crop.rotationCenter ?? [box.x + box.width / 2, box.y + box.height / 2]}
			{@const rot = crop.rotationDeg ?? 0}
			<svg
				viewBox="{box.x} {box.y} {box.width} {box.height}"
				preserveAspectRatio="xMidYMid meet"
				class="absolute inset-0 h-full w-full"
				class:opacity-30={!is_healthy}
				aria-label={display_label}
			>
				<g transform="rotate({rot} {rc[0]} {rc[1]})">
					<image
						href={ws_src}
						x="0"
						y="0"
						width={crop.sourceWidth}
						height={crop.sourceHeight}
						preserveAspectRatio="none"
					/>
				</g>
			</svg>
		{:else}
			<img
				src={ws_src}
				alt={display_label}
				class="absolute inset-0 h-full w-full object-contain"
				class:opacity-30={!is_healthy}
			/>
		{/if}

		{#if !is_healthy}
			<div class="absolute inset-0 flex items-center justify-center">
				<div class="flex flex-col items-center gap-2 text-center">
					{#if health === 'reconnecting'}
						<Loader2 size={28} class="animate-spin text-text-muted" />
						<span class="text-sm font-medium text-text-muted">Reconnecting...</span>
					{:else if health === 'offline'}
						<WifiOff size={28} class="text-text-muted" />
						<span class="text-sm font-medium text-text-muted">Camera Offline</span>
					{:else if health === 'unassigned'}
						<VideoOff size={28} class="text-text-muted" />
						<span class="text-sm font-medium text-text-muted">No Camera Assigned</span>
					{/if}
				</div>
			</div>
		{/if}

		<StreamControlsOverlay
			bind:annotated
			bind:colorCorrect
			bind:cropped
			bind:zones
			bind:ghosts
			bind:fullscreen={fullscreenOpen}
			{showAnnotations}
			{showColor}
			{showCrop}
			{showZones}
			{showGhosts}
			{showFullscreen}
		/>

		{#if showOverlay}
			<div class="pointer-events-none absolute inset-x-0 top-0 h-24 bg-gradient-to-b from-black/55 via-black/12 to-transparent"></div>
			<div class="pointer-events-none absolute inset-x-0 bottom-0 h-28 bg-gradient-to-t from-black/72 via-black/14 to-transparent"></div>

			<div class="pointer-events-none absolute inset-x-3 top-3 flex items-start justify-between gap-3">
				<div class="rounded-full border border-white/12 bg-black/55 px-3 py-1 text-xs font-semibold tracking-[0.16em] text-white/90 uppercase backdrop-blur-sm">
					{display_label}
				</div>
			</div>

			<div class="pointer-events-none absolute inset-x-3 bottom-3 flex items-end justify-between gap-3">
				<div class="rounded-full border border-white/12 bg-black/50 px-3 py-1 text-xs font-medium text-white/75 backdrop-blur-sm">
					{annotated ? 'Annotated' : 'Raw'}
				</div>
			</div>
		{/if}

		{#if fullscreenOpen}
			<div class="pointer-events-none absolute left-3 top-3 z-20 border border-white/20 bg-black/55 px-2 py-0.5 text-xs text-white/80 shadow-md backdrop-blur-sm">
				Esc or toggle to exit
			</div>
		{/if}
	</div>
</div>

<svelte:window onkeydown={handleFullscreenKey} />
