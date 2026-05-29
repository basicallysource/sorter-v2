<script lang="ts">
	// Canvas time-series chart for StallGuard telemetry. SG_RESULT is drawn on a
	// real 0..512 axis (its physical range); CS_ACTUAL and TSTEP are optional
	// overlays, min-max normalized to the plot area since their scales differ.
	// No charting dependency — plain canvas so it builds clean on the Pi.

	type Point = {
		x: number; // relative seconds
		sg: number | null;
		cs: number | null;
		tstep: number | null;
	};

	let {
		points = [],
		triggerLevel = null,
		sgMean = null,
		showCs = false,
		showTstep = false,
		height = 340,
	}: {
		points?: Point[];
		triggerLevel?: number | null;
		sgMean?: number | null;
		showCs?: boolean;
		showTstep?: boolean;
		height?: number;
	} = $props();

	let canvas = $state<HTMLCanvasElement | null>(null);
	let wrapper = $state<HTMLDivElement | null>(null);
	let width = $state(800);

	const SG_MAX = 512;
	const PAD = { top: 16, right: 16, bottom: 32, left: 44 };

	function cssVar(name: string, fallback: string): string {
		if (typeof window === 'undefined' || !canvas) return fallback;
		const v = getComputedStyle(canvas).getPropertyValue(name).trim();
		return v || fallback;
	}

	function normalizedSeries(key: 'cs' | 'tstep'): { x: number; v: number }[] {
		const vals = points.filter((p) => p[key] != null && (p[key] as number) >= 0);
		if (vals.length === 0) return [];
		const ys = vals.map((p) => p[key] as number);
		const lo = Math.min(...ys);
		const hi = Math.max(...ys);
		const span = hi - lo || 1;
		return vals.map((p) => ({ x: p.x, v: ((p[key] as number) - lo) / span }));
	}

	function draw() {
		if (!canvas) return;
		const ctx = canvas.getContext('2d');
		if (!ctx) return;

		const dpr = window.devicePixelRatio || 1;
		canvas.width = Math.max(1, Math.floor(width * dpr));
		canvas.height = Math.max(1, Math.floor(height * dpr));
		ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
		ctx.clearRect(0, 0, width, height);

		const colText = cssVar('--color-text', '#1a1a1a');
		const colMuted = cssVar('--color-text-muted', '#7a7770');
		const colBorder = cssVar('--color-border', '#e2e0db');
		const colPrimary = cssVar('--color-primary', '#0055bf');
		const colDanger = cssVar('--color-danger', '#d01012');
		const colWarning = cssVar('--color-warning', '#f2a900');
		const colSuccess = cssVar('--color-success', '#00852b');

		const plotW = width - PAD.left - PAD.right;
		const plotH = height - PAD.top - PAD.bottom;
		const x0 = PAD.left;
		const y0 = PAD.top;

		const xs = points.map((p) => p.x);
		const xMin = xs.length ? Math.min(...xs) : 0;
		const xMax = xs.length ? Math.max(...xs) : 1;
		const xSpan = xMax - xMin || 1;

		const sx = (x: number) => x0 + ((x - xMin) / xSpan) * plotW;
		const sySg = (v: number) => y0 + plotH - (Math.max(0, Math.min(SG_MAX, v)) / SG_MAX) * plotH;
		const syNorm = (v: number) => y0 + plotH - v * plotH;

		// Gridlines + Y axis (SG scale)
		ctx.font = '11px ui-sans-serif, system-ui, sans-serif';
		ctx.textBaseline = 'middle';
		ctx.lineWidth = 1;
		for (const gv of [0, 128, 256, 384, 512]) {
			const y = sySg(gv);
			ctx.strokeStyle = colBorder;
			ctx.beginPath();
			ctx.moveTo(x0, y);
			ctx.lineTo(x0 + plotW, y);
			ctx.stroke();
			ctx.fillStyle = colMuted;
			ctx.textAlign = 'right';
			ctx.fillText(String(gv), x0 - 6, y);
		}

		// X axis labels (time)
		ctx.textAlign = 'center';
		ctx.textBaseline = 'top';
		const ticks = 5;
		for (let i = 0; i <= ticks; i++) {
			const xv = xMin + (xSpan * i) / ticks;
			const x = sx(xv);
			ctx.fillStyle = colMuted;
			ctx.fillText(`${(xv - xMin).toFixed(1)}s`, x, y0 + plotH + 6);
		}

		if (points.length === 0) {
			ctx.fillStyle = colMuted;
			ctx.textAlign = 'center';
			ctx.textBaseline = 'middle';
			ctx.fillText('No samples', x0 + plotW / 2, y0 + plotH / 2);
			return;
		}

		// Optional normalized overlays first (behind SG)
		const drawNorm = (series: { x: number; v: number }[], color: string) => {
			if (series.length === 0) return;
			ctx.strokeStyle = color;
			ctx.globalAlpha = 0.5;
			ctx.lineWidth = 1;
			ctx.beginPath();
			series.forEach((p, i) => {
				const X = sx(p.x);
				const Y = syNorm(p.v);
				i === 0 ? ctx.moveTo(X, Y) : ctx.lineTo(X, Y);
			});
			ctx.stroke();
			ctx.globalAlpha = 1;
		};
		if (showCs) drawNorm(normalizedSeries('cs'), colWarning);
		if (showTstep) drawNorm(normalizedSeries('tstep'), colSuccess);

		// Mean reference (dotted)
		if (sgMean != null) {
			ctx.strokeStyle = colMuted;
			ctx.setLineDash([2, 3]);
			ctx.lineWidth = 1;
			const y = sySg(sgMean);
			ctx.beginPath();
			ctx.moveTo(x0, y);
			ctx.lineTo(x0 + plotW, y);
			ctx.stroke();
			ctx.setLineDash([]);
		}

		// Trigger level (dashed danger line) — where DIAG would fire
		if (triggerLevel != null) {
			ctx.strokeStyle = colDanger;
			ctx.setLineDash([6, 4]);
			ctx.lineWidth = 1.5;
			const y = sySg(triggerLevel);
			ctx.beginPath();
			ctx.moveTo(x0, y);
			ctx.lineTo(x0 + plotW, y);
			ctx.stroke();
			ctx.setLineDash([]);
			ctx.fillStyle = colDanger;
			ctx.textAlign = 'left';
			ctx.textBaseline = 'bottom';
			ctx.fillText(`trigger ≤ ${triggerLevel}`, x0 + 4, y - 2);
		}

		// SG_RESULT line (primary, on top)
		ctx.strokeStyle = colPrimary;
		ctx.lineWidth = 1.5;
		ctx.beginPath();
		let started = false;
		for (const p of points) {
			if (p.sg == null || p.sg < 0) {
				started = false;
				continue;
			}
			const X = sx(p.x);
			const Y = sySg(p.sg);
			started ? ctx.lineTo(X, Y) : ctx.moveTo(X, Y);
			started = true;
		}
		ctx.stroke();
		// axis frame
		ctx.strokeStyle = colText;
		ctx.globalAlpha = 0.25;
		ctx.strokeRect(x0, y0, plotW, plotH);
		ctx.globalAlpha = 1;
	}

	$effect(() => {
		// touch reactive deps so redraw runs on data/option changes
		void points;
		void triggerLevel;
		void sgMean;
		void showCs;
		void showTstep;
		void width;
		void height;
		draw();
	});

	$effect(() => {
		if (!wrapper) return;
		const ro = new ResizeObserver((entries) => {
			for (const e of entries) width = e.contentRect.width;
		});
		ro.observe(wrapper);
		width = wrapper.clientWidth || 800;
		return () => ro.disconnect();
	});
</script>

<div bind:this={wrapper} class="w-full">
	<canvas bind:this={canvas} style="width: 100%; height: {height}px; display: block;"></canvas>
</div>
