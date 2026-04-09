<script lang="ts">
	import { getMachineContext } from '$lib/machines/context';
	import { backendHttpBaseUrl, machineHttpBaseUrlFromWsUrl } from '$lib/backend';
	import type { DashboardFeedCrop } from '$lib/dashboard/crops';
	import { Eye, EyeOff, WifiOff, Loader2, VideoOff } from 'lucide-svelte';

	let {
		camera,
		label = '',
		baseUrl = '',
		showHeader = true,
		framed = true,
		crop = null,
		showOverlay = false,
		layer = $bindable('annotated')
	}: {
		camera: string;
		label?: string;
		baseUrl?: string;
		showHeader?: boolean;
		framed?: boolean;
		crop?: DashboardFeedCrop | null;
		showOverlay?: boolean;
		layer?: 'raw' | 'annotated';
	} = $props();

	const ctx = getMachineContext();

	// Unique per mount so the browser never reuses a stale MJPEG connection
	// when SvelteKit navigates back to a page with camera feeds.
	const mountId = Date.now();

	function effectiveBaseUrl(): string {
		if (baseUrl) return baseUrl;
		return machineHttpBaseUrlFromWsUrl(ctx.machine?.url) ?? backendHttpBaseUrl;
	}

	const annotated = $derived(layer === 'annotated');

	const mjpeg_src = $derived(
		`${effectiveBaseUrl()}/api/cameras/feed/${camera}?layer=${layer}${crop ? '&dashboard=true' : ''}&_=${mountId}`
	);

	const health = $derived(ctx.cameraHealth.get(camera) ?? 'online');
	const is_healthy = $derived(health === 'online');

	const display_label = $derived(label || camera);
</script>

<div class={`flex h-full min-h-0 flex-col overflow-hidden ${framed ? 'setup-card-shell border' : 'setup-card-body'}`}>
	{#if showHeader}
		<div class="setup-card-header flex flex-shrink-0 items-center justify-between px-3 py-2 text-sm">
			<span class="font-medium text-text">{display_label}</span>
			<button
				onclick={() => (layer = layer === 'annotated' ? 'raw' : 'annotated')}
				class="p-1 text-text transition-colors hover:bg-white/70"
				title={annotated ? 'Show raw' : 'Show annotations'}
			>
				{#if annotated}
					<Eye size={14} />
				{:else}
					<EyeOff size={14} />
				{/if}
			</button>
		</div>
	{/if}
	<div class={`relative flex-1 overflow-hidden ${showOverlay ? 'bg-[#04070B]' : 'setup-card-body'}`}>
		<img
			src={mjpeg_src}
			alt={display_label}
			class="absolute inset-0 h-full w-full object-contain"
			class:opacity-30={!is_healthy}
		/>

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

		{#if showOverlay}
			<div class="pointer-events-none absolute inset-x-0 top-0 h-24 bg-gradient-to-b from-black/55 via-black/12 to-transparent"></div>
			<div class="pointer-events-none absolute inset-x-0 bottom-0 h-28 bg-gradient-to-t from-black/72 via-black/14 to-transparent"></div>

			<div class="pointer-events-none absolute inset-x-3 top-3 flex items-start justify-between gap-3">
				<div class="rounded-full border border-white/12 bg-black/55 px-3 py-1 text-[11px] font-semibold tracking-[0.16em] text-white/90 uppercase backdrop-blur-sm">
					{display_label}
				</div>
				<button
					onclick={() => (layer = layer === 'annotated' ? 'raw' : 'annotated')}
					class="pointer-events-auto rounded-full border border-white/12 bg-black/55 p-2 text-white/85 transition-colors hover:bg-black/70"
					title={annotated ? 'Show raw' : 'Show annotations'}
				>
					{#if annotated}
						<Eye size={14} />
					{:else}
						<EyeOff size={14} />
					{/if}
				</button>
			</div>

			<div class="pointer-events-none absolute inset-x-3 bottom-3 flex items-end justify-between gap-3">
				<div class="rounded-full border border-white/12 bg-black/50 px-3 py-1 text-[11px] font-medium text-white/75 backdrop-blur-sm">
					{annotated ? 'Annotated' : 'Raw'} — MJPEG
				</div>
			</div>
		{/if}
	</div>
</div>
