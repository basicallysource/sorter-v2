<script lang="ts">
	// Canvas time-series chart for chute-stress TMC2209 telemetry. The signals have
	// very different native scales (SG_RESULT 0..512, CS_ACTUAL 0..31, PWM_SCALE
	// 0..255, TSTEP up to ~1e6), so each enabled series is min-max normalized to the
	// plot area — the diagnostic value here is the *shape and correlation* over time
	// (e.g. PWM_SCALE rising while SG_RESULT falls just before a stall). Absolute
	// ranges are shown in the legend by the parent. No charting dependency so it
	// builds clean offline on the Pi.

	type TelemetryPoint = {
		x: number; // relative seconds
		sg: number | null;
		cs: number | null;
		pwm: number | null;
		tstep: number | null;
		warn: boolean; // otpw or over-temperature flag set on this sample
	};

	type SeriesKey = 'sg' | 'cs' | 'pwm' | 'tstep';

	let {
		points = [],
		showSg = true,
		showCs = true,
		showPwm = true,
		showTstep = false,
		height = 320
	}: {
		points?: TelemetryPoint[];
		showSg?: boolean;
		showCs?: boolean;
		showPwm?: boolean;
		showTstep?: boolean;
		height?: number;
	} = $props();

	let canvas = $state<HTMLCanvasElement | null>(null);
	let wrapper = $state<HTMLDivElement | null>(null);
	let width = $state(800);

	const PAD = { top: 16, right: 16, bottom: 32, left: 36 };

	function cssVar(name: string, fallback: string): string {
		if (typeof window === 'undefined' || !canvas) return fallback;
		const v = getComputedStyle(canvas).getPropertyValue(name).trim();
		return v || fallback;
	}

	function normalized(key: SeriesKey): { x: number; v: number }[] {
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
		const syNorm = (v: number) => y0 + plotH - v * plotH;

		// Horizontal gridlines (normalized 0..1)
		ctx.font = '11px ui-sans-serif, system-ui, sans-serif';
		ctx.textBaseline = 'middle';
		ctx.lineWidth = 1;
		for (const gv of [0, 0.25, 0.5, 0.75, 1]) {
			const y = syNorm(gv);
			ctx.strokeStyle = colBorder;
			ctx.beginPath();
			ctx.moveTo(x0, y);
			ctx.lineTo(x0 + plotW, y);
			ctx.stroke();
			ctx.fillStyle = colMuted;
			ctx.textAlign = 'right';
			ctx.fillText(gv.toFixed(2), x0 - 6, y);
		}

		// X axis labels (time)
		ctx.textAlign = 'center';
		ctx.textBaseline = 'top';
		const ticks = 5;
		for (let i = 0; i <= ticks; i++) {
			const xv = xMin + (xSpan * i) / ticks;
			ctx.fillStyle = colMuted;
			ctx.fillText(`${(xv - xMin).toFixed(0)}s`, sx(xv), y0 + plotH + 6);
		}

		if (points.length === 0) {
			ctx.fillStyle = colMuted;
			ctx.textAlign = 'center';
			ctx.textBaseline = 'middle';
			ctx.fillText('No samples', x0 + plotW / 2, y0 + plotH / 2);
			return;
		}

		// Warn markers (otpw / over-temp): thin vertical danger ticks at the base
		for (const p of points) {
			if (!p.warn) continue;
			const X = sx(p.x);
			ctx.strokeStyle = colDanger;
			ctx.globalAlpha = 0.5;
			ctx.lineWidth = 1;
			ctx.beginPath();
			ctx.moveTo(X, y0 + plotH);
			ctx.lineTo(X, y0 + plotH * 0.85);
			ctx.stroke();
			ctx.globalAlpha = 1;
		}

		const drawLine = (key: SeriesKey, color: string, lineWidth: number) => {
			const series = normalized(key);
			if (series.length === 0) return;
			ctx.strokeStyle = color;
			ctx.lineWidth = lineWidth;
			ctx.beginPath();
			series.forEach((p, i) => {
				const X = sx(p.x);
				const Y = syNorm(p.v);
				i === 0 ? ctx.moveTo(X, Y) : ctx.lineTo(X, Y);
			});
			ctx.stroke();
		};

		if (showTstep) drawLine('tstep', colSuccess, 1);
		if (showCs) drawLine('cs', colWarning, 1.25);
		if (showPwm) drawLine('pwm', colDanger, 1.25);
		if (showSg) drawLine('sg', colPrimary, 1.5);

		ctx.strokeStyle = colText;
		ctx.globalAlpha = 0.25;
		ctx.strokeRect(x0, y0, plotW, plotH);
		ctx.globalAlpha = 1;
	}

	$effect(() => {
		void points;
		void showSg;
		void showCs;
		void showPwm;
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
