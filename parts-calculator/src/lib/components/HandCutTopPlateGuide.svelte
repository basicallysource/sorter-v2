<script lang="ts">
	// Step-by-step guide for cutting the top plate with a jigsaw, a drill and a
	// tape measure. All geometry comes from $lib/handcut (derived from the DXF).
	// SVG diagrams are drawn in plate mm (y flipped for SVG) so they stay honest.
	import {
		HEX,
		RECT,
		HOLES,
		CABLE_SLOTS,
		CENTER_HOLE_D,
		SMALL_HOLE_D,
		CABLE_HOLE_D,
		RING_INNER_R,
		RING_OUTER_R,
		fromEdges,
		fmtLen,
		bitLabel,
		type Units,
		type HoleGroup
	} from '$lib/handcut';

	// `units` is bindable so the parent can mirror it into the URL (?units=mm).
	let { units = $bindable('in') }: { units?: Units } = $props();
	const L = (mm: number) => fmtLen(mm, units);
	const bit = (d: number) => bitLabel(d, units);

	// SVG helpers: plate coords are y-up, SVG is y-down
	const sy = (y: number) => -y;

	const GROUP_COLOR: Record<HoleGroup, string> = {
		stepper: '#0055bf',
		inner: '#00852B',
		outer: '#b87e00',
		cable: '#950051'
	};
	const GROUP_LABEL: Record<HoleGroup, string> = {
		stepper: 'stepper trio',
		inner: 'inner ring',
		outer: 'outer ring',
		cable: 'cable holes'
	};

	// hexagon corners, SVG coords (y down)
	const hw = RECT.w / 2; // apothem
	const hh = RECT.h / 2; // circumradius
	const co = HEX.cornerOffset;
	const hexPts = [
		[0, -hh],
		[hw, -co],
		[hw, co],
		[0, hh],
		[-hw, co],
		[-hw, -co]
	];
	const hexPtsStr = hexPts.map((p) => p.join(',')).join(' ');

	// hole label offset: radially outward from plate center, with overrides for
	// the holes that sit on the horizontal centerline (outward would collide)
	function labelPos(h: { id: string; x: number; y: number }): { x: number; y: number } {
		const over: Record<string, [number, number]> = {
			S1: [12, -14],
			S2: [0, 26],
			S3: [-2, -14],
			C1: [-2, -22]
		};
		const o = over[h.id];
		if (o) return { x: h.x + o[0], y: sy(h.y) + o[1] };
		const r = Math.hypot(h.x, h.y) || 1;
		const k = (r + 26) / r;
		return { x: h.x * k, y: sy(h.y * k) + 7 };
	}

	const groups: HoleGroup[] = ['stepper', 'inner', 'outer', 'cable'];
</script>

<div class="space-y-6 p-4 text-sm text-text">
	<!-- worked example -->
	<figure class="m-0">
		<div class="grid grid-cols-1 gap-2 sm:grid-cols-2">
			<img
				src="/examples/handcut-top-plate-1.jpg"
				alt="A hand-cut hexagonal top plate with the drilled hole pattern and center opening"
				class="w-full border border-border"
				loading="lazy"
			/>
			<img
				src="/examples/handcut-top-plate-2.jpg"
				alt="The same hand-cut top plate with the interface assembly mounted"
				class="w-full border border-border"
				loading="lazy"
			/>
		</div>
		<figcaption class="mt-2 text-xs text-text-muted">
			Example courtesy of zed0 in the basically Discord
		</figcaption>
	</figure>

	<!-- intro + unit toggle -->
	<div class="flex flex-wrap items-start justify-between gap-3">
		<p class="max-w-xl text-text-muted">
			No laser big enough? The top plate is a <b class="text-text">regular hexagon</b> — it lays out
			from a rectangle with nothing but a tape measure, and a hexagon checks its own accuracy: the
			distance from the center to each corner equals the side length. The five rounded cable slots
			are replaced by single {bit(CABLE_HOLE_D)} drill holes.
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

	{#if units === 'in'}
		<p class="border border-border bg-[var(--color-bg)] px-3 py-2 text-xs text-text-muted">
			Inch values are rounded to the nearest 1/32″ — at worst 0.4&nbsp;mm off, which is fine here.
			What matters most is the spacing of the small holes relative to each other; the outline is the
			least critical cut on the plate.
		</p>
	{/if}

	<!-- tools -->
	<section>
		<h3 class="mb-1 text-xs font-semibold uppercase tracking-wider text-text-muted">What you need</h3>
		<ul class="list-inside list-disc space-y-0.5 text-text-muted">
			<li>Jigsaw with a fine wood blade, and a drill</li>
			<li>
				Bits: {bit(SMALL_HOLE_D)} (15 small holes) and {bit(CABLE_HOLE_D)} spade or Forstner (5
				cable holes — it also drills the jigsaw blade entry)
			</li>
			<li>Tape measure, straightedge, pencil, awl or nail (to punch hole centers)</li>
			<li>A scrap stick + small nail for a trammel (beam compass), sandpaper on a block, clamps</li>
		</ul>
		<p class="mt-2 text-xs text-text-muted">
			The whole trick: do <b class="text-text">all layout and drilling while the panel is still a
			rectangle</b> — every measurement references the two factory edges. The corners come off last.
		</p>
	</section>

	<!-- STEP 1-2: rectangle + centerlines + hexagon -->
	<section>
		<h3 class="mb-1 text-xs font-semibold uppercase tracking-wider text-text-muted">
			Step 1 · Cut the stock rectangle
		</h3>
		<p class="text-text-muted">
			Cut a rectangle <b class="text-text">{L(RECT.w)} × {L(RECT.h)}</b> from {units === 'mm'
				? '10 mm'
				: '3/8″'} plywood. Keep the edges straight and the corners square — check by measuring both
			diagonals: each should be <b class="text-text">{L(HEX.diagonal)}</b>, and they must match.
		</p>
		<h3 class="mb-1 mt-3 text-xs font-semibold uppercase tracking-wider text-text-muted">
			Step 2 · Draw the centerlines, mark the six corners
		</h3>
		<p class="text-text-muted">
			Mark half the height ({L(RECT.h / 2)}) up from the bottom edge on both sides and join —
			that's the horizontal centerline. Same with half the width ({L(RECT.w / 2)}) for the vertical
			one. Their crossing is the plate center. Then mark the six hexagon corners: two are where the
			vertical centerline meets the top and bottom edges; the other four sit on the left and right
			edges, <b class="text-text">{L(HEX.cornerOffset)}</b> above and below the horizontal
			centerline. Join them with a straightedge.
		</p>
		<div class="mt-2 border border-border bg-[var(--color-bg)] p-2">
			<svg viewBox="-500 -520 1000 990" class="mx-auto block w-full max-w-2xl" role="img" aria-label="Hexagon layout from a rectangle">
				<!-- waste corners -->
				{#each [[0, -hh, hw, -hh, hw, -co], [0, -hh, -hw, -hh, -hw, -co], [0, hh, hw, hh, hw, co], [0, hh, -hw, hh, -hw, co]] as t}
					<polygon points="{t[0]},{t[1]} {t[2]},{t[3]} {t[4]},{t[5]}" fill="#d0101226" stroke="none" />
				{/each}
				<!-- stock rectangle -->
				<rect x={-hw} y={-hh} width={RECT.w} height={RECT.h} fill="none" stroke="var(--color-text-muted)" stroke-width="1.5" stroke-dasharray="10 6" />
				<!-- centerlines -->
				<line x1={-hw - 20} y1="0" x2={hw + 20} y2="0" stroke="var(--color-text-muted)" stroke-width="1" stroke-dasharray="16 6 3 6" />
				<line x1="0" y1={-hh - 20} x2="0" y2={hh + 20} stroke="var(--color-text-muted)" stroke-width="1" stroke-dasharray="16 6 3 6" />
				<!-- hexagon -->
				<polygon points={hexPtsStr} fill="none" stroke="var(--color-text)" stroke-width="3.5" />
				<!-- corner dots -->
				{#each hexPts as p}
					<circle cx={p[0]} cy={p[1]} r="7" fill="var(--color-primary)" />
				{/each}
				<!-- center -->
				<circle cx="0" cy="0" r="5" fill="var(--color-text)" />
				<!-- trammel check line: center -> lower-right corner -->
				<line x1="0" y1="0" x2={hw} y2={co} stroke="var(--color-primary)" stroke-width="1.5" stroke-dasharray="6 5" />
				<text x={hw / 2 + 14} y={co / 2 + 38} fill="var(--color-primary)" font-size="26" transform="rotate({(Math.atan2(co, hw) * 180) / Math.PI}, {hw / 2}, {co / 2})" text-anchor="middle">center → corner {L(HEX.side)}</text>
				<!-- width dim (top) -->
				<g stroke="var(--color-text-muted)" stroke-width="1.2">
					<line x1={-hw} y1={-hh - 28} x2={hw} y2={-hh - 28} />
					<line x1={-hw} y1={-hh - 40} x2={-hw} y2={-hh - 16} />
					<line x1={hw} y1={-hh - 40} x2={hw} y2={-hh - 16} />
				</g>
				<text x="0" y={-hh - 42} fill="var(--color-text)" font-size="28" text-anchor="middle">{L(RECT.w)}</text>
				<!-- height dim (left) -->
				<g stroke="var(--color-text-muted)" stroke-width="1.2">
					<line x1={-hw - 46} y1={-hh} x2={-hw - 46} y2={hh} />
					<line x1={-hw - 58} y1={-hh} x2={-hw - 34} y2={-hh} />
					<line x1={-hw - 58} y1={hh} x2={-hw - 34} y2={hh} />
				</g>
				<text x={-hw - 56} y="0" fill="var(--color-text)" font-size="28" text-anchor="middle" transform="rotate(-90, {-hw - 56}, 0)">{L(RECT.h)}</text>
				<!-- corner offset dims (right edge, up + down) -->
				<g stroke="var(--color-text-muted)" stroke-width="1.2">
					<line x1={hw + 34} y1="0" x2={hw + 34} y2={-co} />
					<line x1={hw + 22} y1="0" x2={hw + 46} y2="0" />
					<line x1={hw + 22} y1={-co} x2={hw + 46} y2={-co} />
					<line x1={hw + 34} y1="0" x2={hw + 34} y2={co} />
					<line x1={hw + 22} y1={co} x2={hw + 46} y2={co} />
				</g>
				<text x={hw + 52} y={-co / 2} fill="var(--color-text)" font-size="26" text-anchor="middle" transform="rotate(90, {hw + 52}, {-co / 2})">{L(HEX.cornerOffset)}</text>
				<text x={hw + 52} y={co / 2} fill="var(--color-text)" font-size="26" text-anchor="middle" transform="rotate(90, {hw + 52}, {co / 2})">{L(HEX.cornerOffset)}</text>
				<!-- side length label along top-right side -->
				<text x={hw / 2 + 44} y={-(hh + co) / 2 - 30} fill="var(--color-text)" font-size="26" text-anchor="middle" transform="rotate(30, {hw / 2 + 44}, {-(hh + co) / 2 - 30})">side {L(HEX.side)}</text>
			</svg>
		</div>
		<p class="mt-2 text-xs text-text-muted">
			Shaded corners are the waste. <b class="text-text">Before cutting anything, verify:</b> all six
			sides should measure {L(HEX.side)}, and the center-to-corner distance is the <i>same</i>
			{L(HEX.side)} — not a coincidence, a regular hexagon's side equals its circumradius. Any
			corner mark that fails both checks is wrong; find it now, not after the saw.
		</p>
	</section>

	<!-- STEP 3: holes -->
	<section>
		<h3 class="mb-1 text-xs font-semibold uppercase tracking-wider text-text-muted">
			Step 3 · Lay out and punch the hole centers
		</h3>
		<p class="text-text-muted">
			Every hole below is measured <b class="text-text">from the rectangle's left and bottom
			edges</b> (that's why the corners stay on). For each hole: tick its from-bottom height twice,
			a little left and right of where it lands, join with a short pencil line, then tick the
			from-left distance along that line. Punch every center with an awl so the bit can't wander.
		</p>
		<div class="mt-2 border border-border bg-[var(--color-bg)] p-2">
			<svg viewBox="-500 -460 1000 920" class="mx-auto block w-full max-w-2xl" role="img" aria-label="Hole map">
				<!-- plate + centerlines -->
				<polygon points={hexPtsStr} fill="none" stroke="var(--color-text-muted)" stroke-width="2" />
				<line x1={-hw} y1="0" x2={hw} y2="0" stroke="var(--color-text-muted)" stroke-width="0.8" stroke-dasharray="16 6 3 6" />
				<line x1="0" y1={-hh} x2="0" y2={hh} stroke="var(--color-text-muted)" stroke-width="0.8" stroke-dasharray="16 6 3 6" />
				<!-- ring construction circles -->
				<circle cx="0" cy="0" r={RING_INNER_R} fill="none" stroke="#00852B55" stroke-width="1.2" stroke-dasharray="8 6" />
				<circle cx="0" cy="0" r={RING_OUTER_R} fill="none" stroke="#b87e0055" stroke-width="1.2" stroke-dasharray="8 6" />
				<!-- center opening -->
				<circle cx="0" cy="0" r={CENTER_HOLE_D / 2} fill="none" stroke="var(--color-text)" stroke-width="3" />
				<text x="0" y="-16" fill="var(--color-text)" font-size="28" text-anchor="middle">Ø {L(CENTER_HOLE_D)}</text>
				<text x="0" y="20" fill="var(--color-text-muted)" font-size="24" text-anchor="middle">jigsaw</text>
				<!-- ghost outlines of the original cable slots -->
				{#each CABLE_SLOTS as s}
					<rect x={-s.L / 2} y={-s.W / 2} width={s.L} height={s.W} rx="5" fill="none" stroke="#95005155" stroke-width="1.2" stroke-dasharray="5 4" transform="translate({s.cx}, {sy(s.cy)}) rotate({s.rot})" />
				{/each}
				<!-- holes -->
				{#each HOLES as h (h.id)}
					{@const lp = labelPos(h)}
					<circle cx={h.x} cy={sy(h.y)} r={Math.max(h.d / 2, 6)} fill={GROUP_COLOR[h.group]} />
					<text x={lp.x} y={lp.y} fill={GROUP_COLOR[h.group]} font-size="24" font-weight="600" text-anchor="middle">{h.id}</text>
				{/each}
			</svg>
		</div>
		<div class="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-text-muted">
			{#each groups as g (g)}
				<span class="inline-flex items-center gap-1.5">
					<span class="h-3 w-3 rounded-full" style="background:{GROUP_COLOR[g]}"></span>
					{g === 'cable' ? `${GROUP_LABEL[g]} · Ø ${bit(CABLE_HOLE_D)}` : `${GROUP_LABEL[g]} · Ø ${bit(SMALL_HOLE_D)}`}
				</span>
			{/each}
			<span class="inline-flex items-center gap-1.5">
				<span class="h-3 w-3 rounded-full border-2 border-[#95005155]"></span>
				original cable slots (replaced by the holes)
			</span>
		</div>
		<div class="mt-3 overflow-x-auto">
			<table class="w-full max-w-lg border-collapse text-xs">
				<thead>
					<tr class="border-b border-border text-left text-text-muted">
						<th class="py-1 pr-3 font-semibold">Hole</th>
						<th class="py-1 pr-3 font-semibold">Bit</th>
						<th class="py-1 pr-3 font-semibold">From left edge</th>
						<th class="py-1 font-semibold">From bottom edge</th>
					</tr>
				</thead>
				<tbody>
					{#each groups as g (g)}
						<tr class="border-b border-border bg-[var(--color-bg)] text-text-muted">
							<td colspan="4" class="py-1 pr-3">
								<span class="mr-1.5 inline-block h-2 w-2 rounded-full align-baseline" style="background:{GROUP_COLOR[g]}"></span>{GROUP_LABEL[g]}
							</td>
						</tr>
						{#each HOLES.filter((h) => h.group === g) as h (h.id)}
							{@const e = fromEdges(h)}
							<tr class="border-b border-border last:border-b-0">
								<td class="py-1 pr-3 font-semibold">{h.id}</td>
								<td class="py-1 pr-3 text-text-muted">{bit(h.d)}</td>
								<td class="py-1 pr-3 tabular-nums">{L(e.left)}</td>
								<td class="py-1 tabular-nums">{L(e.bottom)}</td>
							</tr>
						{/each}
					{/each}
					<tr>
						<td class="py-1 pr-3 font-semibold">Center</td>
						<td class="py-1 pr-3 text-text-muted">Ø {L(CENTER_HOLE_D)} jigsaw</td>
						<td class="py-1 pr-3 tabular-nums">{L(RECT.w / 2)}</td>
						<td class="py-1 tabular-nums">{L(RECT.h / 2)}</td>
					</tr>
				</tbody>
			</table>
		</div>
		<p class="mt-2 text-xs text-text-muted">
			<b class="text-text">Ring shortcut (recommended):</b> instead of measuring all twelve ring
			holes, mark just I1 and O1 from the table. Set the trammel to the ring radius —
			{L(RING_INNER_R)} for the inner ring, {L(RING_OUTER_R)} for the outer — scribe each circle
			from the center, then <i>walk the same trammel setting around the circle</i> starting at the
			marked hole: for six evenly spaced holes, the neighbor-to-neighbor distance equals the radius.
			Six steps should land you exactly back at the start — if they don't, re-scribe before punching.
		</p>
		<figure class="mt-3">
			<img
				src="https://img.basically.website/web/assembly/top-plate/handcut-layout-marked.57ec0d10558593fa.jpg"
				alt="Black-painted plywood rectangle with the hexagonal top plate outline, center opening, cable holes, stepper holes, and two mounting-hole rings marked in white pencil"
				class="w-full border border-border"
				loading="lazy"
			/>
			<figcaption class="mt-1 text-xs text-text-muted">
				All cut lines and hole centers marked while the panel is rectangular. This example is plywood painted black.
			</figcaption>
		</figure>
	</section>

	<!-- STEP 4: drill -->
	<section>
		<h3 class="mb-1 text-xs font-semibold uppercase tracking-wider text-text-muted">
			Step 4 · Drill
		</h3>
		<p class="text-text-muted">
			Clamp scrap under the plate and drill the fifteen {bit(SMALL_HOLE_D)} holes, then the five
			{bit(CABLE_HOLE_D)} cable holes with a spade or Forstner bit. With spade bits, stop as soon as
			the center point pokes through and finish from the other face — that's what kills tear-out.
			(Two of the original slots are 18&nbsp;mm wide, so the {bit(CABLE_HOLE_D)} hole runs a hair
			wider there; they only pass cables, it doesn't matter.)
		</p>
		<p class="mt-2 text-xs text-text-muted">
			Keep the drill square to the panel surface so the holes do not leave at an angle.
		</p>
		<figure class="mt-3">
			<div class="grid grid-cols-1 gap-2 sm:grid-cols-2">
				<img
					src="https://img.basically.website/web/assembly/top-plate/handcut-drilling.2c55404e78214d33.jpg"
					alt="A large hole being drilled square to the black-painted plywood top plate while the panel is still rectangular"
					class="w-full border border-border"
					loading="lazy"
				/>
				<img
					src="https://img.basically.website/web/assembly/top-plate/handcut-holes-cut.a775177a326c6a6a.jpg"
					alt="Black-painted plywood top plate with the center opening, cable holes, and small mounting holes cut before the corner waste is removed"
					class="w-full border border-border"
					loading="lazy"
				/>
			</div>
			<figcaption class="mt-1 text-xs text-text-muted">
				Drill every hole and cut the center opening before trimming the panel to its hexagonal outline.
			</figcaption>
		</figure>
	</section>

	<!-- STEP 5: center opening -->
	<section>
		<h3 class="mb-1 text-xs font-semibold uppercase tracking-wider text-text-muted">
			Step 5 · Jigsaw the center opening
		</h3>
		<div class="mt-2 border border-border bg-[var(--color-bg)] p-2">
			<svg viewBox="-280 -190 560 380" class="mx-auto block w-full max-w-md" role="img" aria-label="Trammel and blade entry for the center circle">
				<!-- scribed circle -->
				<circle cx="0" cy="0" r={CENTER_HOLE_D / 2} fill="none" stroke="var(--color-text)" stroke-width="2.5" stroke-dasharray="9 6" />
				<!-- center cross -->
				<line x1="-12" y1="0" x2="12" y2="0" stroke="var(--color-text)" stroke-width="2" />
				<line x1="0" y1="-12" x2="0" y2="12" stroke="var(--color-text)" stroke-width="2" />
				<!-- trammel stick -->
				<rect x="-24" y="-11" width="148" height="22" rx="10" fill="#b87e0033" stroke="var(--color-text-muted)" stroke-width="1.5" />
				<circle cx="0" cy="0" r="4" fill="var(--color-text)" />
				<circle cx={CENTER_HOLE_D / 2} cy="0" r="4" fill="var(--color-primary)" />
				<text x="4" y="-30" fill="var(--color-text)" font-size="17">nail at center</text>
				<text x={CENTER_HOLE_D / 2 + 10} y="-14" fill="var(--color-primary)" font-size="17">pencil</text>
				<!-- radius dim under the stick -->
				<g stroke="var(--color-text-muted)" stroke-width="1">
					<line x1="0" y1="34" x2={CENTER_HOLE_D / 2} y2="34" />
					<line x1="0" y1="27" x2="0" y2="41" />
					<line x1={CENTER_HOLE_D / 2} y1="27" x2={CENTER_HOLE_D / 2} y2="41" />
				</g>
				<text x={CENTER_HOLE_D / 4} y="56" fill="var(--color-text)" font-size="17" text-anchor="middle">{L(CENTER_HOLE_D / 2)}</text>
				<!-- blade start hole, just inside the line -->
				<circle cx="-55" cy="78" r={CABLE_HOLE_D / 2} fill="none" stroke="var(--color-danger)" stroke-width="2" />
				<text x="-70" y="108" fill="var(--color-danger)" font-size="17" text-anchor="middle">Ø {bit(CABLE_HOLE_D)} blade entry</text>
				<!-- cut direction -->
				<path d="M -78 60 A 99 99 0 0 1 -97 20" fill="none" stroke="var(--color-danger)" stroke-width="2" />
				<path d="M -101 30 l -2 -12 l 11 5 z" fill="var(--color-danger)" />
				<text x="-152" y="52" fill="var(--color-danger)" font-size="17" text-anchor="middle">cut just inside</text>
			</svg>
		</div>
		<p class="mt-2 text-text-muted">
			Make a trammel from any scrap stick: a small nail through one end, and a pencil through a hole
			<b class="text-text">{L(CENTER_HOLE_D / 2)}</b> away. Tap the nail into the plate center and
			swing a Ø {L(CENTER_HOLE_D)} circle. Drill a blade-entry hole just <i>inside</i> the waste
			with the same {bit(CABLE_HOLE_D)} bit you used for the cable holes, drop the jigsaw blade in,
			and cut around staying about 1&nbsp;mm inside the line, then sand back to the line. The nail
			hole is in the middle of the disc you just removed, so it disappears — and this opening is
			pure clearance, so ±1&nbsp;mm is fine.
		</p>
	</section>

	<!-- STEP 6: corners + finish -->
	<section>
		<h3 class="mb-1 text-xs font-semibold uppercase tracking-wider text-text-muted">
			Step 6 · Cut the corners off, finish
		</h3>
		<p class="text-text-muted">
			Now jigsaw the four corner triangles, staying just <i>outside</i> each pencil line (leave the
			line), and block-sand down to it. For dead-straight edges, clamp a straight board next to the
			line as a fence and run the jigsaw's shoe against it. The original design rounds the six
			corners to a {L(HEX.filletR)} radius — trace any round object about {L(2 * HEX.filletR)} across
			and sand to the mark, or just knock the points off; it's cosmetic.
		</p>
		<p class="mt-2 text-text-muted">
			<b class="text-text">Final checks:</b> opposite flats {L(HEX.acrossFlats)} apart, every side
			{L(HEX.side)}, and neighboring holes within each ring exactly one ring-radius apart
			({L(RING_INNER_R)} inner, {L(RING_OUTER_R)} outer).
		</p>
	</section>
</div>
