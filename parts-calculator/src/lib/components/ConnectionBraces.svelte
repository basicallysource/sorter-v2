<!--
	The line diagram for an assembly's connection edges: one brace per join
	method, drawn in a tight gutter just right of the node's own rows, spanning
	the rows of every member that method touches. Each tick runs from the row's
	actual right edge to the spine, so the brace visibly holds those rows. Each
	lane gets its own hue, and a tick that crosses another brace's spine hops
	over it, circuit-diagram style, so shared rows stay legible. The brace
	carries one word — the method — and clicking it opens a panel with the
	specifics (from → to, fastener and count, note, draft state). All-draft
	braces draw dashed.

	Renders as an absolutely-positioned overlay inside the node's branch
	container (its parent element), which reserves `gutter` px of right padding
	for it — the page computes that number and passes the same value here. Rows
	are found by the data-member attribute the tree sets on each direct line
	row; everything re-measures on any size change of the branch, so nested
	folds and window resizes keep ticks on their rows.
-->
<script lang="ts" module>
	import type { Connection } from '$lib/filament';

	/** One brace per independent joint: edges of one method split into connected
	 *  components over shared members, so two unrelated self-tapped joints never
	 *  merge into a single spine. Exported because the page sizes each branch's
	 *  gutter off the same grouping. */
	// One brace per fastener: every joint made with the same screws draws as a
	// single spine spanning all the rows those screws touch, the screw row
	// included — the per-pair breakdown lives in the click panel. Fastenerless
	// joints (press, friction, clip…): a same-method chain between plain parts
	// is one pressed-together stack and draws as one spine too, while a joint
	// that touches a sub-assembly is its own discrete step — so a stack of
	// foot, extensions and leg is one line, but two things that merely
	// friction-fit the same unit stay two.
	export function braceGroups(edges: Connection[], isAssembly: (id: string) => boolean = () => false) {
		const keyOf = new Map<Connection, string>();
		for (const e of edges) {
			if (e.via) keyOf.set(e, `${e.method}:via:${e.via}`);
			else if (isAssembly(e.from) || isAssembly(e.to)) keyOf.set(e, `${e.method}:${e.from}>${e.to}`);
		}
		// part-to-part fastenerless chains: merge per method over shared members
		const chains = edges.filter((e) => !keyOf.has(e));
		const comps: Connection[][] = [];
		for (const e of chains) {
			const mine = new Set([e.from, e.to]);
			const touching = comps.filter(
				(c) => c[0].method === e.method && c.some((o) => mine.has(o.from) || mine.has(o.to))
			);
			for (const t of touching) comps.splice(comps.indexOf(t), 1);
			comps.push([...touching.flat(), e]);
		}
		for (const c of comps) {
			const members = [...new Set(c.flatMap((e) => [e.from, e.to]))].sort();
			for (const e of c) keyOf.set(e, `${e.method}:run:${members.join('+')}`);
		}
		const joints = new Map<string, Connection[]>();
		for (const e of edges) {
			const key = keyOf.get(e)!;
			joints.set(key, [...(joints.get(key) ?? []), e]);
		}
		return [...joints].map(([key, es]) => ({
			key,
			method: es[0].method,
			edges: es,
			ids: [...new Set(es.flatMap((e) => [e.from, e.to, ...(e.via ? [e.via] : [])]))],
			draft: es.every((e) => e.draft)
		}));
	}

</script>

<script lang="ts">
	let {
		edges,
		gutter,
		isAssembly = () => false,
		labelOf,
		nameOf,
		travelOf = () => null
	}: {
		edges: Connection[];
		gutter: number;
		/** Which member ids are sub-assemblies — steers fastenerless grouping. */
		isAssembly?: (id: string) => boolean;
		labelOf: (method: string) => string;
		nameOf: (id: string) => string;
		/** How far a fastener line reaches through a joint (nominal length,
		 *  less the head for countersunk — see screwTravel in filament.ts). */
		travelOf?: (id: string) => number | null;
	} = $props();

	// A screw needs at least this much thread engagement to count as holding.
	const MIN_BITE_MM = 2;
	const mm = (n: number) => (Math.round(n * 100) / 100).toString();

	let host = $state<HTMLElement | null>(null);
	let open = $state<number | null>(null);
	// Hovering a brace focuses it: the other braces fade and the rows this one
	// holds get a hairline ring in its color. An open popover pins the focus.
	let hover = $state<number | null>(null);
	const hot = $derived(open ?? hover);
	$effect(() => {
		const parent = host?.parentElement;
		if (!parent || hot === null) return;
		const g = groups[hot];
		if (!g) return;
		const color = colorOf(hot);
		const els = g.ids
			.map((id) => parent.querySelector(`:scope > [data-member="${CSS.escape(id)}"]`))
			.filter((el): el is HTMLElement => el instanceof HTMLElement);
		for (const el of els) el.style.boxShadow = `inset 0 0 0 1px ${color}`;
		return () => {
			for (const el of els) el.style.boxShadow = '';
		};
	});

	// One hue per join method, the same everywhere — friction is always
	// friction-colored. Pure red and the success green stay clear of the
	// palette; the diff views own those. When two braces in one gutter land
	// on close hues AND overlap vertically, the later one hue-shifts (below).
	const METHOD_HUE: Record<string, number> = {
		'self-tap': 35, // amber
		thread: 215, // blue
		friction: 170, // teal
		clip: 260, // purple
		gravity: 315, // magenta
		press: 55, // olive
		insert: 190, // cyan
		nut: 240, // indigo
		tnut: 285, // violet
		glue: 20, // rust
		solder: 100, // moss
		crimp: 335 // pink
	};
	let hueShift = $state<number[]>([]);
	const hueOf = (i: number) =>
		((METHOD_HUE[groups[i]?.method] ?? 0) + (hueShift[i] ?? 0)) % 360;
	const colorOf = (i: number) => `hsl(${hueOf(i)} 60% 38%)`;
	// The innermost lane keeps a real distance from the rows so every tick has
	// a visible run — a 12px nub against a box border reads as no line at all.
	const laneX = (i: number) => 24 + i * 16;

	const groups = $derived(braceGroups(edges, isAssembly));

	type Span = { ticks: { y: number; from: number }[]; top: number; bottom: number; labelY: number };
	let spans = $state<Span[]>([]);
	let laneOf = $state<number[]>([]);
	let height = $state(0);

	function measure() {
		const parent = host?.parentElement;
		if (!parent) return;
		const pr = parent.getBoundingClientRect();
		height = pr.height;
		const hostLeft = pr.right - gutter;
		const next: Span[] = groups.map((g) => {
			const ticks: { y: number; from: number }[] = [];
			for (const id of g.ids) {
				const el = parent.querySelector(`:scope > [data-member="${CSS.escape(id)}"]`);
				if (el) {
					const r = el.getBoundingClientRect();
					ticks.push({ y: r.top - pr.top + r.height / 2, from: r.right - hostLeft });
				}
			}
			return { ticks, top: 0, bottom: 0, labelY: 0 };
		});
		// The brace spanning the fewest rows sits closest to them, so a wide
		// brace never has to thread through a narrow one.
		const heightOf = (s: Span) =>
			s.ticks.length ? Math.max(...s.ticks.map((t) => t.y)) - Math.min(...s.ticks.map((t) => t.y)) : 0;
		const rank = next
			.map((s, i) => ({ h: heightOf(s), i }))
			.sort((a, b) => a.h - b.h)
			.map(({ i }) => i);
		const lanes = next.map((_, i) => rank.indexOf(i));
		// Braces ticking the same row must not overlap there: nudge each shared
		// tick a few px toward the side the rest of its own brace lies on, so
		// one brace visibly ends where the other begins.
		const clusters = new Map<number, { t: { y: number; from: number }; s: Span }[]>();
		for (const s of next)
			for (const t of s.ticks) {
				const key = Math.round(t.y);
				clusters.set(key, [...(clusters.get(key) ?? []), { t, s }]);
			}
		for (const c of clusters.values()) {
			if (c.length < 2) continue;
			const side = (e: (typeof c)[number]) => {
				const others = e.s.ticks.filter((o) => o !== e.t);
				if (!others.length) return 0;
				const mean = others.reduce((a, o) => a + o.y, 0) / others.length;
				return Math.sign(mean - e.t.y);
			};
			c.sort((a, b) => side(a) - side(b));
			c.forEach((e, k) => (e.t.y += (k - (c.length - 1) / 2) * 5));
		}
		for (const s of next) {
			s.ticks.sort((a, b) => a.y - b.y);
			s.top = s.ticks.length ? s.ticks[0].y : 0;
			s.bottom = s.ticks.length ? s.ticks[s.ticks.length - 1].y : 0;
			s.labelY = (s.top + s.bottom) / 2;
		}
		// Same-ish hue + overlapping spans would read as one brace: shift the
		// later one around the wheel until they part. Two braces of the SAME
		// method keep their exact hue — the color is the method's identity, and
		// their separate lanes and labels already tell them apart.
		const shifts = next.map(() => 0);
		for (let i = 0; i < next.length; i++)
			for (let j = i + 1; j < next.length; j++) {
				if (groups[i].method === groups[j].method) continue;
				const a = next[i];
				const b = next[j];
				if (!a.ticks.length || !b.ticks.length) continue;
				if (a.bottom < b.top || b.bottom < a.top) continue;
				const ha = (METHOD_HUE[groups[i].method] ?? 0) + shifts[i];
				const hb = (METHOD_HUE[groups[j].method] ?? 0) + shifts[j];
				const d = Math.abs(((ha - hb + 540) % 360) - 180);
				if (d < 30) shifts[j] += 45;
			}
		hueShift = shifts;
		laneOf = lanes;
		spans = next;
	}
	$effect(() => {
		void groups;
		void gutter;
		measure();
		const parent = host?.parentElement;
		if (!parent) return;
		const ro = new ResizeObserver(measure);
		ro.observe(parent);
		return () => ro.disconnect();
	});

	function onWinClick(e: MouseEvent) {
		if (open !== null && !host?.contains(e.target as Node)) open = null;
	}
</script>

<svelte:window onclick={onWinClick} onkeydown={(e) => e.key === 'Escape' && (open = null)} />

{#snippet jointDetails(g: ReturnType<typeof braceGroups>[number], i: number)}
	{#each g.edges as e, j (j)}
		<div class={j > 0 ? 'mt-1.5 border-t border-border/60 pt-1.5' : ''}>
			<div class="flex flex-wrap items-baseline gap-x-1.5">
				<span class="font-semibold text-text">{nameOf(e.from)}</span>
				<span class="text-text-muted">→</span>
				<span class="font-semibold text-text">{nameOf(e.to)}</span>
				{#if e.draft}
					<span
						class="border border-dashed border-warning/60 px-1 py-px text-[10px] font-semibold uppercase tracking-wider text-warning-dark"
						title="Extracted from prose — not yet confirmed at the bench">draft</span>
				{/if}
			</div>
			<div class="text-text-muted">
				{#if e.via}{e.qty} × {nameOf(e.via)}{:else}{labelOf(e.method)}{e.qty > 1 ? ` — ${e.qty} places` : ''}{/if}
			</div>
			{#if e.through_mm || e.thread_mm}
				<!-- The screw's journey to scale: pass-through, then the thread
				     waiting for it, a marker at the actual screw's length. Both
				     depths known = a computable valid-length range. -->
				{@const th = e.through_mm ?? 0}
				{@const tr = e.thread_mm ?? 0}
				{@const len = e.via ? travelOf(e.via) : null}
				{@const span = Math.max(th + tr, len ?? 0)}
				{@const lo = th + MIN_BITE_MM}
				{@const hi = th + tr}
				{@const fits = len != null && th > 0 && tr > 0 && len >= lo && len <= hi}
				<div class="relative mt-1.5 h-3 w-full">
					{#if th}
						<div class="absolute inset-y-0 left-0 border border-border bg-[var(--color-bg)]" style="width: {(th / span) * 100}%"></div>
					{/if}
					{#if tr}
						<div
							class="absolute inset-y-0 border"
							style="left: {(th / span) * 100}%; width: {(tr / span) * 100}%; border-color: {colorOf(i)}; background: color-mix(in srgb, {colorOf(i)} 22%, transparent)"
						></div>
					{/if}
					{#if len != null}
						<div class="absolute -inset-y-0.5 w-px bg-text" style="left: {(len / span) * 100}%" title="the screw reaches {mm(len)} mm"></div>
					{/if}
				</div>
				<div class="text-[11px] text-text-muted">
					{#if th}{mm(th)} mm through{/if}{#if th && tr}{' · '}{/if}{#if tr}{mm(tr)} mm thread{/if}{#if th && tr && hi > lo}{` · fits ${mm(lo)}–${mm(hi)} mm`}{/if}{#if len != null && th && tr}
						<span class={fits ? 'text-success' : 'text-warning-dark'}>{` · reaches ${mm(len)} mm — ${fits ? 'fits' : 'out of range'}`}</span>{/if}
				</div>
			{/if}
			{#if e.note}<div class="mt-0.5 text-text-muted">{e.note}</div>{/if}
		</div>
	{/each}
{/snippet}

<div bind:this={host} class="pointer-events-none absolute inset-y-0 right-0" style="width: {gutter}px">
	<svg class="absolute left-0 top-0 overflow-visible" width={gutter} {height} aria-hidden="true">
		{#each groups as g, i (g.key)}
			{@const s = spans[i]}
			{#if s && s.ticks.length}
				{@const x = laneX(laneOf[i] ?? i)}
				<g class="transition-opacity duration-150" opacity={hot !== null && hot !== i ? 0.15 : 1}>
					<path
						d="M {x} {s.top} V {s.bottom}"
						stroke={colorOf(i)}
						stroke-width="1"
						fill="none"
						stroke-dasharray={g.draft ? '3,3' : undefined}
					/>
					{#each s.ticks as t (t.y)}
						<path d="M {t.from} {t.y} H {x}" stroke={colorOf(i)} stroke-width="1" fill="none" />
					{/each}
				</g>
			{/if}
		{/each}
	</svg>
	{#each groups as g, i (g.key)}
		{@const s = spans[i]}
		{#if s && s.ticks.length}
			<!-- The method name sits IN the wire: vertical text centered on the
			     spine, its background masking the line behind it. -->
			<button
				type="button"
				class="pointer-events-auto absolute z-10 whitespace-nowrap bg-surface py-1 text-[10px] font-semibold uppercase tracking-wider transition-opacity duration-150"
				style="left: {laneX(laneOf[i] ?? i)}px; top: {s.labelY}px; transform: translate(-50%, -50%); writing-mode: vertical-rl; color: {colorOf(i)}; opacity: {hot !== null && hot !== i ? 0.15 : 1};"
				aria-expanded={open === i}
				onmouseenter={() => (hover = i)}
				onmouseleave={() => (hover = null)}
				onfocus={() => (hover = i)}
				onblur={() => (hover = null)}
				onclick={() => (open = open === i ? null : i)}
			>
				{labelOf(g.method)}
			</button>
			{#if open === i}
				<div
					class="setup-panel pointer-events-auto absolute right-0 z-30 w-72 p-2.5 text-xs"
					style="top: {s.labelY + 12}px;"
				>
					{@render jointDetails(g, i)}
				</div>
			{/if}
		{/if}
	{/each}
</div>
