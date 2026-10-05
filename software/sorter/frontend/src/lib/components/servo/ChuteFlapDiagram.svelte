<!--
	A cross-section of one storage layer's part of the chute: the tube pieces
	fall down, the funnel out to this layer's bins, and the flap between them,
	hinged at the bottom of the funnel's mouth. Open, the flap lies flat in the
	tube wall and pieces fall on to the layers below; closed, it crosses the
	tube and turns pieces down the funnel. The flap is drawn in the primary,
	everything else in the neutrals. A drawing of the machine, like a chart: its
	small form for buttons is FlapOpenIcon and FlapClosedIcon.
-->
<script lang="ts">
	let {
		state,
		size = 96,
		class: className = ''
	}: {
		state: 'open' | 'closed';
		size?: number;
		class?: string;
	} = $props();

	// The tube's walls, the funnel's mouth in the right wall, and the hinge at
	// the bottom of the mouth. The flap is as long as the mouth is tall.
	const LEFT = 26;
	const RIGHT = 66;
	const MOUTH_TOP = 26;
	const HINGE_Y = 74;
	const FLAP = HINGE_Y - MOUTH_TOP;
	// Closed, the flap's free end rests on the far wall.
	const CLOSED_TIP_Y = HINGE_Y - Math.sqrt(FLAP * FLAP - (RIGHT - LEFT) ** 2);
	// The funnel runs down and out at 30 degrees.
	const FUNNEL_DROP = 0.58;
	const OUT = 116;

	const tip = $derived(state === 'open' ? { x: RIGHT, y: MOUTH_TOP } : { x: LEFT, y: CLOSED_TIP_Y });
	// The flap tapers from the hinge to its tip, as the printed one does.
	const flapOutline = $derived.by(() => {
		const dx = tip.x - RIGHT;
		const dy = tip.y - HINGE_Y;
		const len = Math.hypot(dx, dy);
		const nx = -dy / len;
		const ny = dx / len;
		const at = (x: number, y: number, w: number) =>
			`${x + nx * w},${y + ny * w} ${x - nx * w},${y - ny * w}`;
		const [a, b] = at(RIGHT, HINGE_Y, 4).split(' ');
		const [c, d] = at(tip.x, tip.y, 1.5).split(' ');
		return `${a} ${c} ${d} ${b}`;
	});

	const MID = (LEFT + RIGHT) / 2;
	const flapYAt = (x: number) => HINGE_Y - ((RIGHT - x) * (HINGE_Y - CLOSED_TIP_Y)) / (RIGHT - LEFT);
	const funnelMid = (x: number) => (MOUTH_TOP + HINGE_Y) / 2 + (x - RIGHT) * FUNNEL_DROP + 6;

	const pieceRoute = $derived(
		state === 'open'
			? `M ${MID} 6 L ${MID} 110`
			: `M ${MID} 6 L ${MID} ${flapYAt(MID) - 4} L ${RIGHT + 4} ${HINGE_Y - 8} L ${OUT - 8} ${funnelMid(OUT - 8)}`
	);
	const arrowHead = $derived.by(() => {
		if (state === 'open') return `M ${MID - 4} 104 L ${MID} 111 L ${MID + 4} 104`;
		const x = OUT - 8;
		const y = funnelMid(x);
		return `M ${x - 7} ${y - 6.5} L ${x} ${y} L ${x - 8.5} ${y + 1.5}`;
	});
</script>

<svg
	viewBox="0 0 120 120"
	width={size}
	height={size}
	class="shrink-0 {className}"
	role="img"
	aria-label={state === 'open'
		? 'The flap open: it lies flat in the chute wall and pieces fall on down the chute.'
		: 'The flap closed: it crosses the chute and turns pieces down the funnel into this layer.'}
>
	<g class="stroke-ink-faint" stroke-width="3" stroke-linecap="square" fill="none">
		<!-- The tube: its left wall whole, its right wall broken by the funnel's mouth. -->
		<line x1={LEFT} y1="0" x2={LEFT} y2="120" />
		<line x1={RIGHT} y1="0" x2={RIGHT} y2={MOUTH_TOP} />
		<line x1={RIGHT} y1={HINGE_Y} x2={RIGHT} y2="120" />
		<!-- The funnel, down and out to the bins. -->
		<line x1={RIGHT} y1={MOUTH_TOP} x2={OUT} y2={MOUTH_TOP + (OUT - RIGHT) * FUNNEL_DROP} />
		<line x1={RIGHT} y1={HINGE_Y} x2={OUT} y2={HINGE_Y + (OUT - RIGHT) * FUNNEL_DROP} />
	</g>

	<!-- Where a piece goes. -->
	<g class="stroke-ink-muted" stroke-width="2" fill="none" stroke-linejoin="round" stroke-linecap="round">
		<path d={pieceRoute} stroke-dasharray="4 4" />
		<path d={arrowHead} />
	</g>

	<!-- The flap, and its hinge. -->
	<polygon points={flapOutline} class="fill-primary stroke-primary" stroke-width="1.5" stroke-linejoin="round" />
	<circle cx={RIGHT} cy={HINGE_Y} r="4.5" class="fill-surface stroke-primary" stroke-width="2.5" />
</svg>
