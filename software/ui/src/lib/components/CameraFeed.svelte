<script lang="ts">
	import { getMachineContext } from '$lib/machines/context';
	import { backendHttpBaseUrl, machineHttpBaseUrlFromWsUrl } from '$lib/backend';
	import type { DashboardFeedCrop } from '$lib/dashboard/crops';
	import { Eye, EyeOff } from 'lucide-svelte';

	let {
		camera,
		label = '',
		baseUrl = '',
		showHeader = true,
		framed = true,
		crop = null,
		showOverlay = false,
		annotated = $bindable(true)
	}: {
		camera: string;
		label?: string;
		baseUrl?: string;
		showHeader?: boolean;
		framed?: boolean;
		crop?: DashboardFeedCrop | null;
		showOverlay?: boolean;
		annotated?: boolean;
	} = $props();

	const MJPEG_ROLES = [
		'c_channel_2',
		'c_channel_3',
		'carousel',
		'classification_top',
		'classification_bottom'
	];

	const ctx = getMachineContext();

	function effectiveBaseUrl(): string {
		if (baseUrl) return baseUrl;
		return machineHttpBaseUrlFromWsUrl(ctx.machine?.url) ?? backendHttpBaseUrl;
	}

	const frame = $derived(ctx.frames.get(camera as never));
	const image_src = $derived.by(() => {
		if (!frame) return null;
		const data = annotated && frame.annotated ? frame.annotated : frame.raw;
		return `data:image/jpeg;base64,${data}`;
	});

	const mjpeg_src = $derived(
		MJPEG_ROLES.includes(camera)
			? `${effectiveBaseUrl()}/api/cameras/feed/${camera}`
			: null
	);
	const dashboard_src = $derived(
		crop
			? `${effectiveBaseUrl()}/api/cameras/feed/${camera}?dashboard=true&annotated=${annotated ? 'true' : 'false'}`
			: null
	);
	const active_src = $derived(dashboard_src ?? image_src ?? mjpeg_src);

	const display_label = $derived(label || camera);
	const crop_view_box = $derived(
		crop
			? `${crop.viewBox.x} ${crop.viewBox.y} ${crop.viewBox.width} ${crop.viewBox.height}`
			: null
	);
	const can_crop_render = $derived(Boolean(crop && image_src && crop_view_box && !dashboard_src));
</script>

	<div class={`flex h-full min-h-0 flex-col overflow-hidden ${framed ? 'setup-card-shell border' : 'setup-card-body'}`}>
	{#if showHeader}
		<div class="setup-card-header flex flex-shrink-0 items-center justify-between px-3 py-2 text-sm">
			<span class="font-medium text-text">{display_label}</span>
			{#if frame || crop}
				<button
					onclick={() => (annotated = !annotated)}
					class="p-1 text-text transition-colors hover:bg-white/70"
					title={annotated ? 'Show raw' : 'Show annotations'}
				>
					{#if annotated}
						<Eye size={14} />
					{:else}
						<EyeOff size={14} />
					{/if}
				</button>
			{/if}
		</div>
	{/if}
	<div class={`relative flex-1 overflow-hidden ${showOverlay ? 'bg-[#04070B]' : 'setup-card-body'}`}>
		{#if active_src}
			{#if can_crop_render && crop && crop_view_box}
				<svg
					class="absolute inset-0 h-full w-full"
					viewBox={crop_view_box}
					preserveAspectRatio="xMidYMid meet"
					role="img"
					aria-label={display_label}
				>
					<image
						href={active_src ?? undefined}
						x="0"
						y="0"
					width={crop.sourceWidth}
					height={crop.sourceHeight}
					preserveAspectRatio="none"
				/>
				</svg>
			{:else}
				<img
					src={active_src ?? undefined}
					alt={display_label}
					class="absolute inset-0 h-full w-full object-contain"
				/>
			{/if}

			{#if showOverlay}
				<div class="pointer-events-none absolute inset-x-0 top-0 h-24 bg-gradient-to-b from-black/55 via-black/12 to-transparent"></div>
				<div class="pointer-events-none absolute inset-x-0 bottom-0 h-28 bg-gradient-to-t from-black/72 via-black/14 to-transparent"></div>
			{/if}
		{:else}
			<div
				class={`flex h-full items-center justify-center text-center ${showOverlay ? 'bg-[#04070B] text-white/55' : 'text-text-muted'}`}
			>
				<div class="px-6">
					<div class="text-sm font-medium">No live frame</div>
					<div class="mt-1 text-xs opacity-70">The camera is connected, but no preview is available yet.</div>
				</div>
			</div>
		{/if}

		{#if showOverlay}
			<div class="pointer-events-none absolute inset-x-3 top-3 flex items-start justify-between gap-3">
				<div class="rounded-full border border-white/12 bg-black/55 px-3 py-1 text-[11px] font-semibold tracking-[0.16em] text-white/90 uppercase backdrop-blur-sm">
					{display_label}
				</div>
				{#if frame}
					<button
						onclick={() => (annotated = !annotated)}
						class="pointer-events-auto rounded-full border border-white/12 bg-black/55 p-2 text-white/85 transition-colors hover:bg-black/70"
						title={annotated ? 'Show raw' : 'Show annotations'}
					>
						{#if annotated}
							<Eye size={14} />
						{:else}
							<EyeOff size={14} />
						{/if}
					</button>
				{/if}
			</div>

			<div class="pointer-events-none absolute inset-x-3 bottom-3 flex items-end justify-between gap-3">
				<div class="rounded-full border border-white/12 bg-black/50 px-3 py-1 text-[11px] font-medium text-white/75 backdrop-blur-sm">
					{frame ? (annotated ? 'Annotated live view' : 'Raw live view') : 'Live MJPEG feed'}
				</div>
			</div>
		{/if}
	</div>
</div>
