<script lang="ts">
	// Stacked time-series panels for StallGuard telemetry. Each signal gets its own
	// panel on its own real scale — SG_RESULT (0..512), TSTEP (log, decades differ
	// by 1000x within one move), CS_ACTUAL (0..31). They share the time axis and the
	// green velocity-gate shading, so a stall in SG lines up with where TSTEP is
	// actually below tcoolthrs. No charting dependency — plain canvas, builds on the Pi.

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
		cruiseTstep = null,
		showCs = false,
		showTstep = true,
		height = 420,
	}: {
		points?: Point[];
		triggerLevel?: number | null;
		sgMean?: number | null;
		// TCOOLTHRS velocity gate (TSTEP units). DIAG only fires while TSTEP <= this,
		// so samples at/below it are the protected window; null hides the gate overlay.
		cruiseTstep?: number | null;
		showCs?: boolean;
		showTstep?: boolean;
		height?: number;
	} = $props();

	let canvas = $state<HTMLCanvasElement | null>(null);
	let wrapper = $state<HTMLDivElement | null>(null);
	let width = $state(800);
	// Cursor position over the canvas (CSS px), null when not hovering. Drives the
	// crosshair + value box; the chart snaps to the nearest sample by time.
	let hoverPx = $state<number | null>(null);
	let hoverPy = $state<number | null>(null);

	const SG_MAX = 512;
	const CS_MAX = 31;
	const PAD = { top: 16, right: 16, bottom: 30, left: 48 };
	const PANEL_GAP = 26;

	function cssVar(name: string, fallback: string): string {
		if (typeof window === 'undefined' || !canvas) return fallback;
		const v = getComputedStyle(canvas).getPropertyValue(name).trim();
		return v || fallback;
	}

	// Samples with a valid TSTEP reading, in time order — the basis for every gate calc.
	function tstepPoints(): { x: number; tstep: number }[] {
		return points
			.filter((p) => p.tstep != null && (p.tstep as number) > 0)
			.map((p) => ({ x: p.x, tstep: p.tstep as number }));
	}

	// Contiguous time spans where TSTEP <= cruiseTstep (gate open, DIAG armed). Each
	// span is extended to the midpoint toward its out-of-gate neighbours so a lone
	// in-gate sample still paints a visible band rather than a zero-width sliver.
	function gateSegments(): { x0: number; x1: number }[] {
		if (cruiseTstep == null) return [];
		const pts = tstepPoints();
		if (pts.length === 0) return [];
		const open = (i: number) => pts[i].tstep <= (cruiseTstep as number);
		const segs: { x0: number; x1: number }[] = [];
		let i = 0;
		while (i < pts.length) {
			if (!open(i)) {
				i++;
				continue;
			}
			let j = i;
			while (j + 1 < pts.length && open(j + 1)) j++;
			const x0 = i > 0 ? (pts[i - 1].x + pts[i].x) / 2 : pts[i].x;
			const x1 = j < pts.length - 1 ? (pts[j].x + pts[j + 1].x) / 2 : pts[j].x;
			segs.push({ x0, x1 });
			i = j + 1;
		}
		return segs;
	}

	// Sample interval is ~constant, so gate-open time is fraction-of-samples * duration.
	// ramp = time from move start until the gate first opens (accel eaten before cruise).
	function gateStats(): { pct: number; openSec: number; dur: number; ramp: number | null } | null {
		if (cruiseTstep == null) return null;
		const pts = tstepPoints();
		if (pts.length === 0) return null;
		const xs = points.map((p) => p.x);
		const dur = (xs.length ? Math.max(...xs) - Math.min(...xs) : 0) || 0;
		const inGate = pts.filter((p) => p.tstep <= (cruiseTstep as number));
		const pct = (inGate.length / pts.length) * 100;
		const ramp = inGate.length ? inGate[0].x - Math.min(...xs) : null;
		return { pct, openSec: dur * (inGate.length / pts.length), dur, ramp };
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
		const colBg = cssVar('--color-bg', '#ffffff');

		ctx.font = '11px ui-sans-serif, system-ui, sans-serif';

		const plotW = width - PAD.left - PAD.right;
		const x0 = PAD.left;

		const xs = points.map((p) => p.x);
		const xMin = xs.length ? Math.min(...xs) : 0;
		const xMax = xs.length ? Math.max(...xs) : 1;
		const xSpan = xMax - xMin || 1;
		const sx = (x: number) => x0 + ((x - xMin) / xSpan) * plotW;

		// Sample nearest the cursor's time, for the crosshair + value box.
		let hoverPoint: Point | null = null;
		let hoverXPix = 0;
		if (hoverPx != null && points.length) {
			let best = Infinity;
			for (const p of points) {
				const d = Math.abs(sx(p.x) - hoverPx);
				if (d < best) {
					best = d;
					hoverPoint = p;
				}
			}
			if (hoverPoint) hoverXPix = sx(hoverPoint.x);
		}

		// Which panels are active and how tall each is (SG is the primary, gets more).
		type PanelKey = 'sg' | 'tstep' | 'cs';
		const panels: { key: PanelKey; weight: number }[] = [{ key: 'sg', weight: 1.7 }];
		if (showTstep) panels.push({ key: 'tstep', weight: 1.3 });
		if (showCs) panels.push({ key: 'cs', weight: 1 });
		const totalWeight = panels.reduce((a, p) => a + p.weight, 0);
		const availH = height - PAD.top - PAD.bottom - PANEL_GAP * (panels.length - 1);

		const gateSegs = gateSegments();
		const drawGate = (y0: number, plotH: number) => {
			if (!gateSegs.length) return;
			ctx.fillStyle = colSuccess;
			ctx.globalAlpha = 0.1;
			for (const s of gateSegs) {
				const X0 = sx(s.x0);
				const X1 = sx(s.x1);
				ctx.fillRect(X0, y0, Math.max(1, X1 - X0), plotH);
			}
			ctx.globalAlpha = 1;
		};

		const drawHLine = (y: number, color: string, dash: number[]) => {
			ctx.strokeStyle = color;
			ctx.setLineDash(dash);
			ctx.lineWidth = 1;
			ctx.beginPath();
			ctx.moveTo(x0, y);
			ctx.lineTo(x0 + plotW, y);
			ctx.stroke();
			ctx.setLineDash([]);
		};

		// Plot a series given a value->y mapping; breaks the line on null/invalid.
		const drawSeries = (
			valueOf: (p: Point) => number | null,
			sy: (v: number) => number,
			color: string,
			lineWidth: number
		) => {
			ctx.strokeStyle = color;
			ctx.lineWidth = lineWidth;
			ctx.beginPath();
			let started = false;
			for (const p of points) {
				const v = valueOf(p);
				if (v == null) {
					started = false;
					continue;
				}
				const X = sx(p.x);
				const Y = sy(v);
				started ? ctx.lineTo(X, Y) : ctx.moveTo(X, Y);
				started = true;
			}
			ctx.stroke();
		};

		const drawXAxis = (y0: number, plotH: number, withLabels: boolean) => {
			ctx.textAlign = 'center';
			ctx.textBaseline = 'top';
			const ticks = 5;
			for (let i = 0; i <= ticks; i++) {
				const xv = xMin + (xSpan * i) / ticks;
				const x = sx(xv);
				ctx.strokeStyle = colBorder;
				ctx.globalAlpha = 0.6;
				ctx.beginPath();
				ctx.moveTo(x, y0);
				ctx.lineTo(x, y0 + plotH);
				ctx.stroke();
				ctx.globalAlpha = 1;
				if (withLabels) {
					ctx.fillStyle = colMuted;
					ctx.fillText(`${(xv - xMin).toFixed(1)}s`, x, y0 + plotH + 6);
				}
			}
		};

		const drawFrameTitle = (y0: number, plotH: number, title: string, color: string) => {
			ctx.strokeStyle = colText;
			ctx.globalAlpha = 0.25;
			ctx.strokeRect(x0, y0, plotW, plotH);
			ctx.globalAlpha = 1;
			ctx.fillStyle = color;
			ctx.textAlign = 'left';
			ctx.textBaseline = 'top';
			ctx.font = '600 11px ui-sans-serif, system-ui, sans-serif';
			ctx.fillText(title, x0 + 4, y0 + 3);
			ctx.font = '11px ui-sans-serif, system-ui, sans-serif';
		};

		const yLabel = (text: string, y: number, color: string) => {
			ctx.fillStyle = color;
			ctx.textAlign = 'right';
			ctx.textBaseline = 'middle';
			ctx.fillText(text, x0 - 6, y);
		};

		if (points.length === 0) {
			ctx.fillStyle = colMuted;
			ctx.textAlign = 'center';
			ctx.textBaseline = 'middle';
			ctx.fillText('No samples', x0 + plotW / 2, height / 2);
			return;
		}

		let cursorY = PAD.top;
		panels.forEach((panel, idx) => {
			const plotH = (availH * panel.weight) / totalWeight;
			const y0 = cursorY;
			const isLast = idx === panels.length - 1;

			drawGate(y0, plotH);
			drawXAxis(y0, plotH, isLast);
			if (hoverPoint) {
				ctx.strokeStyle = colMuted;
				ctx.globalAlpha = 0.7;
				ctx.setLineDash([3, 3]);
				ctx.lineWidth = 1;
				ctx.beginPath();
				ctx.moveTo(hoverXPix, y0);
				ctx.lineTo(hoverXPix, y0 + plotH);
				ctx.stroke();
				ctx.setLineDash([]);
				ctx.globalAlpha = 1;
			}

			if (panel.key === 'sg') {
				const sy = (v: number) =>
					y0 + plotH - (Math.max(0, Math.min(SG_MAX, v)) / SG_MAX) * plotH;
				for (const gv of [0, 128, 256, 384, 512]) {
					const y = sy(gv);
					drawHLine(y, colBorder, []);
					yLabel(String(gv), y, colMuted);
				}
				if (sgMean != null) drawHLine(sy(sgMean), colMuted, [2, 3]);
				if (triggerLevel != null) {
					const y = sy(triggerLevel);
					drawHLine(y, colDanger, [6, 4]);
					ctx.fillStyle = colDanger;
					ctx.textAlign = 'left';
					ctx.textBaseline = 'bottom';
					ctx.fillText(`trigger ≤ ${triggerLevel}`, x0 + 4, y - 2);
				}
				drawSeries((p) => (p.sg != null && p.sg >= 0 ? p.sg : null), sy, colPrimary, 1.5);
				if (hoverPoint && hoverPoint.sg != null && hoverPoint.sg >= 0) {
					ctx.fillStyle = colPrimary;
					ctx.beginPath();
					ctx.arc(hoverXPix, sy(hoverPoint.sg), 3, 0, Math.PI * 2);
					ctx.fill();
				}

				const stats = gateStats();
				if (stats) {
					ctx.fillStyle = colMuted;
					ctx.textAlign = 'right';
					ctx.textBaseline = 'top';
					const ramp =
						stats.ramp != null ? ` · ramp ${stats.ramp.toFixed(1)}s` : ' · never opens';
					ctx.fillText(
						`gate open ${stats.openSec.toFixed(1)}s / ${stats.dur.toFixed(1)}s (${Math.round(
							stats.pct
						)}%)${ramp}`,
						x0 + plotW - 4,
						y0 + 3
					);
				}
				drawFrameTitle(y0, plotH, 'SG_RESULT', colPrimary);
			} else if (panel.key === 'tstep') {
				const tvals = tstepPoints().map((p) => p.tstep);
				const dataLo = tvals.length ? Math.min(...tvals) : 1;
				const dataHi = tvals.length ? Math.max(...tvals) : 10;
				// Pad the log range a little and include tcoolthrs so its line is in view.
				const lo = Math.max(1, Math.min(dataLo, cruiseTstep ?? dataLo) * 0.9);
				const hi = Math.max(dataHi, cruiseTstep ?? dataHi) * 1.1;
				const lLo = Math.log10(lo);
				const lHi = Math.log10(hi) || lLo + 1;
				const lSpan = lHi - lLo || 1;
				// Low TSTEP (fast/cruise) at the bottom; gate band sits below the line.
				const sy = (v: number) =>
					y0 + ((lHi - Math.log10(Math.max(lo, Math.min(hi, v)))) / lSpan) * plotH;
				for (const gv of [100, 1000, 10000, 100000]) {
					if (gv < lo || gv > hi) continue;
					const y = sy(gv);
					drawHLine(y, colBorder, []);
					yLabel(gv >= 1000 ? `${gv / 1000}k` : String(gv), y, colMuted);
				}
				if (cruiseTstep != null && cruiseTstep >= lo && cruiseTstep <= hi) {
					const y = sy(cruiseTstep);
					drawHLine(y, colSuccess, [4, 3]);
					ctx.fillStyle = colSuccess;
					ctx.textAlign = 'left';
					ctx.textBaseline = 'bottom';
					ctx.fillText(`tcoolthrs ${cruiseTstep} (gate ≤ here)`, x0 + 4, y - 2);
				}
				drawSeries(
					(p) => (p.tstep != null && p.tstep > 0 ? p.tstep : null),
					sy,
					colSuccess,
					1.25
				);
				if (hoverPoint && hoverPoint.tstep != null && hoverPoint.tstep > 0) {
					ctx.fillStyle = colSuccess;
					ctx.beginPath();
					ctx.arc(hoverXPix, sy(hoverPoint.tstep), 3, 0, Math.PI * 2);
					ctx.fill();
				}
				drawFrameTitle(y0, plotH, 'TSTEP (log, lower = faster)', colSuccess);
			} else {
				const sy = (v: number) =>
					y0 + plotH - (Math.max(0, Math.min(CS_MAX, v)) / CS_MAX) * plotH;
				for (const gv of [0, 16, 31]) {
					const y = sy(gv);
					drawHLine(y, colBorder, []);
					yLabel(String(gv), y, colMuted);
				}
				drawSeries((p) => (p.cs != null && p.cs >= 0 ? p.cs : null), sy, colWarning, 1.25);
				if (hoverPoint && hoverPoint.cs != null && hoverPoint.cs >= 0) {
					ctx.fillStyle = colWarning;
					ctx.beginPath();
					ctx.arc(hoverXPix, sy(hoverPoint.cs), 3, 0, Math.PI * 2);
					ctx.fill();
				}
				drawFrameTitle(y0, plotH, 'CS_ACTUAL', colWarning);
			}

			cursorY += plotH + PANEL_GAP;
		});

		// Value box following the cursor — the readout for the snapped sample.
		if (hoverPoint) {
			const fmt = (v: number | null, ok: boolean) => (v != null && ok ? String(v) : '—');
			const lines = [`t ${(hoverPoint.x - xMin).toFixed(2)}s`];
			lines.push(`SG ${fmt(hoverPoint.sg, hoverPoint.sg != null && hoverPoint.sg >= 0)}`);
			if (showTstep)
				lines.push(`TSTEP ${fmt(hoverPoint.tstep, hoverPoint.tstep != null && hoverPoint.tstep > 0)}`);
			if (showCs) lines.push(`CS ${fmt(hoverPoint.cs, hoverPoint.cs != null && hoverPoint.cs >= 0)}`);

			const lineH = 14;
			const boxW = Math.max(...lines.map((l) => ctx.measureText(l).width)) + 12;
			const boxH = lines.length * lineH + 6;
			let bx = hoverXPix + 10;
			if (bx + boxW > x0 + plotW) bx = hoverXPix - 10 - boxW;
			bx = Math.max(x0, Math.min(bx, x0 + plotW - boxW));
			let by = (hoverPy ?? PAD.top) + 8;
			by = Math.max(PAD.top, Math.min(by, height - PAD.bottom - boxH));

			ctx.fillStyle = colBg;
			ctx.globalAlpha = 0.95;
			ctx.fillRect(bx, by, boxW, boxH);
			ctx.globalAlpha = 1;
			ctx.strokeStyle = colBorder;
			ctx.lineWidth = 1;
			ctx.strokeRect(bx, by, boxW, boxH);
			ctx.textAlign = 'left';
			ctx.textBaseline = 'top';
			lines.forEach((l, i) => {
				ctx.fillStyle = i === 0 ? colMuted : colText;
				ctx.fillText(l, bx + 6, by + 4 + i * lineH);
			});
		}
	}

	$effect(() => {
		// touch reactive deps so redraw runs on data/option changes
		void points;
		void triggerLevel;
		void sgMean;
		void cruiseTstep;
		void showCs;
		void showTstep;
		void hoverPx;
		void hoverPy;
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
	<canvas
		bind:this={canvas}
		style="width: 100%; height: {height}px; display: block;"
		onmousemove={(e) => {
			hoverPx = e.offsetX;
			hoverPy = e.offsetY;
		}}
		onmouseleave={() => {
			hoverPx = null;
			hoverPy = null;
		}}
	></canvas>
</div>
