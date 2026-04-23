<script lang="ts">
	import { getMachineContext } from '$lib/machines/context';
	import { page } from '$app/state';
	import type { DashboardFeedCrop } from '$lib/dashboard/crops';
	import StreamControlsOverlay from '$lib/components/StreamControlsOverlay.svelte';
	import { persistentToggle } from '$lib/preferences/persistent-toggle.svelte';
	import { WifiOff, Loader2, VideoOff } from 'lucide-svelte';

	type ControlKey = 'annotations' | 'color' | 'crop' | 'zones' | 'ghosts' | 'slots' | 'fullscreen';

	type StateBadge = { label: string; tone: string };

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
		layer = $bindable('annotated'),
		stateBadge = null
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
		stateBadge?: StateBadge | null;
	} = $props();

	const ctx = getMachineContext();

	// Persistent per-camera toggle state — survives reloads via localStorage.
	// Keyed by (route, camera, toggle) so e.g. the dashboard's crop state
	// doesn't leak into setup's, and c_channel_2's doesn't leak into the
	// carousel's. Falls back to the ``default*`` props when no saved value
	// exists. The ``persistentToggle`` helper rehydrates whenever the key
	// changes, which covers the dashboard's aux camera flipping from
	// "carousel" to "classification_channel" as the machine config loads.
	const routeScope = $derived(page.route?.id ?? page.url?.pathname ?? '_');
	const slotKey = (toggle: string) => `camera-feed:${routeScope}:${camera}:${toggle}`;

	const annotated = persistentToggle({
		key: () => slotKey('annotated'),
		default: () => defaultAnnotated && layer === 'annotated'
	});
	const colorCorrect = persistentToggle({
		key: () => slotKey('colorCorrect'),
		default: () => defaultColorCorrect
	});
	// Legacy: presence of `crop` prop defaulted cropping on. Honor that unless
	// the caller explicitly sets `defaultCropped`.
	const cropped = persistentToggle({
		key: () => slotKey('cropped'),
		default: () => defaultCropped ?? crop !== null
	});
	const zones = persistentToggle({ key: () => slotKey('zones'), default: () => defaultZones });
	const ghosts = persistentToggle({ key: () => slotKey('ghosts'), default: false });
	const slots = persistentToggle({ key: () => slotKey('slots'), default: false });

	// Keep the legacy `layer` prop synced with the `annotated` toggle so
	// existing consumers (e.g. dashboard) binding to `layer` keep working.
	$effect(() => {
		layer = annotated.value ? 'annotated' : 'raw';
	});
	$effect(() => {
		annotated.value = layer === 'annotated';
	});

	const showAnnotations = $derived(controls.includes('annotations'));
	const showColor = $derived(controls.includes('color'));
	const showCrop = $derived(controls.includes('crop'));
	const showZones = $derived(controls.includes('zones'));
	const showGhosts = $derived(controls.includes('ghosts'));
	const showSlots = $derived(controls.includes('slots'));
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
		const payload = annotated.value && frame.annotated ? frame.annotated : frame.raw;
		return payload ? `data:image/jpeg;base64,${payload}` : '';
	});

	const health = $derived(ctx.cameraHealth.get(camera) ?? 'online');
	const is_healthy = $derived(health === 'online');

	const display_label = $derived(label || camera);

	// Unique id so multiple CameraFeed instances (e.g. 4 on the dashboard)
	// don't collide on their SVG clipPath element.
	const instanceId = Math.random().toString(36).slice(2, 10);

	// SVG path for an annulus-sector wedge. Used by the slots overlay to
	// visualise where the runtime has angular reservations (C4 dossier
	// zones, C2/C3 confirmed-real piece positions) on the live stream.
	function wedgePath(
		cx: number,
		cy: number,
		rInner: number,
		rOuter: number,
		startDeg: number,
		endDeg: number
	): string {
		const raw = ((endDeg - startDeg) % 360 + 360) % 360;
		const span = raw === 0 ? 360 : raw;
		const sr = (startDeg * Math.PI) / 180;
		const er = ((startDeg + span) * Math.PI) / 180;
		const sxInner = cx + rInner * Math.cos(sr);
		const syInner = cy + rInner * Math.sin(sr);
		const sxOuter = cx + rOuter * Math.cos(sr);
		const syOuter = cy + rOuter * Math.sin(sr);
		const exInner = cx + rInner * Math.cos(er);
		const eyInner = cy + rInner * Math.sin(er);
		const exOuter = cx + rOuter * Math.cos(er);
		const eyOuter = cy + rOuter * Math.sin(er);
		const largeArc = span > 180 ? 1 : 0;
		return [
			`M ${sxInner} ${syInner}`,
			`L ${sxOuter} ${syOuter}`,
			`A ${rOuter} ${rOuter} 0 ${largeArc} 1 ${exOuter} ${eyOuter}`,
			`L ${exInner} ${eyInner}`,
			`A ${rInner} ${rInner} 0 ${largeArc} 0 ${sxInner} ${syInner}`,
			'Z'
		].join(' ');
	}
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
			{#if stateBadge}
				{@const toneClass =
					stateBadge.tone === 'green'
						? 'bg-emerald-500/15 text-emerald-500 border-emerald-500/30'
						: stateBadge.tone === 'amber'
							? 'bg-amber-500/15 text-amber-500 border-amber-500/30'
							: stateBadge.tone === 'red'
								? 'bg-rose-500/15 text-rose-500 border-rose-500/30'
								: stateBadge.tone === 'blue'
									? 'bg-sky-500/15 text-sky-500 border-sky-500/30'
									: 'bg-text-muted/10 text-text-muted border-text-muted/20'}
				<span
					class="rounded-full border px-2 py-0.5 text-xs font-medium uppercase tracking-wide {toneClass}"
				>
					{stateBadge.label}
				</span>
			{/if}
		</div>
	{/if}
	<div class={`relative flex-1 overflow-hidden ${showOverlay ? 'bg-[#04070B]' : 'setup-card-body'}`}>
		{#if cropped.value && crop}
			{@const box = crop.viewBox}
			{@const rc = crop.rotationCenter ?? [box.x + box.width / 2, box.y + box.height / 2]}
			{@const rot = crop.rotationDeg ?? 0}
			{@const clipId = `camera-feed-clip-${instanceId}`}
			<svg
				viewBox="{box.x} {box.y} {box.width} {box.height}"
				preserveAspectRatio="xMidYMid meet"
				class="absolute inset-0 h-full w-full"
				class:opacity-30={!is_healthy}
				aria-label={display_label}
			>
				<defs>
					<clipPath id={clipId} clipPathUnits="userSpaceOnUse">
						{#each crop.polygons as polygon}
							<polygon points={polygon.map((p) => `${p[0]},${p[1]}`).join(' ')} />
						{/each}
					</clipPath>
				</defs>
				<g clip-path={`url(#${clipId})`}>
					<g transform="rotate({rot} {rc[0]} {rc[1]})">
						<image
							href={ws_src}
							x="0"
							y="0"
							width={crop.sourceWidth}
							height={crop.sourceHeight}
							preserveAspectRatio="none"
						/>
						{#if ghosts.value && ws_frame?.ghost_boxes}
							{#each ws_frame.ghost_boxes as gb}
								<rect
									x={gb[0]}
									y={gb[1]}
									width={gb[2] - gb[0]}
									height={gb[3] - gb[1]}
									fill="none"
									stroke="#ffffff"
									stroke-width="3"
									vector-effect="non-scaling-stroke"
								/>
							{/each}
						{/if}
						{#if slots.value && ws_frame?.ring_geom && ws_frame?.slot_wedges}
							{@const rg = ws_frame.ring_geom}
							{#each ws_frame.slot_wedges as wedge}
								<path
									d={wedgePath(
										rg.center_x,
										rg.center_y,
										rg.inner_radius,
										rg.outer_radius,
										wedge.start_angle_deg,
										wedge.end_angle_deg
									)}
									fill={wedge.color ?? 'rgba(99,204,255,0.28)'}
									stroke={wedge.color ?? '#63ccff'}
									stroke-width="2"
									vector-effect="non-scaling-stroke"
								/>
							{/each}
						{/if}
					</g>
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
			bind:annotated={annotated.value}
			bind:colorCorrect={colorCorrect.value}
			bind:cropped={cropped.value}
			bind:zones={zones.value}
			bind:ghosts={ghosts.value}
			bind:slots={slots.value}
			bind:fullscreen={fullscreenOpen}
			{showAnnotations}
			{showColor}
			{showCrop}
			{showZones}
			{showGhosts}
			{showSlots}
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
					{annotated.value ? 'Annotated' : 'Raw'}
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
