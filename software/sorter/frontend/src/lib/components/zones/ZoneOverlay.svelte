<!--
	A channel's zones drawn over its camera picture, and edited there.

	Laid over a picture shown with object-fit: contain, in the zones' own pixels
	(their `frame`), so the shapes sit on the picture at any size and run off its
	edges freely. Each zone has a handle on each edge, on the band pieces ride;
	dragging a zone moves it, the wheel over a zone widens or narrows it.
	Dragging the ring's inner or outer circle, or the exit's edge, sets that
	radius; the cross in the middle moves the center. The inner circle can sit
	off the center (the hub looks shifted from the camera): its small ring
	moves it alone.
-->
<script lang="ts">
	import {
		angleOf,
		channelPolygon,
		hub,
		innerPoint,
		isLocked,
		moveCenter,
		moveHub,
		moveEdge,
		moveZone,
		polar,
		setRadius,
		svgPath,
		widen,
		zonePolygon,
		zoneSpan,
		type ChannelZones,
		type Part,
		type Point,
		type ZoneName
	} from '$lib/zones/model';

	let {
		zones,
		editing = false,
		selected = null,
		onchange,
		onselect,
		class: className = '',
		style = ''
	}: {
		zones: ChannelZones;
		editing?: boolean;
		selected?: Part | null;
		onchange?: (zones: ChannelZones) => void;
		onselect?: (part: Part | null) => void;
		class?: string;
		style?: string;
	} = $props();

	// Categorical colors drawn over the photo, the live feed's hues.
	const COLOR: Record<ZoneName, string> = {
		drop: 'rgb(0 128 255)',
		exit: 'rgb(255 64 0)',
		precise: 'rgb(255 0 255)'
	};
	const OUTLINE = 'rgb(0 255 255)';
	const ZONES: ZoneName[] = ['drop', 'precise', 'exit'];

	let svg = $state<SVGSVGElement | null>(null);
	let renderedWidth = $state(1);
	// Picture pixels per screen pixel, so handles and lines keep their size on screen.
	const unit = $derived(zones.frame[0] / Math.max(1, renderedWidth));
	const band = $derived((zones.inner_radius + zones.exit_radius) / 2);

	type Drag =
		| { kind: 'edge'; zone: ZoneName; edge: 'start' | 'end' }
		| { kind: 'zone'; zone: ZoneName; lastAngle: number }
		| { kind: 'radius'; which: 'inner_radius' | 'outer_radius' | 'exit_radius' }
		| { kind: 'center'; offset: Point }
		| { kind: 'hub'; offset: Point };
	let drag = $state<Drag | null>(null);

	function inFrame(p: Point): boolean {
		return p[0] >= 0 && p[1] >= 0 && p[0] <= zones.frame[0] && p[1] <= zones.frame[1];
	}

	// Where an edge's handle goes: on the band, or the nearest radius between
	// the ring's circles that is in the picture.
	function edgeHandle(angle: number): Point | null {
		const radii = [band, ...[0.25, 0.75, 0.1, 0.9].map((t) => zones.inner_radius + t * (zones.exit_radius - zones.inner_radius))];
		for (const r of radii) {
			const p = polar(zones.center, r, angle);
			if (inFrame(p)) return p;
		}
		return null;
	}

	function circleHandle(around: Point, radius: number): Point | null {
		for (let a = 0; a < 360; a += 15) {
			const angle = (270 + a) % 360;
			const p = polar(around, radius, angle);
			if (inFrame(p) && !ZONES.some((z) => edgeNear(z, angle))) return p;
		}
		return null;
	}

	function edgeNear(name: ZoneName, angle: number): boolean {
		const span = zoneSpan(zones, name);
		if (!span) return false;
		const d = (a: number) => Math.min(Math.abs(a - angle) % 360, 360 - (Math.abs(a - angle) % 360));
		return d(span.start) < 8 || d(span.end) < 8;
	}

	function toFrame(event: PointerEvent | WheelEvent): Point {
		if (!svg) return [0, 0];
		const m = svg.getScreenCTM();
		if (!m) return [0, 0];
		const p = new DOMPoint(event.clientX, event.clientY).matrixTransform(m.inverse());
		return [p.x, p.y];
	}

	function locked(part: Part): boolean {
		return isLocked(zones, part);
	}

	function begin(event: PointerEvent, next: Drag, part: Part) {
		if (!editing) return;
		onselect?.(part);
		if (locked(part)) return;
		event.preventDefault();
		event.stopPropagation();
		(event.currentTarget as Element).setPointerCapture(event.pointerId);
		drag = next;
	}

	function move(event: PointerEvent) {
		if (!drag || !editing) return;
		const p = toFrame(event);
		const angle = angleOf(zones.center, p);
		if (drag.kind === 'edge') {
			onchange?.(moveEdge(zones, drag.zone, drag.edge, angle));
		} else if (drag.kind === 'zone') {
			const delta = ((angle - drag.lastAngle + 540) % 360) - 180;
			drag = { ...drag, lastAngle: angle };
			onchange?.(moveZone(zones, drag.zone, delta));
		} else if (drag.kind === 'radius') {
			const from = drag.which === 'inner_radius' ? hub(zones) : zones.center;
			onchange?.(setRadius(zones, drag.which, Math.hypot(p[0] - from[0], p[1] - from[1])));
		} else if (drag.kind === 'hub') {
			onchange?.(moveHub(zones, [p[0] - drag.offset[0], p[1] - drag.offset[1]]));
		} else {
			onchange?.(moveCenter(zones, [p[0] - drag.offset[0], p[1] - drag.offset[1]]));
		}
	}

	function end() {
		drag = null;
	}

	function wheel(event: WheelEvent, name: ZoneName) {
		if (!editing || locked(name)) return;
		event.preventDefault();
		onselect?.(name);
		onchange?.(widen(zones, name, event.deltaY < 0 ? 1 : -1));
	}

	const outline = $derived(svgPath(channelPolygon(zones)));

	type Radius = 'inner_radius' | 'outer_radius' | 'exit_radius';
	const rings = $derived(
		(['inner_radius', 'outer_radius'] as const).map((which) => {
			const around = which === 'inner_radius' ? hub(zones) : zones.center;
			return { which, around, radius: zones[which], handle: circleHandle(around, zones[which]) };
		})
	);
	const exitHandle = $derived.by(() => {
		const span = zoneSpan(zones, 'exit');
		if (!span) return null;
		const p = polar(zones.center, zones.exit_radius, (span.start + ((span.end - span.start + 360) % 360) / 2) % 360);
		return inFrame(p) ? p : null;
	});
	const edges = $derived(
		ZONES.flatMap((name) => {
			const span = zoneSpan(zones, name);
			if (!span) return [];
			const which = name === 'precise' ? (['start'] as const) : (['start', 'end'] as const);
			return which.map((edge) => {
				const angle = edge === 'start' ? span.start : span.end;
				const outer = name === 'exit' ? zones.exit_radius : zones.outer_radius;
				return {
					key: `${name}-${edge}`,
					name,
					edge,
					from: innerPoint(zones, angle),
					to: polar(zones.center, outer, angle),
					handle: edgeHandle(angle)
				};
			});
		})
	);

	function radiusLabel(which: Radius): string {
		return which === 'inner_radius' ? 'The ring inner edge' : which === 'outer_radius' ? 'The ring outer edge' : "The exit's outer edge";
	}
</script>

<div class="pointer-events-none {className}" {style} bind:clientWidth={renderedWidth}>
	<svg
		bind:this={svg}
		viewBox="0 0 {zones.frame[0]} {zones.frame[1]}"
		preserveAspectRatio="xMidYMid meet"
		class="h-full w-full overflow-hidden"
		role="group"
		aria-label="Zones"
		onpointermove={move}
		onpointerup={end}
		onpointercancel={end}
	>
		<path d={outline} fill="none" stroke={OUTLINE} stroke-width={1.5 * unit} />
		{#each ZONES as name (name)}
			{@const poly = zonePolygon(zones, name)}
			{#if poly}
				<path
					d={svgPath(poly)}
					fill={COLOR[name]}
					fill-opacity={selected === name ? 0.38 : 0.2}
					stroke={COLOR[name]}
					stroke-opacity={selected === name ? 0.95 : 0.55}
					stroke-width={(selected === name ? 2 : 1) * unit}
					class={editing ? 'pointer-events-auto' : ''}
					style:cursor={editing ? (locked(name) ? 'not-allowed' : 'grab') : 'default'}
					role="button"
					tabindex="-1"
					aria-label="The {name} zone"
					onpointerdown={(e) =>
						begin(e, { kind: 'zone', zone: name, lastAngle: angleOf(zones.center, toFrame(e)) }, name)}
					onwheel={(e) => wheel(e, name)}
				/>
			{/if}
		{/each}

		{#if editing}
			<!-- The ring: drag a circle's handle to set its radius. -->
			{#each rings as ring (ring.which)}
				<circle
					cx={ring.around[0]}
					cy={ring.around[1]}
					r={ring.radius}
					fill="none"
					stroke={OUTLINE}
					stroke-opacity={selected === 'ring' ? 0.9 : 0.45}
					stroke-width={unit}
					stroke-dasharray="{6 * unit} {5 * unit}"
				/>
				{#if ring.handle}
					<circle
						cx={ring.handle[0]}
						cy={ring.handle[1]}
						r={7 * unit}
						fill={OUTLINE}
						stroke="black"
						stroke-width={1.5 * unit}
						class="pointer-events-auto"
						style:cursor={locked('ring') ? 'not-allowed' : 'ew-resize'}
						role="button"
						tabindex="-1"
						aria-label={radiusLabel(ring.which)}
						onpointerdown={(e) => begin(e, { kind: 'radius', which: ring.which }, 'ring')}
					/>
				{/if}
			{/each}

			<!-- The exit's outer edge: where the opening starts to show the next channel. -->
			{#if exitHandle}
				<rect
					x={exitHandle[0] - 6 * unit}
					y={exitHandle[1] - 6 * unit}
					width={12 * unit}
					height={12 * unit}
					fill={COLOR.exit}
					stroke="black"
					stroke-width={1.5 * unit}
					class="pointer-events-auto"
					style:cursor={locked('ring') ? 'not-allowed' : 'ns-resize'}
					role="button"
					tabindex="-1"
					aria-label={radiusLabel('exit_radius')}
					onpointerdown={(e) => begin(e, { kind: 'radius', which: 'exit_radius' }, 'ring')}
				/>
			{/if}

			{#each edges as edge (edge.key)}
				<line
					x1={edge.from[0]}
					y1={edge.from[1]}
					x2={edge.to[0]}
					y2={edge.to[1]}
					stroke={COLOR[edge.name]}
					stroke-width={(selected === edge.name ? 2.5 : 1.5) * unit}
				/>
				{#if edge.handle}
					<circle
						cx={edge.handle[0]}
						cy={edge.handle[1]}
						r={(selected === edge.name ? 9 : 7.5) * unit}
						fill="white"
						stroke={COLOR[edge.name]}
						stroke-width={3 * unit}
						class="pointer-events-auto"
						style:cursor={locked(edge.name) ? 'not-allowed' : 'grab'}
						role="button"
						tabindex="-1"
						aria-label="The {edge.name} zone's {edge.edge === 'start' ? 'first' : 'last'} edge"
						onpointerdown={(e) => begin(e, { kind: 'edge', zone: edge.name, edge: edge.edge }, edge.name)}
					/>
				{/if}
			{/each}

			{#if zones.inner_center && inFrame(zones.inner_center)}
				{@const h = zones.inner_center}
				<g
					class="pointer-events-auto"
					style:cursor={locked('ring') ? 'not-allowed' : 'move'}
					role="button"
					tabindex="-1"
					aria-label="The inner circle's center"
					onpointerdown={(e) => {
						const p = toFrame(e);
						begin(e, { kind: 'hub', offset: [p[0] - h[0], p[1] - h[1]] }, 'ring');
					}}
				>
					<circle cx={h[0]} cy={h[1]} r={7 * unit} fill="transparent" stroke="white" stroke-width={2 * unit} />
				</g>
			{/if}

			{#if inFrame(zones.center)}
				<g
					class="pointer-events-auto"
					style:cursor={locked('ring') ? 'not-allowed' : 'move'}
					role="button"
					tabindex="-1"
					aria-label="The ring's center"
					onpointerdown={(e) => {
						const p = toFrame(e);
						begin(e, { kind: 'center', offset: [p[0] - zones.center[0], p[1] - zones.center[1]] }, 'ring');
					}}
				>
					<circle cx={zones.center[0]} cy={zones.center[1]} r={12 * unit} fill="transparent" />
					<path
						d="M{zones.center[0] - 10 * unit} {zones.center[1]} H{zones.center[0] + 10 * unit} M{zones.center[0]} {zones.center[1] - 10 * unit} V{zones.center[1] + 10 * unit}"
						stroke="white"
						stroke-width={2.5 * unit}
					/>
				</g>
			{/if}
		{/if}
	</svg>
</div>
