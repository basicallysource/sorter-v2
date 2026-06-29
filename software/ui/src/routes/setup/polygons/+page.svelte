<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import { goto } from '$app/navigation';
	import { backendHttpBaseUrl } from '$lib/backend';

	// Channels drawn over the live cameras. second/third carry a section-0 reference angle;
	// carousel + classification are plain regions. classification replaces the old top/bottom.
	const FEEDER_CHANNELS = ['second', 'third', 'carousel'];
	const SECTION_ZERO_CHANNELS = ['second', 'third'];
	const CLASSIFICATION = 'classification';
	const ALL = [...FEEDER_CHANNELS, CLASSIFICATION];

	const LABELS: Record<string, string> = {
		second: 'Second (C-Ch 2)',
		third: 'Third (C-Ch 3)',
		carousel: 'Carousel',
		classification: 'Classification'
	};
	const COLORS: Record<string, [number, number, number]> = {
		second: [255, 200, 0],
		third: [0, 200, 255],
		carousel: [0, 255, 128],
		classification: [255, 96, 144]
	};

	let status = $state('loading…');
	let current = $state('second');
	let saved = $state(false);
	let sessionEnded = false;

	let channelCameraMap: Record<string, string> = {};

	onMount(() => {
		const canvas = document.getElementById('poly') as HTMLCanvasElement;
		const ctx = canvas.getContext('2d')!;

		const userPoints: Record<string, number[][]> = {
			second: [], third: [], carousel: [], classification: []
		};
		const sectionZero: Record<string, number[] | null> = { second: null, third: null };
		let frameImg = new Image();
		let cur = 'second';
		let dragging = false, didDrag = false;
		let dragStart: number[] | null = null;
		let dragOrig: number[][] | null = null;
		let dragOrigSec0: number[] | null = null;
		const DRAG = 5;

		const camFor = (ch: string) => channelCameraMap[ch] ?? ch;

		function coords(e: MouseEvent) {
			const r = canvas.getBoundingClientRect();
			return [
				((e.clientX - r.left) * canvas.width) / r.width,
				((e.clientY - r.top) * canvas.height) / r.height
			];
		}
		function inPoly(x: number, y: number, pts: number[][]) {
			if (pts.length < 3) return false;
			let inside = false;
			for (let i = 0, j = pts.length - 1; i < pts.length; j = i++) {
				const [xi, yi] = pts[i], [xj, yj] = pts[j];
				if (yi > y !== yj > y && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) inside = !inside;
			}
			return inside;
		}
		function sortPoly(ch: string) {
			const pts = userPoints[ch].map((p) => [...p]);
			if (pts.length < 2) return pts;
			const cx = pts.reduce((s, p) => s + p[0], 0) / pts.length;
			const cy = pts.reduce((s, p) => s + p[1], 0) / pts.length;
			pts.sort((a, b) => Math.atan2(a[1] - cy, a[0] - cx) - Math.atan2(b[1] - cy, b[0] - cx));
			return pts;
		}
		function center(ch: string) {
			const pts = sortPoly(ch);
			if (pts.length < 2) return null;
			return [
				pts.reduce((s, p) => s + p[0], 0) / pts.length,
				pts.reduce((s, p) => s + p[1], 0) / pts.length
			];
		}
		function angle(ch: string) {
			const ref = sectionZero[ch];
			const c = center(ch);
			if (!ref || !c) return null;
			return Math.atan2(ref[1] - c[1], ref[0] - c[0]) * (180 / Math.PI);
		}

		canvas.addEventListener('mousedown', (e) => {
			if (e.button !== 0) return;
			const [x, y] = coords(e);
			const sorted = sortPoly(cur);
			if (sorted.length >= 3 && inPoly(x, y, sorted) && !e.shiftKey) {
				dragging = true;
				dragStart = [x, y];
				dragOrig = userPoints[cur].map((p) => [...p]);
				dragOrigSec0 = sectionZero[cur] ? [...sectionZero[cur]!] : null;
			}
		});
		canvas.addEventListener('mousemove', (e) => {
			if (!dragging || !dragStart || !dragOrig) return;
			const [x, y] = coords(e);
			const dx = x - dragStart[0], dy = y - dragStart[1];
			userPoints[cur] = dragOrig.map((p) => [p[0] + dx, p[1] + dy]);
			if (dragOrigSec0 && sectionZero[cur]) sectionZero[cur] = [dragOrigSec0[0] + dx, dragOrigSec0[1] + dy];
		});
		canvas.addEventListener('mouseup', (e) => {
			if (e.button !== 0 || !dragging) return;
			const [x, y] = coords(e);
			if (Math.hypot(x - dragStart![0], y - dragStart![1]) < DRAG) {
				userPoints[cur] = dragOrig!;
				if (dragOrigSec0) sectionZero[cur] = dragOrigSec0;
				userPoints[cur].push([dragStart![0], dragStart![1]]);
			} else didDrag = true;
			dragging = false; dragStart = dragOrig = dragOrigSec0 = null;
		});
		canvas.addEventListener('click', (e) => {
			if (didDrag) { didDrag = false; return; }
			const [x, y] = coords(e);
			if (e.shiftKey && SECTION_ZERO_CHANNELS.includes(cur)) { sectionZero[cur] = [x, y]; return; }
			const sorted = sortPoly(cur);
			if (sorted.length >= 3 && inPoly(x, y, sorted)) return;
			userPoints[cur].push([x, y]);
		});
		canvas.addEventListener('contextmenu', (e) => {
			e.preventDefault();
			const [x, y] = coords(e);
			const pts = userPoints[cur];
			let md = Infinity, mi = -1;
			pts.forEach((p, i) => { const d = Math.hypot(p[0] - x, p[1] - y); if (d < md) { md = d; mi = i; } });
			if (mi >= 0 && md < 40) pts.splice(mi, 1);
		});
		canvas.addEventListener('wheel', (e) => {
			e.preventDefault();
			const pts = userPoints[cur];
			if (pts.length < 3) return;
			const s = e.deltaY > 0 ? 0.95 : 1.05;
			const cx = pts.reduce((a, p) => a + p[0], 0) / pts.length;
			const cy = pts.reduce((a, p) => a + p[1], 0) / pts.length;
			for (let i = 0; i < pts.length; i++) pts[i] = [cx + (pts[i][0] - cx) * s, cy + (pts[i][1] - cy) * s];
		}, { passive: false });

		function drawPoly(ch: string, active: boolean) {
			const pts = sortPoly(ch);
			if (pts.length < 2) return;
			const [r, g, b] = COLORS[ch];
			ctx.beginPath();
			ctx.moveTo(pts[0][0], pts[0][1]);
			for (let i = 1; i < pts.length; i++) ctx.lineTo(pts[i][0], pts[i][1]);
			ctx.closePath();
			ctx.fillStyle = `rgba(${r},${g},${b},${active ? 0.12 : 0.05})`;
			ctx.fill();
			ctx.strokeStyle = `rgba(${r},${g},${b},${active ? 1 : 0.35})`;
			ctx.lineWidth = active ? 2 : 1;
			ctx.stroke();
			for (const [x, y] of pts) {
				ctx.beginPath(); ctx.arc(x, y, 6, 0, Math.PI * 2);
				ctx.fillStyle = `rgba(${r},${g},${b},${active ? 1 : 0.35})`; ctx.fill();
			}
			if (SECTION_ZERO_CHANNELS.includes(ch) && sectionZero[ch]) {
				const c = center(ch), ref = sectionZero[ch]!;
				if (c) {
					ctx.beginPath(); ctx.moveTo(c[0], c[1]); ctx.lineTo(ref[0], ref[1]);
					ctx.strokeStyle = `rgba(255,255,255,${active ? 0.9 : 0.3})`;
					ctx.setLineDash([6, 4]); ctx.stroke(); ctx.setLineDash([]);
					ctx.beginPath(); ctx.arc(ref[0], ref[1], 8, 0, Math.PI * 2);
					ctx.fillStyle = `rgba(255,255,255,${active ? 0.9 : 0.3})`; ctx.fill();
				}
			}
		}
		function render() {
			if (!frameImg.naturalWidth) return;
			if (canvas.width !== frameImg.naturalWidth) canvas.width = frameImg.naturalWidth;
			if (canvas.height !== frameImg.naturalHeight) canvas.height = frameImg.naturalHeight;
			ctx.drawImage(frameImg, 0, 0, canvas.width, canvas.height);
			const cam = camFor(cur);
			for (const ch of ALL) if (ch !== cur && camFor(ch) === cam) drawPoly(ch, false);
			drawPoly(cur, true);
			const a = SECTION_ZERO_CHANNELS.includes(cur) ? angle(cur) : null;
			status = `${cur}: ${userPoints[cur].length} pts` +
				(SECTION_ZERO_CHANNELS.includes(cur) ? (a !== null ? ` | sec0 ${a.toFixed(1)}°` : ' | shift-click to set sec 0') : '');
		}
		function poll() {
			const img = new Image();
			img.onload = () => { frameImg = img; render(); };
			img.src = `${backendHttpBaseUrl}/calibration/polygons/frame/${camFor(cur)}?t=${Date.now()}`;
		}

		// expose for the toolbar buttons (outside this closure)
		(window as any).__poly = {
			setChannel: (ch: string) => { cur = ch; current = ch; },
			clear: () => { userPoints[cur] = []; if (SECTION_ZERO_CHANNELS.includes(cur)) sectionZero[cur] = null; },
			save: async () => {
				const polygons: Record<string, number[][]> = {};
				const upts: Record<string, number[][]> = {};
				for (const ch of FEEDER_CHANNELS) {
					const key = ch === 'carousel' ? 'carousel' : ch + '_channel';
					polygons[key] = sortPoly(ch).map((p) => [Math.round(p[0]), Math.round(p[1])]);
					upts[ch] = userPoints[ch].map((p) => [Math.round(p[0]), Math.round(p[1])]);
				}
				const angles: Record<string, number> = {};
				const sec0: Record<string, number[]> = {};
				for (const ch of SECTION_ZERO_CHANNELS) {
					const a = angle(ch); angles[ch] = a ?? 0;
					if (sectionZero[ch]) sec0[ch] = [Math.round(sectionZero[ch]![0]), Math.round(sectionZero[ch]![1])];
				}
				const body = {
					polygons, user_pts: upts, channel_angles: angles, section_zero_pts: sec0,
					class_polygons: { classification: sortPoly(CLASSIFICATION).map((p) => [Math.round(p[0]), Math.round(p[1])]) },
					class_user_pts: { classification: userPoints[CLASSIFICATION].map((p) => [Math.round(p[0]), Math.round(p[1])]) }
				};
				const res = await fetch(`${backendHttpBaseUrl}/calibration/polygons/save`, {
					method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body)
				});
				status = res.ok ? 'Saved.' : 'Save failed.';
			}
		};

		let pollTimer: ReturnType<typeof setInterval>;
		(async () => {
			try {
				const init = await (await fetch(`${backendHttpBaseUrl}/calibration/polygons/begin`, { method: 'POST' })).json();
				channelCameraMap = init.channel_camera_map ?? {};
				for (const ch of ALL) {
					if (init.user_pts?.[ch]) userPoints[ch] = init.user_pts[ch];
					if (init.class_user_pts?.[ch]) userPoints[ch] = init.class_user_pts[ch];
					if (init.section_zero_pts?.[ch]) sectionZero[ch] = init.section_zero_pts[ch];
				}
				status = 'ready';
			} catch (e) {
				status = 'failed to start: ' + (e as Error).message;
			}
			pollTimer = setInterval(poll, 100);
			poll();
		})();

		return () => clearInterval(pollTimer);
	});

	async function endSession() {
		if (sessionEnded) return;
		sessionEnded = true;
		try { await fetch(`${backendHttpBaseUrl}/calibration/polygons/end`, { method: 'POST' }); } catch { /* ignore */ }
	}
	onDestroy(endSession);

	function pick(ch: string) { (window as any).__poly?.setChannel(ch); }
	function clear() { (window as any).__poly?.clear(); }
	async function save() { await (window as any).__poly?.save(); saved = true; }
	async function done() { await save(); await endSession(); goto('/setup'); }
</script>

<div class="dark:bg-bg-dark flex h-screen flex-col bg-bg">
	<div class="dark:bg-surface-dark flex flex-wrap items-center gap-2 bg-surface p-3">
		{#each ALL as ch}
			<button onclick={() => pick(ch)}
				class="rounded px-3 py-1.5 text-sm font-medium {current === ch ? 'bg-blue-600 text-white' : 'dark:bg-bg-dark dark:text-text-dark bg-bg text-text'}">
				{LABELS[ch]}
			</button>
		{/each}
		<div class="mx-2 h-6 w-px bg-gray-500/40"></div>
		<button onclick={clear} class="rounded bg-red-700/80 px-3 py-1.5 text-sm text-white">Clear</button>
		<button onclick={save} class="rounded bg-green-700/80 px-3 py-1.5 text-sm text-white">Save</button>
		<button onclick={done} class="rounded bg-green-600 px-3 py-1.5 text-sm font-medium text-white">Save &amp; Finish</button>
		<span class="dark:text-text-muted-dark ml-auto text-xs text-text-muted">{status}</span>
	</div>
	<div class="dark:text-text-muted-dark px-3 py-1 text-xs text-text-muted">
		Click to add a vertex · drag inside to move · scroll to resize · right-click a vertex to remove · shift-click sets section-0 (second/third)
	</div>
	<div class="flex flex-1 items-center justify-center overflow-hidden bg-black">
		<canvas id="poly" width="1280" height="720" class="max-h-full max-w-full" style="cursor: crosshair;"></canvas>
	</div>
</div>
