<script lang="ts">
	// A fastener's two identifying facts, at a glance: the head profile as a
	// silhouette, the thread size as a colour. Two M3 screws of different lengths
	// look identical in a product photo, and an M3 next to an M5 nearly so — this
	// is the cue that says "look closer, this one is different".
	import { SIZE_COLORS, type Hardware } from '$lib/filament';

	let { hw, size = 18 }: { hw: Hardware; size?: number } = $props();

	// Side-on silhouettes in a 24x24 box, shank pointing down. Each is drawn to
	// the same shank so the heads are what differ.
	const SHANK = 'M10.5 9 h3 v13 h-3 z';
	const PROFILES: Record<string, string> = {
		// countersunk: a cone that sinks flush
		countersunk: 'M4 3 h16 v2.2 l-6.5 5.3 h-3 L4 5.2 z',
		// socket cap: tall straight cylinder
		socket: 'M7.5 3 h9 v7 h-9 z',
		// button: low dome
		button: 'M5 10 a7.6 7.6 0 0 1 14 0 z',
		// flat/pancake: wide, thin, flanged
		flat: 'M4 4.5 h16 v4 h-16 z',
		// hex nut, face on — no shank
		nut: 'M12 3 L20.4 7.8 v9.4 L12 22 L3.6 17.2 V7.8 z',
		// heat-set insert: knurled barrel
		'heat-insert': 'M6.5 4 h11 v16 h-11 z',
		// T-nut for extrusion
		't-nut': 'M4 5 h16 v5 h-5.5 v9 h-5 v-9 H4 z'
	};
	const HOLLOW = new Set(['nut', 'heat-insert', 't-nut']);

	const kind = $derived(
		hw.cots?.type === 'screw' ? (hw.cots?.variant ?? '') : (hw.cots?.type ?? '')
	);
	const profile = $derived(PROFILES[kind]);
	const color = $derived(hw.cots?.size ? SIZE_COLORS[hw.cots.size] : undefined);
	const label = $derived([hw.cots?.size, kind.replace('-', ' ')].filter(Boolean).join(' '));
</script>

{#if profile && color}
	<svg
		width={size}
		height={size}
		viewBox="0 0 24 24"
		fill={color}
		role="img"
		aria-label={label}
		class="shrink-0"
	>
		<title>{label}</title>
		<path d={profile} />
		{#if !HOLLOW.has(kind)}<path d={SHANK} />{/if}
		<!-- the drive recess / bore, punched back out in the page background -->
		{#if kind === 'nut'}
			<circle cx="12" cy="12.5" r="3.6" fill="var(--color-surface)" />
		{:else if kind === 'heat-insert'}
			<rect x="9.5" y="4" width="5" height="16" fill="var(--color-surface)" />
		{:else if kind !== 't-nut'}
			<circle cx="12" cy={kind === 'countersunk' ? 5.4 : kind === 'flat' ? 6.5 : 6.6} r="1.9"
				fill="var(--color-surface)" />
		{/if}
	</svg>
{/if}
