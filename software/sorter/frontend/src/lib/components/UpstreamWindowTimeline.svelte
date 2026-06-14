<script lang="ts">
	// Draggable visualization of the per-channel search windows. Time runs along
	// the x-axis as "seconds before the piece arrived at C4": older on the left,
	// arrival at 0, a little into the future on the right. Each channel's window
	// is a draggable band; where the two bands overlap in time is shaded so you
	// can see how much of the search range C2 and C3 share.
	let { values = $bindable() }: { values: Record<string, number | boolean> } = $props();

	const ROWS = [
		{ label: 'C2', startKey: 'ch2_window_start_s', endKey: 'ch2_window_end_s', band: 'border-info bg-info/25', grip: 'bg-info' },
		{ label: 'C3', startKey: 'ch3_window_start_s', endKey: 'ch3_window_end_s', band: 'border-warning bg-warning/25', grip: 'bg-warning' }
	];

	const MIN_GAP = 1;
	const TICK = 15;

	function num(key: string, fallback: number): number {
		const v = values[key];
		return typeof v === 'number' && !Number.isNaN(v) ? v : fallback;
	}
	function round(v: number): number {
		return Math.round(v * 10) / 10;
	}

	let starts = $derived(ROWS.map((r) => num(r.startKey, 0)));
	let ends = $derived(ROWS.map((r) => num(r.endKey, 0)));

	let domainMax = $derived(Math.max(60, Math.ceil(Math.max(...starts, 0) / TICK) * TICK));
	let domainMin = $derived(Math.min(-10, Math.floor(Math.min(...ends, 0) / TICK) * TICK));

	let ticks = $derived.by(() => {
		const out: number[] = [];
		for (let v = Math.ceil(domainMax / TICK) * TICK; v >= domainMin; v -= TICK) out.push(v);
		return out;
	});

	function xPct(sba: number): number {
		return ((domainMax - sba) / (domainMax - domainMin)) * 100;
	}

	function edgeLabel(sba: number): string {
		if (Math.abs(sba) < 0.001) return 'arrival';
		return sba > 0 ? `${round(sba)}s ago` : `${round(-sba)}s future`;
	}

	let overlap = $derived.by(() => {
		const older = Math.min(starts[0], starts[1]);
		const newer = Math.max(ends[0], ends[1]);
		if (older > newer) return { left: xPct(older), width: xPct(newer) - xPct(older), secs: round(older - newer) };
		return null;
	});

	let active = $derived(Boolean(values['per_channel_window']));

	let trackEl = $state<HTMLDivElement | null>(null);
	let drag = $state<null | { i: number; mode: 'start' | 'end' | 'move'; grab: number; s0: number; e0: number }>(null);

	function clamp(v: number, lo: number, hi: number): number {
		return Math.min(hi, Math.max(lo, v));
	}
	function snap(v: number): number {
		return Math.round(v);
	}
	function sbaAt(clientX: number): number {
		if (!trackEl) return 0;
		const rect = trackEl.getBoundingClientRect();
		const frac = clamp((clientX - rect.left) / rect.width, 0, 1);
		return domainMax - frac * (domainMax - domainMin);
	}

	function setStart(i: number, sba: number) {
		values[ROWS[i].startKey] = snap(clamp(sba, ends[i] + MIN_GAP, domainMax));
	}
	function setEnd(i: number, sba: number) {
		values[ROWS[i].endKey] = snap(clamp(sba, domainMin, starts[i] - MIN_GAP));
	}
	function setBoth(i: number, s: number, e: number) {
		if (s > domainMax) {
			const o = s - domainMax;
			s -= o;
			e -= o;
		}
		if (e < domainMin) {
			const o = domainMin - e;
			s += o;
			e += o;
		}
		values[ROWS[i].startKey] = snap(s);
		values[ROWS[i].endKey] = snap(e);
	}

	function onMove(e: PointerEvent) {
		if (!drag) return;
		const sba = sbaAt(e.clientX);
		if (drag.mode === 'start') setStart(drag.i, sba);
		else if (drag.mode === 'end') setEnd(drag.i, sba);
		else setBoth(drag.i, drag.s0 + (sba - drag.grab), drag.e0 + (sba - drag.grab));
	}
	function onUp() {
		drag = null;
		window.removeEventListener('pointermove', onMove);
		window.removeEventListener('pointerup', onUp);
	}
	function onDown(e: PointerEvent, i: number, mode: 'start' | 'end' | 'move') {
		e.preventDefault();
		drag = { i, mode, grab: sbaAt(e.clientX), s0: starts[i], e0: ends[i] };
		window.addEventListener('pointermove', onMove);
		window.addEventListener('pointerup', onUp);
	}
	function onKey(e: KeyboardEvent, i: number, mode: 'start' | 'end' | 'move') {
		const d = e.key === 'ArrowLeft' ? 1 : e.key === 'ArrowRight' ? -1 : 0;
		if (!d) return;
		e.preventDefault();
		if (mode === 'start') setStart(i, starts[i] + d);
		else if (mode === 'end') setEnd(i, ends[i] + d);
		else setBoth(i, starts[i] + d, ends[i] + d);
	}
</script>

<div class="flex flex-col gap-3 border border-border bg-bg p-4">
	<div class="flex items-center justify-between gap-3">
		<div class="text-xs font-semibold uppercase tracking-wider text-text-muted">Window timeline</div>
		{#if !active}
			<span class="text-sm text-text-muted">Per-channel windows are off — drag still edits the values below.</span>
		{:else if overlap}
			<span class="text-sm text-text-muted">C2/C3 overlap: {overlap.secs}s</span>
		{:else}
			<span class="text-sm text-text-muted">No C2/C3 overlap</span>
		{/if}
	</div>

	<div class="relative select-none {active ? '' : 'opacity-50'}" bind:this={trackEl} style="touch-action: none;">
		<div class="relative h-[124px] w-full border border-border bg-surface">
			{#if overlap}
				<div class="absolute bottom-0 top-0 bg-primary/15" style="left: {overlap.left}%; width: {overlap.width}%;"></div>
			{/if}
			<div class="absolute bottom-0 top-0 w-px bg-text" style="left: {xPct(0)}%;"></div>

			{#each ROWS as r, i (r.label)}
				<div
					class="absolute"
					style="top: {i * 58 + 8}px; height: 46px; left: {xPct(starts[i])}%; width: {xPct(ends[i]) - xPct(starts[i])}%;"
				>
					<div class="relative h-full border-2 {r.band}">
						<div
							class="absolute bottom-0 left-0 top-0 w-2.5 cursor-ew-resize {r.grip}"
							role="slider"
							tabindex="0"
							aria-label={`${r.label} window older edge`}
							aria-valuemin={domainMin}
							aria-valuemax={domainMax}
							aria-valuenow={starts[i]}
							onpointerdown={(e) => onDown(e, i, 'start')}
							onkeydown={(e) => onKey(e, i, 'start')}
						></div>
						<div
							class="absolute bottom-0 left-2.5 right-2.5 top-0 cursor-grab"
							role="button"
							tabindex="0"
							aria-label={`${r.label} window move`}
							onpointerdown={(e) => onDown(e, i, 'move')}
							onkeydown={(e) => onKey(e, i, 'move')}
						></div>
						<div
							class="absolute bottom-0 right-0 top-0 w-2.5 cursor-ew-resize {r.grip}"
							role="slider"
							tabindex="0"
							aria-label={`${r.label} window newer edge`}
							aria-valuemin={domainMin}
							aria-valuemax={domainMax}
							aria-valuenow={ends[i]}
							onpointerdown={(e) => onDown(e, i, 'end')}
							onkeydown={(e) => onKey(e, i, 'end')}
						></div>
						<div class="pointer-events-none absolute inset-0 flex items-center justify-center text-sm font-semibold text-text">
							{r.label}
						</div>
					</div>
				</div>
			{/each}
		</div>

		<div class="relative mt-1 h-5 w-full">
			{#each ticks as t (t)}
				<div class="absolute -translate-x-1/2 text-xs text-text-muted" style="left: {xPct(t)}%;">
					{t === 0 ? '0' : t > 0 ? `${t}` : `+${-t}`}
				</div>
			{/each}
		</div>
		<div class="mt-0.5 text-xs text-text-muted">seconds before arrival · left = older, 0 = arrival, right = future</div>
	</div>

	<div class="flex flex-wrap gap-x-6 gap-y-1 text-sm text-text-muted">
		{#each ROWS as r, i (r.label)}
			<span><span class="font-semibold text-text">{r.label}:</span> {edgeLabel(starts[i])} → {edgeLabel(ends[i])}</span>
		{/each}
	</div>
</div>
