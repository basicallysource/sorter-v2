<script lang="ts">
	// One live camera, drawn on a canvas: its newest frame and, when asked,
	// what perception found on it (`boxes`) and the zones perception works
	// with (`zones`). The backend sends the pixels and these as data apart
	// (lib/video.ts), so a layer shown or hidden is only a redraw, and the
	// zones drawn are the ones perception used for that very frame. The caller
	// gives the canvas its size; `shape` is the frame's size, for a box that
	// should hug it. `stale` turns true when no frame has come for STALE_MS.
	import { onDestroy, untrack } from 'svelte';
	import { getBackendHttpBase, machineHttpBaseUrlFromWsUrl } from '$lib/backend';
	import { getMachineContext } from '$lib/machines/context';
	import {
		watchVideo,
		type FeedBox,
		type FeedFrame,
		type FeedLayout,
		type FeedZones,
		type Ring
	} from '$lib/video';

	const STALE_MS = 3000;

	// The operating feed's colours, as perception's debug pictures draw them.
	const ZONE_FILL = {
		drop: 'rgb(0 128 255 / 0.15)',
		exit: 'rgb(255 64 0 / 0.15)',
		precise: 'rgb(255 0 255 / 0.15)'
	} as const;
	const CHANNEL_OUTLINE = 'rgb(0 255 255)';
	const EXIT_MARGIN = 'rgb(160 160 160)';
	const SECONDARY_ZONE: Record<string, string> = {
		drop: 'rgb(120 160 200)',
		exit: 'rgb(220 140 120)',
		precise: 'rgb(200 120 200)'
	};
	const SECONDARY_ZONE_DEFAULT = 'rgb(180 180 180)';
	const BOX: Record<FeedBox['kind'], string> = {
		piece: 'rgb(0 255 0)',
		merged: 'rgb(128 0 255)',
		seen: 'rgb(0 255 255)',
		margin: 'rgb(160 160 160)'
	};
	const LABEL_PX = 11;

	type Size = { width: number; height: number };

	let {
		view,
		baseUrl = '',
		alt,
		boxes = false,
		zones = false,
		fit = 'contain',
		class: className = '',
		style = '',
		stale = $bindable(false),
		shape = $bindable(null),
		onframe
	}: {
		view: string;
		baseUrl?: string;
		alt: string;
		boxes?: boolean;
		zones?: boolean;
		fit?: 'contain' | 'cover';
		class?: string;
		style?: string;
		stale?: boolean;
		shape?: Size | null;
		// The full frame's size, each time a new frame is up.
		onframe?: (size: Size) => void;
	} = $props();

	const ctx = getMachineContext();
	const base = $derived(
		baseUrl || machineHttpBaseUrlFromWsUrl(ctx.machine?.url) || getBackendHttpBase()
	);

	let canvas: HTMLCanvasElement;
	// The frame on show and what perception found on it, the view's layout,
	// and the newest frame to show once the one decoding is up: frames that
	// come meanwhile are skipped.
	let bitmap: ImageBitmap | null = null;
	let found: FeedBox[] | null = null;
	let layout: FeedLayout | null = null;
	let decoding = false;
	let next: FeedFrame | null = null;
	// Bumped when the view changes, so a frame of the last one is dropped.
	let generation = 0;
	let destroyed = false;
	let lastFrameAt = 0;

	function fresh() {
		lastFrameAt = performance.now();
		stale = false;
	}

	async function decode(frame: FeedFrame, of: number) {
		decoding = true;
		try {
			const decoded = await createImageBitmap(frame.jpeg);
			if (destroyed || of !== generation) {
				decoded.close();
				return;
			}
			bitmap?.close();
			bitmap = decoded;
			found = frame.boxes;
			draw();
			onframe?.({ width: decoded.width, height: decoded.height });
		} catch {
			// A frame that does not decode is skipped; the next replaces it.
		} finally {
			decoding = false;
			// What came meanwhile is the current view's: a new view clears it.
			const queued = next;
			next = null;
			if (queued && !destroyed) decode(queued, generation);
		}
	}

	$effect(() => {
		const of = ++generation;
		fresh();
		next = null;
		layout = null;
		const stop = watchVideo(base, view, {
			frame: (frame) => {
				fresh();
				if (decoding) next = frame;
				else decode(frame, of);
			},
			layout: (newer) => {
				layout = newer;
				draw();
			}
		});
		const timer = setInterval(() => (stale = performance.now() - lastFrameAt > STALE_MS), 1000);
		return () => {
			stop();
			clearInterval(timer);
		};
	});

	$effect(() => {
		void [boxes, zones, fit];
		untrack(draw);
	});

	$effect(() => {
		const observer = new ResizeObserver(() => draw());
		observer.observe(canvas);
		return () => observer.disconnect();
	});

	onDestroy(() => {
		destroyed = true;
		bitmap?.close();
		bitmap = null;
	});

	function trace(g: CanvasRenderingContext2D, rings: Ring[], width: number, height: number) {
		g.beginPath();
		for (const ring of rings) {
			for (let i = 0; i + 1 < ring.length; i += 2) {
				const [x, y] = [ring[i] * width, ring[i + 1] * height];
				if (i === 0) g.moveTo(x, y);
				else g.lineTo(x, y);
			}
			g.closePath();
		}
	}

	function drawZones(
		g: CanvasRenderingContext2D,
		shapes: FeedZones,
		width: number,
		height: number,
		px: number
	) {
		for (const name of ['precise', 'exit', 'drop'] as const) {
			trace(g, shapes[name], width, height);
			g.fillStyle = ZONE_FILL[name];
			g.fill('evenodd');
		}
		g.lineWidth = px;
		const outlines: [Ring[], string][] = [
			[shapes.outline, CHANNEL_OUTLINE],
			[shapes.margin, EXIT_MARGIN],
			...shapes.secondary.map((zone): [Ring[], string] => [
				zone.rings,
				SECONDARY_ZONE[zone.type] ?? SECONDARY_ZONE_DEFAULT
			])
		];
		for (const [rings, color] of outlines) {
			trace(g, rings, width, height);
			g.strokeStyle = color;
			g.stroke();
		}
	}

	function label(
		g: CanvasRenderingContext2D,
		text: string,
		x: number,
		y: number,
		color: string,
		px: number
	) {
		g.font = `${LABEL_PX * px}px ui-sans-serif, system-ui, sans-serif`;
		g.textBaseline = 'top';
		const pad = 2 * px;
		const w = g.measureText(text).width + 2 * pad;
		const h = LABEL_PX * px + 2 * pad;
		g.fillStyle = 'rgb(0 0 0)';
		g.fillRect(x, y, w, h);
		g.fillStyle = color;
		g.fillText(text, x + pad, y + pad);
		return h;
	}

	function drawBoxes(
		g: CanvasRenderingContext2D,
		all: FeedBox[],
		width: number,
		height: number,
		px: number
	) {
		for (const { kind, box, id } of all) {
			const [x1, y1, x2, y2] = [box[0] * width, box[1] * height, box[2] * width, box[3] * height];
			g.lineWidth = (kind === 'merged' ? 2 : 1) * px;
			g.strokeStyle = BOX[kind];
			g.strokeRect(x1, y1, x2 - x1, y2 - y1);
			if (kind === 'merged') {
				// What the machine acts on, named under the box.
				label(g, id === undefined ? 'merged' : `merged #${id}`, x1, y2 + px, BOX[kind], px);
			} else if (kind === 'piece' && id !== undefined) {
				const h = (LABEL_PX + 4) * px;
				label(g, `#${id}`, x1, Math.max(0, y1 - h - px), BOX[kind], px);
			}
		}
	}

	function draw() {
		if (!canvas || !bitmap) return;
		const [width, height] = [bitmap.width, bitmap.height];
		if (shape?.width !== width || shape?.height !== height) shape = { width, height };
		// The canvas holds what it shows at the size it is shown, in device
		// pixels, so lines and labels stay sharp; object-fit places it.
		const [boxWidth, boxHeight] = [canvas.clientWidth, canvas.clientHeight];
		if (!boxWidth || !boxHeight) return;
		const pick = fit === 'cover' ? Math.max : Math.min;
		const cssScale = pick(boxWidth / width, boxHeight / height);
		const scale = Math.min(
			cssScale * (window.devicePixelRatio || 1),
			4096 / Math.max(width, height)
		);
		const backingWidth = Math.max(1, Math.round(width * scale));
		const backingHeight = Math.max(1, Math.round(height * scale));
		if (canvas.width !== backingWidth) canvas.width = backingWidth;
		if (canvas.height !== backingHeight) canvas.height = backingHeight;
		const g = canvas.getContext('2d');
		if (!g) return;
		g.setTransform(backingWidth / width, 0, 0, backingHeight / height, 0, 0);
		g.clearRect(0, 0, width, height);
		// One CSS pixel, in frame pixels.
		const px = 1 / cssScale;
		g.drawImage(bitmap, 0, 0, width, height);
		if (zones && layout?.zones) drawZones(g, layout.zones, width, height, px);
		if (boxes && found) drawBoxes(g, found, width, height, px);
	}
</script>

<!-- Back from hidden, the page gets its frames again: not stale meanwhile. -->
<svelte:document onvisibilitychange={fresh} />

<!-- What the canvas holds, named for a screen reader in its fallback. -->
<canvas
	bind:this={canvas}
	class="{className} {fit === 'cover' ? 'object-cover' : 'object-contain'}"
	{style}>{alt}</canvas
>
