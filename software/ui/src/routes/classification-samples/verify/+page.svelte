<script lang="ts">
	import { backendHttpBaseUrl, machineHttpBaseUrlFromWsUrl } from '$lib/backend';
	import { getMachinesContext } from '$lib/machines/context';
	import { ArrowLeft, ArrowRight, Check, SkipForward, X, Pencil } from 'lucide-svelte';

	const manager = getMachinesContext();

	type Detection = {
		description: string;
		bbox: [number, number, number, number];
		confidence: number;
	};

	type SampleDetail = {
		sample_id: string;
		session_id?: string;
		input_image_url: string;
		distill_result?: {
			result_json_url?: string;
			overlay_image_url?: string;
			detections?: number;
		};
		detection_candidate_bboxes?: number[][];
		review?: { status: string; updated_at: number } | null;
	};

	type Stats = {
		total: number;
		verified: number;
		unverified: number;
		accepted: number;
		rejected: number;
	};

	let loading = $state(false);
	let saving = $state(false);
	let sample = $state<SampleDetail | null>(null);
	let stats = $state<Stats>({ total: 0, verified: 0, unverified: 0, accepted: 0, rejected: 0 });
	let detections = $state<Detection[]>([]);
	let boxStatuses = $state<Map<number, 'confirmed' | 'rejected'>>(new Map());
	let addedBoxes = $state<{ bbox: [number, number, number, number] }[]>([]);
	let drawingBox = $state<{ startX: number; startY: number; currentX: number; currentY: number } | null>(null);
	let drawMode = $state(false);
	let imageLoaded = $state(false);
	let imgWidth = $state(0);
	let imgHeight = $state(0);
	let canvasEl: HTMLCanvasElement;
	let imageEl: HTMLImageElement;
	let done = $state(false);
	let currentSessionId = $state<string | null>(null);

	function currentBackendBaseUrl(): string {
		return (
			machineHttpBaseUrlFromWsUrl(
				manager.selectedMachine?.status === 'connected' ? manager.selectedMachine.url : null
			) ?? backendHttpBaseUrl
		);
	}

	function assetUrl(path: string | null | undefined): string | null {
		if (typeof path !== 'string' || !path) return null;
		if (path.startsWith('http://') || path.startsWith('https://')) return path;
		return `${currentBackendBaseUrl()}${path}`;
	}

	async function loadNextSample() {
		loading = true;
		imageLoaded = false;
		detections = [];
		boxStatuses = new Map();
		addedBoxes = [];
		drawingBox = null;
		try {
			const res = await fetch(`${currentBackendBaseUrl()}/api/classification/training/verify-next`);
			const data = await res.json();
			if (data.done || !data.sample) {
				sample = null;
				currentSessionId = null;
				done = true;
				return;
			}
			sample = data.sample;
			currentSessionId = data.session_id ?? null;
			done = false;

			if (sample?.distill_result?.result_json_url) {
				const rjUrl = assetUrl(sample.distill_result.result_json_url);
				if (rjUrl) {
					const rjRes = await fetch(rjUrl);
					const rjData = await rjRes.json();
					if (rjData.detections && Array.isArray(rjData.detections)) {
						detections = rjData.detections;
					}
					if (rjData.width) imgWidth = rjData.width;
					if (rjData.height) imgHeight = rjData.height;
				}
			}
		} catch (e) {
			console.error('Failed to load next sample:', e);
		} finally {
			loading = false;
		}
	}

	async function loadStats() {
		try {
			const res = await fetch(`${currentBackendBaseUrl()}/api/classification/training/verify-stats`);
			const data = await res.json();
			if (data.ok) {
				stats = data;
			}
		} catch (e) {
			console.error('Failed to load stats:', e);
		}
	}

	async function submitReview(status: 'accepted' | 'rejected') {
		if (saving || !sample || !currentSessionId) return;
		saving = true;
		try {
			const corrections = detections.map((det, i) => ({
				bbox: det.bbox,
				status: boxStatuses.get(i) ?? 'confirmed',
			}));
			const added = addedBoxes.map((b) => ({ bbox: b.bbox }));

			await fetch(
				`${currentBackendBaseUrl()}/api/classification/training/sessions/${currentSessionId}/samples/${sample.sample_id}/review`,
				{
					method: 'POST',
					headers: { 'Content-Type': 'application/json' },
					body: JSON.stringify({
						status,
						box_corrections: corrections.length > 0 ? corrections : undefined,
						added_boxes: added.length > 0 ? added : undefined,
					}),
				}
			);
			await loadStats();
			await loadNextSample();
		} finally {
			saving = false;
		}
	}

	function skip() {
		loadNextSample();
	}

	const BOX_COLORS = ['#3b82f6', '#8b5cf6', '#f59e0b', '#06b6d4', '#ec4899', '#10b981', '#f97316', '#6366f1'];

	function drawCanvas() {
		if (!canvasEl || !imageEl || !imageLoaded) return;
		const ctx = canvasEl.getContext('2d');
		if (!ctx) return;

		canvasEl.width = imgWidth || imageEl.naturalWidth;
		canvasEl.height = imgHeight || imageEl.naturalHeight;
		ctx.drawImage(imageEl, 0, 0, canvasEl.width, canvasEl.height);

		for (let i = 0; i < detections.length; i++) {
			const det = detections[i];
			const status = boxStatuses.get(i);
			let color: string;
			let lineWidth: number;
			if (status === 'confirmed') {
				color = '#22c55e';
				lineWidth = 3;
			} else if (status === 'rejected') {
				color = '#ef4444';
				lineWidth = 3;
			} else {
				color = BOX_COLORS[i % BOX_COLORS.length];
				lineWidth = 2;
			}

			const [x1, y1, x2, y2] = det.bbox;
			ctx.strokeStyle = color;
			ctx.lineWidth = lineWidth;
			ctx.strokeRect(x1, y1, x2 - x1, y2 - y1);

			const label = `${i + 1}${det.description ? ': ' + det.description.slice(0, 25) : ''}`;
			ctx.font = '14px sans-serif';
			const textWidth = ctx.measureText(label).width;
			ctx.fillStyle = color;
			ctx.fillRect(x1, Math.max(0, y1 - 20), textWidth + 8, 20);
			ctx.fillStyle = '#fff';
			ctx.fillText(label, x1 + 4, Math.max(14, y1 - 5));

			if (status === 'rejected') {
				ctx.strokeStyle = '#ef4444';
				ctx.lineWidth = 2;
				ctx.beginPath();
				ctx.moveTo(x1, y1);
				ctx.lineTo(x2, y2);
				ctx.moveTo(x2, y1);
				ctx.lineTo(x1, y2);
				ctx.stroke();
			}
		}

		for (let i = 0; i < addedBoxes.length; i++) {
			const [x1, y1, x2, y2] = addedBoxes[i].bbox;
			ctx.strokeStyle = '#06b6d4';
			ctx.lineWidth = 3;
			ctx.setLineDash([6, 3]);
			ctx.strokeRect(x1, y1, x2 - x1, y2 - y1);
			ctx.setLineDash([]);

			const label = `Added ${i + 1}`;
			ctx.font = '14px sans-serif';
			const tw = ctx.measureText(label).width;
			ctx.fillStyle = '#06b6d4';
			ctx.fillRect(x1, Math.max(0, y1 - 20), tw + 8, 20);
			ctx.fillStyle = '#fff';
			ctx.fillText(label, x1 + 4, Math.max(14, y1 - 5));
		}

		if (drawingBox) {
			const x = Math.min(drawingBox.startX, drawingBox.currentX);
			const y = Math.min(drawingBox.startY, drawingBox.currentY);
			const w = Math.abs(drawingBox.currentX - drawingBox.startX);
			const h = Math.abs(drawingBox.currentY - drawingBox.startY);
			ctx.strokeStyle = '#06b6d4';
			ctx.lineWidth = 2;
			ctx.setLineDash([4, 4]);
			ctx.strokeRect(x, y, w, h);
			ctx.setLineDash([]);
		}
	}

	$effect(() => {
		// Track all reactive deps
		void detections;
		void boxStatuses;
		void addedBoxes;
		void drawingBox;
		void imageLoaded;
		drawCanvas();
	});

	function canvasCoords(e: PointerEvent): { x: number; y: number } {
		const rect = canvasEl.getBoundingClientRect();
		const scaleX = canvasEl.width / rect.width;
		const scaleY = canvasEl.height / rect.height;
		return {
			x: (e.clientX - rect.left) * scaleX,
			y: (e.clientY - rect.top) * scaleY,
		};
	}

	function onPointerDown(e: PointerEvent) {
		if (!canvasEl) return;
		const { x, y } = canvasCoords(e);

		if (!drawMode) {
			for (let i = detections.length - 1; i >= 0; i--) {
				const [bx1, by1, bx2, by2] = detections[i].bbox;
				if (x >= bx1 && x <= bx2 && y >= by1 && y <= by2) {
					const current = boxStatuses.get(i);
					const newMap = new Map(boxStatuses);
					if (current === undefined) {
						newMap.set(i, 'confirmed');
					} else if (current === 'confirmed') {
						newMap.set(i, 'rejected');
					} else {
						newMap.delete(i);
					}
					boxStatuses = newMap;
					return;
				}
			}
		}

		drawingBox = { startX: x, startY: y, currentX: x, currentY: y };
		canvasEl.setPointerCapture(e.pointerId);
	}

	function onPointerMove(e: PointerEvent) {
		if (!drawingBox || !canvasEl) return;
		const { x, y } = canvasCoords(e);
		drawingBox = { ...drawingBox, currentX: x, currentY: y };
	}

	function onPointerUp(e: PointerEvent) {
		if (!drawingBox) return;
		const x1 = Math.min(drawingBox.startX, drawingBox.currentX);
		const y1 = Math.min(drawingBox.startY, drawingBox.currentY);
		const x2 = Math.max(drawingBox.startX, drawingBox.currentX);
		const y2 = Math.max(drawingBox.startY, drawingBox.currentY);
		const w = x2 - x1;
		const h = y2 - y1;

		if (w > 10 && h > 10) {
			addedBoxes = [
				...addedBoxes,
				{ bbox: [Math.round(x1), Math.round(y1), Math.round(x2), Math.round(y2)] as [number, number, number, number] },
			];
		}
		drawingBox = null;
	}

	function undoLastBox() {
		if (addedBoxes.length > 0) {
			addedBoxes = addedBoxes.slice(0, -1);
		}
	}

	function onKeyDown(e: KeyboardEvent) {
		if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) return;
		if (e.key === 'ArrowRight') {
			e.preventDefault();
			skip();
		}
		if (e.key === 'Enter') {
			e.preventDefault();
			submitReview('accepted');
		}
		if (e.key === 'Backspace') {
			e.preventDefault();
			submitReview('rejected');
		}
		if (e.key === 'd') {
			e.preventDefault();
			drawMode = !drawMode;
		}
		if (e.key === 'z' && (e.metaKey || e.ctrlKey)) {
			e.preventDefault();
			undoLastBox();
		}
	}

	$effect(() => {
		loadStats();
		loadNextSample();
	});
</script>

<svelte:window onkeydown={onKeyDown} />

<div class="fixed inset-0 flex flex-col bg-gray-950 text-gray-200">
	<!-- Top bar -->
	<header class="flex items-center justify-between border-b border-gray-800 px-4 py-2">
		<div class="flex items-center gap-4">
			<a href="/classification-samples" class="text-sm text-gray-400 hover:text-white transition-colors">
				<ArrowLeft size={16} class="inline -mt-0.5" /> Back
			</a>
			<div class="text-sm">
				<span class="text-emerald-400 font-semibold">{stats.verified}</span>
				<span class="text-gray-500"> / {stats.total} verified</span>
				{#if stats.accepted > 0}
					<span class="ml-2 text-emerald-600">{stats.accepted} accepted</span>
				{/if}
				{#if stats.rejected > 0}
					<span class="ml-2 text-red-500">{stats.rejected} rejected</span>
				{/if}
			</div>
			{#if stats.total > 0}
				<div class="w-48 h-1.5 bg-gray-800 rounded-full overflow-hidden">
					<div
						class="h-full bg-emerald-500 transition-all duration-300"
						style="width: {(stats.verified / stats.total) * 100}%"
					></div>
				</div>
			{/if}
		</div>

		<div class="flex items-center gap-2">
			<button
				onclick={() => (drawMode = !drawMode)}
				class="flex items-center gap-1.5 rounded px-3 py-1.5 text-sm transition-colors {drawMode
					? 'bg-cyan-500/20 text-cyan-300 border border-cyan-500'
					: 'bg-gray-800 text-gray-400 border border-gray-700 hover:border-gray-500'}"
			>
				<Pencil size={14} /> Draw (D)
			</button>

			<button
				onclick={() => submitReview('rejected')}
				disabled={saving || !sample}
				class="flex items-center gap-1.5 rounded border border-red-500/50 bg-red-500/10 px-3 py-1.5 text-sm text-red-400 transition-colors hover:bg-red-500/20 disabled:opacity-40"
			>
				<X size={14} /> Reject
			</button>

			<button
				onclick={skip}
				disabled={loading || !sample}
				class="flex items-center gap-1.5 rounded border border-gray-600 bg-gray-800 px-3 py-1.5 text-sm text-gray-300 transition-colors hover:bg-gray-700 disabled:opacity-40"
			>
				<SkipForward size={14} /> Skip
			</button>

			<button
				onclick={() => submitReview('accepted')}
				disabled={saving || !sample}
				class="flex items-center gap-1.5 rounded border border-emerald-500/50 bg-emerald-500/10 px-4 py-1.5 text-sm font-medium text-emerald-400 transition-colors hover:bg-emerald-500/20 disabled:opacity-40"
			>
				<Check size={14} /> Approve
			</button>
		</div>
	</header>

	<!-- Main canvas area -->
	<main class="flex flex-1 items-center justify-center overflow-hidden p-4">
		{#if loading}
			<div class="text-gray-500 text-lg">Loading next sample...</div>
		{:else if done || !sample}
			<div class="text-center">
				<div class="text-4xl mb-4">All done!</div>
				<p class="text-gray-400">All {stats.total} samples have been verified.</p>
				<a href="/classification-samples" class="mt-4 inline-block text-emerald-400 hover:underline">
					Back to library
				</a>
			</div>
		{:else}
			<div class="relative flex items-center justify-center max-w-full max-h-full">
				<img
					bind:this={imageEl}
					src={assetUrl(sample.input_image_url) ?? undefined}
					onload={() => {
						imageLoaded = true;
						if (!imgWidth) imgWidth = imageEl.naturalWidth;
						if (!imgHeight) imgHeight = imageEl.naturalHeight;
					}}
					class="hidden"
					alt=""
				/>
				<canvas
					bind:this={canvasEl}
					onpointerdown={onPointerDown}
					onpointermove={onPointerMove}
					onpointerup={onPointerUp}
					class="max-w-full max-h-[calc(100vh-120px)] {drawMode ? 'cursor-crosshair' : 'cursor-pointer'}"
					style="object-fit: contain;"
				></canvas>
			</div>
		{/if}
	</main>

	<!-- Bottom info bar -->
	{#if sample && !done}
		<footer class="flex items-center justify-between border-t border-gray-800 px-4 py-2 text-xs text-gray-500">
			<div class="flex items-center gap-4">
				<span>Sample: <span class="text-gray-300">{sample.sample_id}</span></span>
				<span>{detections.length} detections</span>
				{#if addedBoxes.length > 0}
					<span class="text-cyan-400">{addedBoxes.length} added</span>
					<button onclick={undoLastBox} class="text-cyan-400 hover:text-cyan-300">Undo last</button>
				{/if}
			</div>
			<div class="flex items-center gap-4">
				<span>Click box: <span class="text-gray-300">toggle status</span></span>
				<span class="text-emerald-500">Confirmed</span>
				<span class="text-red-500">Rejected</span>
				<span class="text-cyan-400">Added</span>
				<span class="text-gray-600">|</span>
				<span>Enter: approve</span>
				<span>Backspace: reject</span>
				<span>Arrow Right: skip</span>
				<span>D: draw mode</span>
			</div>
		</footer>
	{/if}
</div>
