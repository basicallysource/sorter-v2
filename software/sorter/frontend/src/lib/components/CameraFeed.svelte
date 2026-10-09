<script lang="ts">
	import { getMachineContext } from '$lib/machines/context';
	import CameraPicture from '$lib/components/CameraPicture.svelte';
	import StreamControlsOverlay from '$lib/components/StreamControlsOverlay.svelte';
	import WifiOff from '@lucide/svelte/icons/wifi-off';
	import VideoOff from '@lucide/svelte/icons/video-off';
	import MediaTile from '$lib/components/ui/MediaTile.svelte';
	import Spinner from '$lib/components/ui/Spinner.svelte';
	import type { Snippet } from 'svelte';
	import { roleView } from '$lib/video';

	type ControlKey = 'annotations' | 'crop' | 'fullscreen';

	let {
		camera,
		label = '',
		header = true,
		controls = ['annotations'],
		actions,
		class: className = ''
	}: {
		camera: string;
		label?: string;
		// False for a picture that is the whole tile (MediaTile's `header`).
		header?: boolean;
		controls?: ControlKey[];
		actions?: Snippet;
		class?: string;
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
	// A feed that can be cropped starts cropped; one whose camera has no zone
	// shows the whole frame either way.
	/* svelte-ignore state_referenced_locally */
	let cropped = $state(readPersisted('cropped', controls.includes('crop')));
	// The size of what the picture shows, which the tile takes the shape of.
	let shape = $state<{ width: number; height: number } | null>(null);

	// Write-back side: every toggle change writes to localStorage.
	$effect(() => {
		writePersisted('annotated', annotated);
	});
	$effect(() => {
		writePersisted('cropped', cropped);
	});

	let stale = $state(false);

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

<!-- A camera as the design system's MediaTile, whose full screen it uses. -->
<MediaTile
	title={display_label}
	{header}
	{actions}
	class={className}
	expandable={controls.includes('fullscreen')}
	aspect={shape ? `${shape.width} / ${shape.height}` : '16 / 9'}
>
	{#if is_configured}
		<CameraPicture
			view={roleView(camera)}
			boxes={annotated}
			zones={annotated}
			{cropped}
			alt={display_label}
			class="absolute inset-0 h-full w-full {is_healthy ? '' : 'opacity-30'}"
			bind:stale
			bind:shape
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
	{#snippet overlay()}
		<StreamControlsOverlay
			bind:annotated
			bind:cropped
			showAnnotations={controls.includes('annotations')}
			showCrop={controls.includes('crop')}
		/>
	{/snippet}
</MediaTile>
