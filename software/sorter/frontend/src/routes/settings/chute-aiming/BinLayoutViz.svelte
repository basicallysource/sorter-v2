<script lang="ts">
	import { binCenterAngle, reachInfo, type ChuteGeometry } from './geometry';

	type Selected = { section: number; bin: number; binCount: number };

	let {
		numSections,
		sectionWidthDeg,
		firstSectionOffsetDeg,
		maxAngleDeg,
		binCount,
		liveAngleDeg = null,
		selected = null,
		onSelect
	}: {
		numSections: number;
		sectionWidthDeg: number;
		firstSectionOffsetDeg: number;
		maxAngleDeg: number;
		binCount: number;
		liveAngleDeg?: number | null;
		selected?: Selected | null;
		onSelect?: (sel: Selected) => void;
	} = $props();

	const geo = $derived<ChuteGeometry>({ numSections, sectionWidthDeg, firstSectionOffsetDeg });
	const sectionPitchDeg = $derived(360 / Math.max(1, numSections));

	const CX = 110;
	const CY = 110;
	const R = 78;
	function polar(angleDeg: number, radius = R) {
		const rad = ((angleDeg - 90) * Math.PI) / 180;
		return { x: CX + radius * Math.cos(rad), y: CY + radius * Math.sin(rad) };
	}

	function annularWedge(startDeg: number, endDeg: number, rInner: number, rOuter: number): string {
		const a1 = polar(startDeg, rOuter);
		const a2 = polar(endDeg, rOuter);
		const b2 = polar(endDeg, rInner);
		const b1 = polar(startDeg, rInner);
		const large = endDeg - startDeg > 180 ? 1 : 0;
		return `M ${a1.x} ${a1.y} A ${rOuter} ${rOuter} 0 ${large} 1 ${a2.x} ${a2.y} L ${b2.x} ${b2.y} A ${rInner} ${rInner} 0 ${large} 0 ${b1.x} ${b1.y} Z`;
	}

	const bins = $derived(
		Array.from({ length: numSections }, (_, s) =>
			Array.from({ length: binCount }, (_, i) => {
				const angle = binCenterAngle(geo, s, i, binCount);
				const r = reachInfo(angle, maxAngleDeg);
				return { section: s, bin: i, angle, ...r, ...polar(r.norm) };
			})
		).flat()
	);
	const total = $derived(numSections * binCount);
	const unreachableCount = $derived(bins.filter((b) => !b.reachable).length);

	const deadzonePath = $derived(annularWedge(maxAngleDeg, 360, R - 16, R + 3));
	const needle = $derived(liveAngleDeg === null ? null : polar(((liveAngleDeg % 360) + 360) % 360));
	const maxTick = $derived(polar(maxAngleDeg, R + 8));
	const homeLabel = $derived(polar(0, R + 9));
	const homeRim = $derived(polar(0, R));

	function pick(b: { section: number; bin: number; reachable: boolean }) {
		if (!b.reachable) return;
		onSelect?.({ section: b.section, bin: b.bin, binCount });
	}
</script>

<div class="flex flex-col gap-1 border border-border bg-bg p-3">
	<div class="flex items-baseline justify-between">
		<div class="text-sm font-semibold text-text">{binCount} {binCount === 1 ? 'bin' : 'bins'}/section</div>
		<div class={`text-sm ${unreachableCount === 0 ? 'text-success' : 'text-danger'}`}>
			{#if unreachableCount === 0}
				all {total} reachable
			{:else}
				{unreachableCount}/{total} unreachable
			{/if}
		</div>
	</div>

	<svg viewBox="0 0 220 220" class="w-full" role="img" aria-label={`${binCount}-bin layout`}>
		<circle cx={CX} cy={CY} r={R} class="fill-surface stroke-border" stroke-width="1" />

		<!-- The single mechanical deadzone: the wedge between max travel and home. -->
		<path d={deadzonePath} class="fill-danger" opacity="0.12" />
		<path
			d={`M ${polar(maxAngleDeg, R + 3).x} ${polar(maxAngleDeg, R + 3).y} A ${R + 3} ${R + 3} 0 0 1 ${polar(360, R + 3).x} ${polar(360, R + 3).y}`}
			class="stroke-danger"
			fill="none"
			stroke-width="1.5"
		/>

		<!-- Section boundary ticks. -->
		{#each Array.from({ length: numSections }, (_, s) => firstSectionOffsetDeg + s * sectionPitchDeg) as edge}
			{@const p = polar(edge, R + 5)}
			{@const p0 = polar(edge, R - 4)}
			<line x1={p0.x} y1={p0.y} x2={p.x} y2={p.y} class="stroke-border" stroke-width="0.75" />
		{/each}

		<!-- Home + max markers. -->
		<line x1={CX} y1={CY} x2={homeRim.x} y2={homeRim.y} class="stroke-text-muted" stroke-width="0.5" stroke-dasharray="2 2" />
		<circle cx={homeRim.x} cy={homeRim.y} r="2.5" class="fill-primary" />
		<text x={homeLabel.x} y={homeLabel.y} text-anchor="middle" font-size="10" class="fill-text-muted">home 0°</text>
		<text x={maxTick.x} y={maxTick.y} text-anchor="middle" font-size="10" class="fill-danger">max {maxAngleDeg.toFixed(0)}°</text>

		{#if needle}
			<line x1={CX} y1={CY} x2={needle.x} y2={needle.y} class="stroke-primary" stroke-width="1.5" />
		{/if}

		{#each bins as b}
			{@const isSel = selected?.binCount === binCount && selected?.section === b.section && selected?.bin === b.bin}
			<g>
				<title>
					Section {b.section + 1}, bin {b.bin + 1} → {b.angle.toFixed(1)}°{b.reachable
						? ''
						: ` — UNREACHABLE: ${b.reason}`}
				</title>
				<circle
					cx={b.x}
					cy={b.y}
					r={isSel ? 6 : 4.5}
					class={`${b.reachable ? 'cursor-pointer' : 'cursor-not-allowed'} ${
						!b.reachable
							? 'fill-surface stroke-danger'
							: isSel
								? 'fill-primary stroke-primary'
								: 'fill-bg stroke-text-muted'
					}`}
					stroke-width="1"
					role="button"
					tabindex={b.reachable ? 0 : -1}
					onclick={() => pick(b)}
					onkeydown={(e) => {
						if (e.key === 'Enter' || e.key === ' ') pick(b);
					}}
				/>
				{#if !b.reachable}
					<!-- Red X crossing out a bin the chute can't physically reach. -->
					<line x1={b.x - 3.5} y1={b.y - 3.5} x2={b.x + 3.5} y2={b.y + 3.5} class="stroke-danger" stroke-width="1.25" />
					<line x1={b.x - 3.5} y1={b.y + 3.5} x2={b.x + 3.5} y2={b.y - 3.5} class="stroke-danger" stroke-width="1.25" />
				{/if}
			</g>
		{/each}

		<circle cx={CX} cy={CY} r="2" class="fill-text-muted" />
	</svg>

	{#if unreachableCount > 0}
		<p class="text-sm text-danger">
			{unreachableCount}
			{unreachableCount === 1 ? 'bin falls' : 'bins fall'} in the {maxAngleDeg.toFixed(0)}° no-go wedge by home.
		</p>
	{/if}
</div>
