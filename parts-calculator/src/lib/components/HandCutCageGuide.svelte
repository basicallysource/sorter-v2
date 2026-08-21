<script lang="ts">
	// Step-by-step guide for cutting a cable cage plate (top or bottom) with a
	// jigsaw, a drill and a tape measure. Geometry comes from $lib/cagehandcut
	// (derived from the DXF); the length/bit formatting helpers are shared with
	// the top-plate guide in $lib/handcut. SVG diagrams are drawn in plate mm
	// with y flipped for SVG so they stay honest.
	import { fmtLen, bitLabel, type Units } from '$lib/handcut';
	import {
		CAGE_HEX,
		CAGE_RECT,
		CAGE_CENTER_HOLE_D,
		MOUNT_HOLE_D,
		MOUNT_RING_R,
		MOUNT_ANGLES,
		CLAMP_HOLE_D,
		CLAMP_RING_R,
		CLAMP_HOLES,
		KEY
	} from '$lib/cagehandcut';

	let {
		variant,
		units = $bindable('in')
	}: { variant: 'top' | 'bottom'; units?: Units } = $props();

	const isTop = $derived(variant === 'top');
	const L = (mm: number) => fmtLen(mm, units);
	const bit = (d: number) => bitLabel(d, units);

	const overview = $derived(
		isTop
			? 'https://sorter-v2-parts.nyc3.cdn.digitaloceanspaces.com/img/4a2aea74e2dadc3713612e44974a0a751d7ae0ac2891df6a588e7cd9d6d925dd.png'
			: 'https://sorter-v2-parts.nyc3.cdn.digitaloceanspaces.com/img/8398abac6bbe5bbbfeee2ed9206ea47278a6f9664509473812d0f882bba50ba5.png'
	);

	// plate coords are y-up; SVG is y-down
	const rad = (deg: number) => (deg * Math.PI) / 180;
	const P = (r: number, deg: number): [number, number] => [r * Math.cos(rad(deg)), -r * Math.sin(rad(deg))];

	const hw = CAGE_RECT.w / 2; // 162.5, half across flats (horizontal)
	const hh = CAGE_RECT.h / 2; // 187.64, half across corners (vertical)
	const co = CAGE_HEX.cornerOffset; // 93.82
	const hexPts: [number, number][] = [
		[0, -hh],
		[hw, -co],
		[hw, co],
		[0, hh],
		[-hw, co],
		[-hw, -co]
	];
	const hexPtsStr = hexPts.map((p) => p.join(',')).join(' ');

	const mountPts = MOUNT_ANGLES.map((a) => P(MOUNT_RING_R, a));

	// keyway outline: outer arc (r104.5) sampled + two end walls to the centre hole
	const outerArc = Array.from({ length: 41 }, (_, i) =>
		P(KEY.outerR, KEY.outerFromDeg + (i * (KEY.outerToDeg - KEY.outerFromDeg)) / 40)
	);
	const outerArcStr = outerArc.map((p) => p.join(',')).join(' ');
	const wallA = [P(KEY.innerR, KEY.innerFromDeg), P(KEY.outerR, KEY.outerFromDeg)];
	const wallB = [P(KEY.innerR, KEY.innerToDeg), P(KEY.outerR, KEY.outerToDeg)];
</script>

<div class="space-y-6 p-4 text-sm text-text">
	<!-- overview drawing (print this) -->
	<figure class="m-0">
		<div class="border border-border bg-white p-2">
			<img
				src={overview}
				alt="Full dimensioned hand-cut drawing of the cable cage {variant}"
				class="mx-auto block w-full max-w-2xl"
				loading="lazy"
			/>
		</div>
		<figcaption class="mt-2 text-xs text-text-muted">
			The whole thing on one sheet, in mm and inches — print it and work from it. The diagrams below
			walk through it step by step.
		</figcaption>
	</figure>

	<!-- intro + unit toggle -->
	<div class="flex flex-wrap items-start justify-between gap-3">
		<p class="max-w-xl text-text-muted">
			No laser? Both cage plates are a <b class="text-text">regular hexagon</b>, the same outline top
			and bottom, so they lay out from a rectangle with a tape measure. A hexagon checks its own
			accuracy: the distance from the centre to each corner equals the side length. The centre is one
			big drilled-and-jigsawed hole; everything else is drill holes.
		</p>
		<div class="flex shrink-0 border border-border" role="group" aria-label="Units">
			{#each [['mm', 'Metric (mm)'], ['in', 'Imperial (inches)']] as [id, label] (id)}
				<button
					class="px-3 py-1.5 text-xs font-semibold {units === id
						? 'bg-[var(--color-primary)] text-[var(--color-primary-contrast)]'
						: 'text-text-muted hover:text-text'}"
					onclick={() => (units = id as Units)}
				>
					{label}
				</button>
			{/each}
		</div>
	</div>

	<!-- main diagram -->
	<div class="border border-border bg-[var(--color-bg)] p-2">
		<svg viewBox="-250 -235 500 490" class="mx-auto block w-full max-w-2xl" role="img" aria-label="Cable cage {variant} layout">
			<!-- construction circles to strike with a trammel -->
			<circle cx="0" cy="0" r={MOUNT_RING_R} fill="none" stroke="#c0392b66" stroke-width="1.2" stroke-dasharray="8 6" />
			{#if isTop}
				<circle cx="0" cy="0" r={CLAMP_RING_R} fill="none" stroke="#2471a366" stroke-width="1.2" stroke-dasharray="8 6" />
				<circle cx="0" cy="0" r={KEY.centreR} fill="none" stroke="#8e44ad66" stroke-width="1.2" stroke-dasharray="8 6" />
			{/if}
			<!-- outline -->
			<polygon points={hexPtsStr} fill="none" stroke="var(--color-text)" stroke-width="3" />
			<!-- centre hole -->
			<circle cx="0" cy="0" r={CAGE_CENTER_HOLE_D / 2} fill="none" stroke="var(--color-text)" stroke-width="3" />
			<text x="0" y="-6" fill="var(--color-text)" font-size="20" text-anchor="middle">Ø {L(CAGE_CENTER_HOLE_D)}</text>
			<!-- centre cross -->
			<line x1="-12" y1="0" x2="12" y2="0" stroke="var(--color-text)" stroke-width="1.5" />
			<line x1="0" y1="-12" x2="0" y2="12" stroke="var(--color-text)" stroke-width="1.5" />
			<!-- six mounting holes -->
			{#each mountPts as p (p.join())}
				<circle cx={p[0]} cy={p[1]} r="10" fill="none" stroke="#c0392b" stroke-width="2" />
				<line x1={p[0] - 7} y1={p[1]} x2={p[0] + 7} y2={p[1]} stroke="#c0392b" stroke-width="1.6" />
				<line x1={p[0]} y1={p[1] - 7} x2={p[0]} y2={p[1] + 7} stroke="#c0392b" stroke-width="1.6" />
			{/each}
			{#if isTop}
				<!-- twelve small holes -->
				{#each CLAMP_HOLES as h (h.x + ',' + h.y)}
					<circle cx={h.x} cy={-h.y} r="6" fill="none" stroke="#2471a3" stroke-width="1.8" />
				{/each}
				<!-- keyed notch: outer arc + end walls + the two drill holes -->
				<polyline points={outerArcStr} fill="none" stroke="var(--color-text)" stroke-width="3" />
				<line x1={wallA[0][0]} y1={wallA[0][1]} x2={wallA[1][0]} y2={wallA[1][1]} stroke="var(--color-text)" stroke-width="3" />
				<line x1={wallB[0][0]} y1={wallB[0][1]} x2={wallB[1][0]} y2={wallB[1][1]} stroke="var(--color-text)" stroke-width="3" />
				{#each KEY.drills as d (d.x + ',' + d.y)}
					<circle cx={d.x} cy={-d.y} r={KEY.bit / 2} fill="none" stroke="#c0392b" stroke-width="2.2" />
				{/each}
			{/if}
			<!-- across-flats dim (bottom) -->
			<g stroke="var(--color-text-muted)" stroke-width="1.2">
				<line x1={-hw} y1={hh + 28} x2={hw} y2={hh + 28} />
				<line x1={-hw} y1={hh + 16} x2={-hw} y2={hh + 40} />
				<line x1={hw} y1={hh + 16} x2={hw} y2={hh + 40} />
			</g>
			<text x="0" y={hh + 48} fill="var(--color-text)" font-size="20" text-anchor="middle">{L(CAGE_HEX.acrossFlats)} across flats</text>
			<!-- point-to-point dim (right) -->
			<g stroke="var(--color-text-muted)" stroke-width="1.2">
				<line x1={hw + 40} y1={-hh} x2={hw + 40} y2={hh} />
				<line x1={hw + 28} y1={-hh} x2={hw + 52} y2={-hh} />
				<line x1={hw + 28} y1={hh} x2={hw + 52} y2={hh} />
			</g>
			<text x={hw + 58} y="0" fill="var(--color-text)" font-size="20" text-anchor="middle" transform="rotate(90, {hw + 58}, 0)">{L(CAGE_HEX.acrossCorners)} point to point</text>
			<!-- side length (left flat) -->
			<g stroke="var(--color-text-muted)" stroke-width="1.2">
				<line x1={-hw - 30} y1={-co} x2={-hw - 30} y2={co} />
				<line x1={-hw - 42} y1={-co} x2={-hw - 18} y2={-co} />
				<line x1={-hw - 42} y1={co} x2={-hw - 18} y2={co} />
			</g>
			<text x={-hw - 40} y="0" fill="var(--color-text)" font-size="20" text-anchor="middle" transform="rotate(-90, {-hw - 40}, 0)">side {L(CAGE_HEX.side)}</text>
		</svg>
	</div>
	<div class="flex flex-wrap gap-x-4 gap-y-1 text-xs text-text-muted">
		<span class="inline-flex items-center gap-1.5"><span class="h-3 w-3 rounded-full border-2" style="border-color:#c0392b"></span> six Ø {bit(MOUNT_HOLE_D)} mounting holes · {L(MOUNT_RING_R)} radius</span>
		{#if isTop}
			<span class="inline-flex items-center gap-1.5"><span class="h-3 w-3 rounded-full border-2" style="border-color:#2471a3"></span> twelve Ø {bit(CLAMP_HOLE_D)} holes · {L(CLAMP_RING_R)} radius</span>
			<span class="inline-flex items-center gap-1.5"><span class="h-3 w-3 rounded-full border-2" style="border-color:#8e44ad"></span> keyed-notch radius {L(KEY.centreR)}</span>
		{/if}
	</div>

	<!-- tools -->
	<section>
		<h3 class="mb-1 text-xs font-semibold uppercase tracking-wider text-text-muted">What you need</h3>
		<ul class="list-inside list-disc space-y-0.5 text-text-muted">
			<li>Jigsaw with a fine wood blade, and a drill</li>
			<li>
				Bits: {bit(MOUNT_HOLE_D)} (six mounting holes){#if isTop}, {bit(CLAMP_HOLE_D)} (the twelve small holes, if you drill them), {bit(KEY.bit)} spade or Forstner (the two keyed-notch ends){/if}, and a bit for the jigsaw blade entry
			</li>
			<li>Tape measure, straightedge, pencil, awl or nail to punch hole centres</li>
			<li>A scrap stick + small nail for a trammel (beam compass), sandpaper on a block, clamps</li>
		</ul>
		<p class="mt-2 text-xs text-text-muted">
			Do <b class="text-text">all layout and drilling while the panel is still a rectangle</b> — the
			corners come off last.
		</p>
	</section>

	<!-- STEP 1: rectangle -->
	<section>
		<h3 class="mb-1 text-xs font-semibold uppercase tracking-wider text-text-muted">Step 1 · Cut the stock rectangle</h3>
		<p class="text-text-muted">
			Cut a rectangle <b class="text-text">{L(CAGE_RECT.w)} × {L(CAGE_RECT.h)}</b> from {units === 'mm' ? '3 mm' : '1/8″'} plywood. Keep the corners square — check both diagonals: each should be <b class="text-text">{L(CAGE_HEX.diagonal)}</b>, and they must match.
		</p>
	</section>

	<!-- STEP 2: centrelines + hexagon -->
	<section>
		<h3 class="mb-1 text-xs font-semibold uppercase tracking-wider text-text-muted">Step 2 · Centrelines and the six corners</h3>
		<p class="text-text-muted">
			Mark half the width ({L(CAGE_RECT.w / 2)}) in from each side and half the height ({L(CAGE_RECT.h / 2)}) from top and bottom; where they cross is the plate centre. Two corners are where the vertical centreline meets the top and bottom edges; the other four sit on the left and right edges, <b class="text-text">{L(CAGE_HEX.cornerOffset)}</b> above and below the horizontal centreline. Join them. <b class="text-text">Verify:</b> every side is {L(CAGE_HEX.side)}, and the centre-to-corner distance is the same {L(CAGE_HEX.side)}.
		</p>
	</section>

	<!-- STEP 3: strike circles + holes -->
	<section>
		<h3 class="mb-1 text-xs font-semibold uppercase tracking-wider text-text-muted">Step 3 · Strike the hole circles and mark the centres</h3>
		<p class="text-text-muted">
			Set a trammel (a scrap stick with a nail at the centre and a pencil at the radius) and swing each dashed circle from the plate centre:
		</p>
		<ul class="mt-1 list-inside list-disc space-y-0.5 text-text-muted">
			<li><b class="text-text">Mounting holes:</b> strike {L(MOUNT_RING_R)}. The six Ø {bit(MOUNT_HOLE_D)} holes sit on it, one at each hexagon corner (every 60°). Walk the same {L(MOUNT_RING_R)} trammel setting around the circle from any corner: for six even holes the neighbour-to-neighbour step equals the radius, and six steps land you back at the start.</li>
			{#if isTop}
				<li><b class="text-text">Keyed notch:</b> strike {L(KEY.centreR)}. Draw a line from the centre out through whichever corner you want the key to face; where the {L(KEY.centreR)} circle crosses that line, step {L(KEY.alongArc)} along the circle each way and mark. Those two marks are the notch-end drill centres ({L(KEY.spacing)} apart).</li>
				<li><b class="text-text">The twelve Ø {bit(CLAMP_HOLE_D)} holes</b> sit on {L(CLAMP_RING_R)}, in pairs on each edge. See the note below before you drill these.</li>
			{/if}
		</ul>
		<p class="mt-1 text-text-muted">Punch every centre with an awl so the bit can't wander.</p>
	</section>

	<!-- STEP 4: drill -->
	<section>
		<h3 class="mb-1 text-xs font-semibold uppercase tracking-wider text-text-muted">Step 4 · Drill</h3>
		<p class="text-text-muted">
			Clamp scrap under the plate. Drill the six {bit(MOUNT_HOLE_D)} mounting holes.
			{#if isTop}
				Then drill the two keyed-notch ends with a {bit(KEY.bit)} spade or Forstner bit: the notch is a pocket exactly {L(KEY.depth)} deep, so a {bit(KEY.bit)} hole centred on the {L(KEY.centreR)} circle breaks into the big hole on the inside and just touches the outer edge — that hole becomes the rounded end of the notch.
			{/if}
			With spade bits, stop as the point pokes through and finish from the other face to kill tear-out.
		</p>
	</section>

	<!-- STEP 5: centre opening -->
	<section>
		<h3 class="mb-1 text-xs font-semibold uppercase tracking-wider text-text-muted">Step 5 · Jigsaw the centre hole{#if isTop} and the notch{/if}</h3>
		<p class="text-text-muted">
			Reset the trammel to <b class="text-text">{L(CAGE_CENTER_HOLE_D / 2)}</b> and scribe the Ø {L(CAGE_CENTER_HOLE_D)} centre circle. Drill a blade-entry hole just inside the waste, drop the jigsaw blade in, and cut around about 1&nbsp;mm inside the line, then sand back to it. This opening is pure clearance, so ±1&nbsp;mm is fine.
			{#if isTop}
				For the notch, saw the short outer wall (an arc about {L(KEY.outerR)} from the centre) between the two {bit(KEY.bit)} holes, then pare the inner edge back flush with the Ø {L(CAGE_CENTER_HOLE_D)} hole.
			{/if}
		</p>
	</section>

	<!-- STEP 6: corners -->
	<section>
		<h3 class="mb-1 text-xs font-semibold uppercase tracking-wider text-text-muted">Step 6 · Cut the corners off, finish</h3>
		<p class="text-text-muted">
			Jigsaw the six corner triangles, staying just outside each pencil line, and block-sand to it. <b class="text-text">Final checks:</b> {L(CAGE_HEX.acrossFlats)} across the flats, {L(CAGE_HEX.acrossCorners)} point to point, every side {L(CAGE_HEX.side)}.
		</p>
	</section>

	{#if isTop}
		<!-- honest note on the twelve small holes -->
		<section class="border border-border bg-[var(--color-bg)] px-3 py-2">
			<h3 class="mb-1 text-xs font-semibold uppercase tracking-wider text-text-muted">About the twelve Ø {bit(CLAMP_HOLE_D)} holes</h3>
			<p class="text-xs text-text-muted">
				These are in the laser-cut file, but the documented top-interface build doesn't fasten anything into them (the cage brackets use the {bit(MOUNT_HOLE_D)} corner holes, and the cable clamps mount to the chute mount). They look like optional cable-management points. <b class="text-text">You can leave them out</b> unless your build turns out to need them — this note will be updated once it's confirmed what they're for.
			</p>
		</section>
	{/if}

	<p class="text-xs text-text-muted">
		Photos of a real hand-cut plate are on the way and will be added here as a worked example.
	</p>
</div>
