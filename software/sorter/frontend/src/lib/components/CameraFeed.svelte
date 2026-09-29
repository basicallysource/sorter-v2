<script lang="ts">
	import { getMachineContext } from '$lib/machines/context';
	import type { DashboardFeedCrop } from '$lib/dashboard/crops';
	import LiveImage from '$lib/components/LiveImage.svelte';
	import StreamControlsOverlay from '$lib/components/StreamControlsOverlay.svelte';
	import WifiOff from '@lucide/svelte/icons/wifi-off';
	import VideoOff from '@lucide/svelte/icons/video-off';
	import Spinner from '$lib/components/ui/Spinner.svelte';
	import type { Snippet } from 'svelte';
	import { roleView } from '$lib/video';

	type ControlKey = 'annotations' | 'crop' | 'fullscreen';

	let {
		camera,
		label = '',
		showHeader = true,
		framed = true,
		crop = null,
		controls = ['annotations'],
		headerActions = null
	}: {
		camera: string;
		label?: string;
		showHeader?: boolean;
		framed?: boolean;
		crop?: DashboardFeedCrop | null;
		controls?: ControlKey[];
		headerActions?: Snippet | null;
	} = $props();

	const ctx = getMachineContext();

	// Persistent per-camera toggle state, kept across reloads in localStorage
	// and keyed by camera, so one camera's crop toggle does not leak into
	// another's.
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

	let annotated = $state(readPersisted('annotated', true));
	// A feed given a crop starts cropped.
	/* svelte-ignore state_referenced_locally */
	let cropped = $state(readPersisted('cropped', crop !== null));

	// Write-back side: every toggle change writes to localStorage.
	$effect(() => {
		writePersisted('annotated', annotated);
	});
	$effect(() => {
		writePersisted('cropped', cropped);
	});

	const showAnnotations = $derived(controls.includes('annotations'));
	const showCrop = $derived(controls.includes('crop'));
	const showFullscreen = $derived(controls.includes('fullscreen'));

	let fullscreenOpen = $state(false);
	let stale = $state(false);

	function handleFullscreenKey(event: KeyboardEvent) {
		if (event.key === 'Escape' && fullscreenOpen) {
			fullscreenOpen = false;
		}
	}

	const configuredSource = $derived(ctx.machine?.camerasConfig?.cameras?.[camera]);
	const hasCameraConfig = $derived(Boolean(ctx.machine?.camerasConfig?.cameras));
	const reportedHealth = $derived(
		ctx.cameraHealth.get(camera) ??
			(hasCameraConfig && configuredSource == null ? 'unassigned' : 'unknown')
	);
	// A camera that reports in but whose frames stopped coming looks like one
	// reconnecting.
	const health = $derived(
		stale && (reportedHealth === 'online' || reportedHealth === 'unknown')
			? 'reconnecting'
			: reportedHealth
	);
	const is_healthy = $derived(health === 'online' || health === 'unknown');
	const is_configured = $derived(health !== 'unassigned');

	const display_label = $derived(label || camera);
</script>

<!-- A camera, drawn like the design system's MediaTile: a strip on the
     surface with its name and controls, then the picture on the media
     backdrop, a dark subtree in both modes. Full screen, the whole feed is
     that dark subtree. -->
<section
	class={fullscreenOpen
		? 'dark fixed inset-0 z-50 flex flex-col bg-media text-ink'
		: `flex h-full min-h-0 flex-col overflow-hidden ${framed ? 'rounded-panel bg-surface' : ''}`}
>
	{#if showHeader}
		<header
			class="flex h-(--size-control-lg) shrink-0 items-center justify-between gap-3 pr-2 pl-(--pad-panel)"
		>
			<h3 class="truncate text-sm font-medium text-ink">{display_label}</h3>
			{#if headerActions}
				<div class="flex shrink-0 items-center gap-1">
					{@render headerActions()}
				</div>
			{/if}
		</header>
	{/if}
	<div class="dark relative min-h-0 flex-1 overflow-hidden bg-media">
		{#if is_configured}
			<LiveImage
				view={roleView(camera, annotated, cropped)}
				alt={display_label}
				class="absolute inset-0 h-full w-full object-contain {is_healthy ? '' : 'opacity-30'}"
				bind:stale
			/>
		{/if}

		{#if !is_healthy}
			<div class="absolute inset-0 flex flex-col items-center justify-center gap-2 text-ink-muted">
				{#if health === 'reconnecting'}
					<Spinner size={24} />
					<span class="text-sm">Reconnecting</span>
				{:else if health === 'offline'}
					<WifiOff size={24} />
					<span class="text-sm">Camera offline</span>
				{:else if health === 'unassigned'}
					<VideoOff size={24} />
					<span class="text-sm">No camera assigned</span>
				{/if}
			</div>
		{/if}

		<StreamControlsOverlay
			bind:annotated
			bind:cropped
			bind:fullscreen={fullscreenOpen}
			{showAnnotations}
			{showCrop}
			{showFullscreen}
		/>

		{#if fullscreenOpen}
			<div
				class="pointer-events-none absolute top-2 left-2 z-20 rounded-badge bg-scrim px-2 py-1 text-sm text-ink-muted"
			>
				Escape or the toggle leaves full screen
			</div>
		{/if}
	</div>
</section>

<svelte:window onkeydown={handleFullscreenKey} />
