<script lang="ts">
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import AppHeader from '$lib/components/AppHeader.svelte';
	import { backendHttpBaseUrl, machineHttpBaseUrlFromWsUrl } from '$lib/backend';
	import { getMachinesContext } from '$lib/machines/context';

	type RetestModelOption = {
		id: string;
		label: string;
	};

	type RetestSummary = {
		retest_id: string;
		created_at: number | null;
		model: string;
		found: boolean;
		bbox?: [number, number, number, number] | null;
		candidate_bboxes?: [number, number, number, number][];
		bbox_count: number;
		score?: number | null;
		error?: string | null;
		overlay_image_url?: string | null;
		result_json_url?: string | null;
		inference_ms?: number | null;
		fps?: number | null;
	};

	type LiveRetestState = 'running' | 'completed' | 'error';

	type LiveRetestCard = {
		local_id: string;
		run_token: string;
		model: string;
		status: LiveRetestState;
		requested_at: number;
		retest?: RetestSummary | null;
		error?: string | null;
	};

	type RetestCard = {
		key: string;
		retest_id?: string | null;
		model: string;
		status: LiveRetestState;
		created_at: number | null;
		found: boolean | null;
		bbox?: [number, number, number, number] | null;
		bbox_count: number | null;
		score?: number | null;
		error?: string | null;
		overlay_image_url?: string | null;
		result_json_url?: string | null;
		inference_ms?: number | null;
		fps?: number | null;
	};

	type SampleDetail = {
		session_id: string;
		session_name: string;
		sample_id: string;
		source: string;
		source_role?: string | null;
		capture_reason?: string | null;
		detection_scope?: string | null;
		camera?: string | null;
		preferred_camera?: string | null;
		captured_at: number | null;
		processor: string;
		detection_algorithm?: string | null;
		detection_openrouter_model?: string | null;
		detection_found?: boolean | null;
		detection_bbox?: [number, number, number, number] | null;
		detection_candidate_bboxes?: [number, number, number, number][];
		detection_bbox_count?: number | null;
		detection_score?: number | null;
		detection_message?: string | null;
		distill_status: string;
		distill_detections?: number | null;
		review_status?: string | null;
		review_updated_at?: number | null;
		input_image_url?: string | null;
		top_zone_url?: string | null;
		bottom_zone_url?: string | null;
		top_frame_url?: string | null;
		bottom_frame_url?: string | null;
		distill_error?: string | null;
			distill_result?: {
				detections: number;
				overlay_image_url?: string | null;
				result_json_url?: string | null;
				yolo_label_url?: string | null;
				processed_at?: number | null;
			} | null;
			classification_result?: {
				provider?: string | null;
				status?: string | null;
				completed_at?: number | null;
				part_id?: string | null;
				item_name?: string | null;
				item_category?: string | null;
				color_id?: string | null;
				color_name?: string | null;
				confidence?: number | null;
				preview_url?: string | null;
				source_view?: string | null;
				selected_crop_url?: string | null;
				top_crop_url?: string | null;
				bottom_crop_url?: string | null;
				result_json_url?: string | null;
				top_items_count?: number | null;
				bottom_items_count?: number | null;
				top_colors_count?: number | null;
				bottom_colors_count?: number | null;
				error?: string | null;
			} | null;
			review?: {
				status?: string | null;
				updated_at?: number | null;
			} | null;
			retests: RetestSummary[];
			prev_sample_id?: string | null;
			next_sample_id?: string | null;
		};

	const manager = getMachinesContext();

	let loadedKey = $state('');
	let loading = $state(false);
	let deleting = $state(false);
	let reviewing = $state(false);
	let promoting = $state(false);
	let cacheBuster = $state(0);
	let showDistillOverlay = $state(true);
	let expandMeta = $state(false);
	let expandClassification = $state(false);
	let expandDistillation = $state(false);
	let showClassificationCrop = $state(false);
	let drawMode = $state(false);
	let drawingBox = $state<{ startX: number; startY: number; currentX: number; currentY: number } | null>(null);
	let pendingBoxes = $state<{ bbox: [number, number, number, number] }[]>([]);
	let savingBoxes = $state(false);
	let errorMsg = $state<string | null>(null);
	let statusMsg = $state('');
	let sample = $state<SampleDetail | null>(null);
	let availableRetestModels = $state<RetestModelOption[]>([]);
	let liveRetests = $state<LiveRetestCard[]>([]);

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
		const url = `${currentBackendBaseUrl()}${path}`;
		return cacheBuster > 0 ? `${url}${url.includes('?') ? '&' : '?'}_cb=${cacheBuster}` : url;
	}

	function formatDate(timestamp: number | null | undefined): string {
		if (typeof timestamp !== 'number' || !Number.isFinite(timestamp) || timestamp <= 0) {
			return 'n/a';
		}
		return new Date(timestamp * 1000).toLocaleString();
	}

	function bboxSummary(bbox: [number, number, number, number] | null | undefined): string {
		if (!bbox) return 'n/a';
		return `${Math.max(0, bbox[2] - bbox[0])} x ${Math.max(0, bbox[3] - bbox[1])}`;
	}

	function modelLabel(model: string | null | undefined): string {
		if (typeof model !== 'string' || !model) return 'n/a';
		return availableRetestModels.find((option) => option.id === model)?.label ?? model;
	}

	function sourceLabel(source: string | null | undefined): string {
		if (typeof source !== 'string' || !source) return 'n/a';
		const specialLabels: Record<string, string> = {
			classification_chamber: 'Classification Chamber',
			c_channel_2: 'C-Channel 2',
			c_channel_3: 'C-Channel 3',
			carousel: 'Carousel',
			channel_move_complete: 'Channel Move Complete',
			carousel_classic_trigger: 'Carousel Classic Trigger',
			live_aux_teacher_capture: 'Live Teacher Capture'
		};
		if (specialLabels[source]) return specialLabels[source];
		return source
			.split('_')
			.map((part) => (part ? `${part[0].toUpperCase()}${part.slice(1)}` : part))
			.join(' ');
	}

	async function loadSample(): Promise<boolean> {
		loading = true;
		errorMsg = null;
		try {
			const sessionId = page.params.sessionId;
			const sampleId = page.params.sampleId;
			const res = await fetch(
				`${currentBackendBaseUrl()}/api/classification/training/sessions/${sessionId}/samples/${sampleId}`
			);
			if (!res.ok) throw new Error(await res.text());
			const payload = await res.json();
			sample = (payload?.sample ?? null) as SampleDetail | null;
			availableRetestModels = Array.isArray(payload?.available_retest_models)
				? payload.available_retest_models.filter(
						(value: any): value is RetestModelOption =>
							typeof value?.id === 'string' && typeof value?.label === 'string'
				  )
				: Array.isArray(payload?.available_openrouter_models)
					? payload.available_openrouter_models.filter(
							(value: any): value is RetestModelOption =>
								typeof value?.id === 'string' && typeof value?.label === 'string'
					  )
					: [];
			return true;
		} catch (error: unknown) {
			sample = null;
			errorMsg =
					error instanceof Error && error.message
						? error.message
						: 'Failed to load the sample.';
			return false;
		} finally {
			loading = false;
		}
	}

	function updateLiveRetest(
		localId: string,
		mutate: (entry: LiveRetestCard) => LiveRetestCard
	) {
		liveRetests = liveRetests.map((entry) => (entry.local_id === localId ? mutate(entry) : entry));
	}

	function displayedRetestCards(): RetestCard[] {
		const liveCards = liveRetests.map((entry) => {
			const retest = entry.retest;
			return {
				key: entry.local_id,
				retest_id: retest?.retest_id ?? null,
				model: retest?.model ?? entry.model,
				status: entry.status,
				created_at: retest?.created_at ?? entry.requested_at,
				found: retest?.found ?? null,
				bbox: retest?.bbox ?? null,
				bbox_count:
					typeof retest?.bbox_count === 'number'
						? retest.bbox_count
						: entry.status === 'running'
							? null
							: 0,
				score: retest?.score ?? null,
				error: entry.status === 'error' ? (entry.error ?? retest?.error ?? null) : (retest?.error ?? null),
				overlay_image_url: retest?.overlay_image_url ?? null,
				result_json_url: retest?.result_json_url ?? null,
				inference_ms: retest?.inference_ms ?? null,
				fps: retest?.fps ?? null
			};
		});
		const savedCards = (sample?.retests ?? []).map((retest) => ({
			key: `saved:${retest.retest_id}`,
			retest_id: retest.retest_id,
			model: retest.model,
			status: 'completed' as const,
			created_at: retest.created_at,
			found: retest.found,
			bbox: retest.bbox ?? null,
			bbox_count: retest.bbox_count,
			score: retest.score ?? null,
			error: retest.error ?? null,
			overlay_image_url: retest.overlay_image_url ?? null,
			result_json_url: retest.result_json_url ?? null,
			inference_ms: retest.inference_ms ?? null,
			fps: retest.fps ?? null
		}));
		return [...liveCards, ...savedCards];
	}

	function activeRetestCount(): number {
		return liveRetests.filter((entry) => entry.status === 'running').length;
	}

	function isRetesting(): boolean {
		return activeRetestCount() > 0;
	}

	function isModelRunning(model: string): boolean {
		return liveRetests.some((entry) => entry.model === model && entry.status === 'running');
	}

	function runnableRetestModels(): RetestModelOption[] {
		return availableRetestModels.filter((option) => !isModelRunning(option.id));
	}

	async function runRetestRequest(model: string, runToken: string, index: number): Promise<boolean> {
		const requestedAt = Date.now() / 1000;
		const localId = `${runToken}:${index}:${model}`;
		liveRetests = [
			...liveRetests,
			{
				local_id: localId,
				run_token: runToken,
				model,
				status: 'running',
				requested_at: requestedAt,
				retest: null,
				error: null
			}
		];

		const sessionId = page.params.sessionId;
		const sampleId = page.params.sampleId;
		try {
			const res = await fetch(
				`${currentBackendBaseUrl()}/api/classification/training/sessions/${sessionId}/samples/${sampleId}/retest`,
				{
					method: 'POST',
					headers: { 'Content-Type': 'application/json' },
					body: JSON.stringify({ model_id: model })
				}
			);
			if (!res.ok) {
				throw new Error(await res.text());
			}
			const payload = await res.json();
			const retest = (payload?.retest ?? null) as RetestSummary | null;
			updateLiveRetest(localId, (entry) => ({
				...entry,
				status: 'completed',
				retest,
				error: null
			}));
			const synced = await loadSample();
			if (synced) {
				liveRetests = liveRetests.filter((entry) => !(entry.local_id === localId && entry.status === 'completed'));
			}
			return true;
		} catch (error: unknown) {
			updateLiveRetest(localId, (entry) => ({
				...entry,
				status: 'error',
				error:
					error instanceof Error && error.message
						? error.message
						: 'Retest failed.',
				retest: null
			}));
			return false;
		}
	}

	async function runRetests(models: string[], completionMessage: (succeeded: number, failed: number) => string) {
		const queuedModels = models.filter((model, index) => !models.slice(0, index).includes(model) && !isModelRunning(model));
		if (queuedModels.length === 0) {
			statusMsg = 'Those retests are already running.';
			return;
		}
		errorMsg = null;
		statusMsg =
			queuedModels.length === 1
				? `Queued ${modelLabel(queuedModels[0])}.`
				: `Queued ${queuedModels.length} models.`;
		const runToken = `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
		const results = await Promise.all(
			queuedModels.map((model, index) => runRetestRequest(model, runToken, index))
		);
		const succeeded = results.filter(Boolean).length;
		const failed = results.length - succeeded;
		statusMsg = completionMessage(succeeded, failed);
	}

	async function runRetest(model: string) {
		await runRetests([model], (succeeded, failed) =>
			failed === 0
				? `${modelLabel(model)} finished and was saved to the sample history.`
				: `${modelLabel(model)} finished with ${succeeded} success and ${failed} error.`
		);
	}

	async function runAllRetests() {
		await runRetests(
			runnableRetestModels().map((option) => option.id),
			(succeeded, failed) =>
				failed === 0
					? `Completed ${succeeded} retests and saved them to the sample history.`
					: `Completed ${succeeded} retests with ${failed} error${failed === 1 ? '' : 's'}.`
		);
	}

	async function deleteSample() {
		if (!sample || deleting || isRetesting()) return;
		if (
			typeof window !== 'undefined' &&
			!window.confirm(`Delete sample ${sample.sample_id}? This also removes its saved assets and retests.`)
		) {
			return;
		}

		deleting = true;
		errorMsg = null;
		statusMsg = '';
		try {
			const sessionId = page.params.sessionId;
			const sampleId = page.params.sampleId;
			const res = await fetch(
				`${currentBackendBaseUrl()}/api/classification/training/sessions/${sessionId}/samples/${sampleId}`,
				{ method: 'DELETE' }
			);
			if (!res.ok) throw new Error(await res.text());
			await goto('/classification-samples');
		} catch (error: unknown) {
			errorMsg =
				error instanceof Error && error.message
					? error.message
					: 'Failed to delete the sample.';
		} finally {
			deleting = false;
		}
	}

	async function updateReview(status: string | null) {
		if (!sample || deleting || isRetesting() || reviewing) return;

		reviewing = true;
		errorMsg = null;
		statusMsg = '';
		try {
			const sessionId = page.params.sessionId;
			const sampleId = page.params.sampleId;
			const res = await fetch(
				`${currentBackendBaseUrl()}/api/classification/training/sessions/${sessionId}/samples/${sampleId}/review`,
				{
					method: 'POST',
					headers: { 'Content-Type': 'application/json' },
					body: JSON.stringify({ status })
				}
			);
			if (!res.ok) throw new Error(await res.text());
			const payload = await res.json();
			if (payload?.sample) {
				sample = payload.sample;
			}
			statusMsg =
				status === 'rejected'
					? 'Sample marked as wrong.'
					: status === 'accepted'
						? 'Sample marked as approved.'
						: 'Sample review cleared.';
		} catch (error: unknown) {
			errorMsg =
				error instanceof Error && error.message
					? error.message
					: 'Failed to update the sample review.';
		} finally {
			reviewing = false;
		}
	}

	async function promoteRetest(retestId: string) {
		if (!sample || promoting || deleting || isRetesting() || reviewing) return;
		if (
			typeof window !== 'undefined' &&
			!window.confirm('Use this retest result as ground truth? This will replace the current distilled labels used for training.')
		) {
			return;
		}

		promoting = true;
		errorMsg = null;
		statusMsg = '';
		try {
			const sessionId = page.params.sessionId;
			const sampleId = page.params.sampleId;
			const res = await fetch(
				`${currentBackendBaseUrl()}/api/classification/training/sessions/${sessionId}/samples/${sampleId}/promote-retest`,
				{
					method: 'POST',
					headers: { 'Content-Type': 'application/json' },
					body: JSON.stringify({ retest_id: retestId })
				}
			);
			if (!res.ok) throw new Error(await res.text());
			const payload = await res.json();
			if (payload?.sample) {
				sample = payload.sample;
				cacheBuster++;
			}
			statusMsg = 'Retest promoted to ground truth. YOLO labels and distill overlay have been updated.';
		} catch (error: unknown) {
			errorMsg =
				error instanceof Error && error.message
					? error.message
					: 'Failed to promote the retest.';
		} finally {
			promoting = false;
		}
	}

	function svgCoords(e: PointerEvent, svg: SVGSVGElement): { x: number; y: number } {
		const rect = svg.getBoundingClientRect();
		return {
			x: ((e.clientX - rect.left) / rect.width) * 1000,
			y: ((e.clientY - rect.top) / rect.height) * 1000,
		};
	}

	function onDrawPointerDown(e: PointerEvent) {
		if (!drawMode) return;
		const svg = e.currentTarget as unknown as SVGSVGElement;
		const { x, y } = svgCoords(e, svg);
		drawingBox = { startX: x, startY: y, currentX: x, currentY: y };
		(svg as unknown as Element).setPointerCapture(e.pointerId);
	}

	function onDrawPointerMove(e: PointerEvent) {
		if (!drawingBox || !drawMode) return;
		const svg = e.currentTarget as unknown as SVGSVGElement;
		const { x, y } = svgCoords(e, svg);
		drawingBox = { ...drawingBox, currentX: x, currentY: y };
	}

	function onDrawPointerUp() {
		if (!drawingBox) return;
		const x1 = Math.min(drawingBox.startX, drawingBox.currentX);
		const y1 = Math.min(drawingBox.startY, drawingBox.currentY);
		const x2 = Math.max(drawingBox.startX, drawingBox.currentX);
		const y2 = Math.max(drawingBox.startY, drawingBox.currentY);
		if (x2 - x1 > 10 && y2 - y1 > 10) {
			pendingBoxes = [
				...pendingBoxes,
				{ bbox: [Math.round(x1), Math.round(y1), Math.round(x2), Math.round(y2)] as [number, number, number, number] },
			];
		}
		drawingBox = null;
	}

	async function saveManualBoxes() {
		if (!sample || savingBoxes || pendingBoxes.length === 0) return;
		savingBoxes = true;
		errorMsg = null;
		statusMsg = '';
		try {
			const sessionId = page.params.sessionId;
			const sampleId = page.params.sampleId;
			const res = await fetch(
				`${currentBackendBaseUrl()}/api/classification/training/sessions/${sessionId}/samples/${sampleId}/review`,
				{
					method: 'POST',
					headers: { 'Content-Type': 'application/json' },
					body: JSON.stringify({
						status: 'accepted',
						added_boxes: pendingBoxes.map((b) => ({ bbox: b.bbox, normalized: true })),
					}),
				}
			);
			if (!res.ok) throw new Error(await res.text());
			const payload = await res.json();
			if (payload?.sample) {
				sample = payload.sample;
				cacheBuster++;
			}
			pendingBoxes = [];
			drawMode = false;
			statusMsg = `Added ${pendingBoxes.length || 'new'} manual detection(s) to ground truth.`;
		} catch (error: unknown) {
			errorMsg = error instanceof Error && error.message ? error.message : 'Failed to save manual boxes.';
		} finally {
			savingBoxes = false;
		}
	}

	async function deleteRetest(retestId: string) {
		if (!sample || deleting || isRetesting() || reviewing) return;
		const sessionId = page.params.sessionId;
		const sampleId = page.params.sampleId;
		try {
			const res = await fetch(
				`${currentBackendBaseUrl()}/api/classification/training/sessions/${sessionId}/samples/${sampleId}/retests/${retestId}`,
				{ method: 'DELETE' }
			);
			if (!res.ok) throw new Error(await res.text());
			const data = await res.json();
			if (data?.sample) sample = data.sample;
		} catch (error: unknown) {
			errorMsg =
				error instanceof Error && error.message
					? error.message
					: 'Failed to delete the retest.';
		}
	}

	async function clearAllRetests() {
		if (!sample || deleting || isRetesting() || reviewing) return;
		if (
			typeof window !== 'undefined' &&
			!window.confirm('Delete all retest results?')
		) {
			return;
		}
		const sessionId = page.params.sessionId;
		const sampleId = page.params.sampleId;
		try {
			const res = await fetch(
				`${currentBackendBaseUrl()}/api/classification/training/sessions/${sessionId}/samples/${sampleId}/retests`,
				{ method: 'DELETE' }
			);
			if (!res.ok) throw new Error(await res.text());
			const data = await res.json();
			if (data?.sample) sample = data.sample;
			statusMsg = 'All retests cleared.';
		} catch (error: unknown) {
			errorMsg =
				error instanceof Error && error.message
					? error.message
					: 'Failed to clear retests.';
		}
	}

	$effect(() => {
		const routeKey = `${page.params.sessionId}/${page.params.sampleId}/${
			(manager.selectedMachine?.status === 'connected' ? manager.selectedMachine.url : null) ?? '__local__'
		}`;
		if (routeKey !== loadedKey) {
			loadedKey = routeKey;
			void loadSample();
		}
	});
</script>

<div class="dark:bg-bg-dark min-h-screen bg-bg p-6">
	<AppHeader />

	<div class="flex flex-col gap-6">
		<div class="flex flex-wrap items-start justify-between gap-3">
			<div>
					<div class="flex items-center gap-4">
						<a
							href="/classification-samples"
							class="text-sm text-sky-600 transition-colors hover:text-sky-500 dark:text-sky-300"
						>
							← Back to samples
						</a>
						{#if sample?.prev_sample_id || sample?.next_sample_id}
							<span class="dark:text-text-muted-dark text-xs text-text-muted">|</span>
							{#if sample?.prev_sample_id}
								<a
									href="/classification-samples/{page.params.sessionId}/{sample.prev_sample_id}"
									class="text-sm text-sky-600 transition-colors hover:text-sky-500 dark:text-sky-300"
								>
									← Previous
								</a>
							{:else}
								<span class="text-sm text-gray-400 dark:text-gray-600">← Previous</span>
							{/if}
							{#if sample?.next_sample_id}
								<a
									href="/classification-samples/{page.params.sessionId}/{sample.next_sample_id}"
									class="text-sm text-sky-600 transition-colors hover:text-sky-500 dark:text-sky-300"
								>
									Next →
								</a>
							{:else}
								<span class="text-sm text-gray-400 dark:text-gray-600">Next →</span>
							{/if}
						{/if}
					</div>
					<h2 class="dark:text-text-dark mt-2 text-2xl font-semibold text-text">
						{sample?.sample_id ?? 'Sample'}
					</h2>
				<p class="dark:text-text-muted-dark mt-1 text-sm text-text-muted">
					{sample?.session_name ?? 'Loading session...'}
				</p>
			</div>
			<div class="flex flex-wrap items-center gap-2">
				<button
					type="button"
					onclick={loadSample}
					disabled={loading || deleting || reviewing}
					class="dark:border-border-dark dark:bg-surface-dark dark:text-text-dark dark:hover:bg-bg-dark border border-border bg-surface px-3 py-2 text-sm text-text transition-colors hover:bg-bg disabled:cursor-not-allowed disabled:opacity-50"
				>
					{loading ? 'Loading...' : 'Reload'}
				</button>
				<button
					type="button"
					onclick={() => updateReview('rejected')}
					disabled={!sample || loading || deleting || isRetesting() || reviewing}
					class="border px-3 py-2 text-sm transition-colors disabled:cursor-not-allowed disabled:opacity-50 {sample?.review_status === 'rejected' ? 'border-red-500 bg-red-500 text-white dark:border-red-500 dark:bg-red-500 dark:text-white' : 'border-red-500 bg-red-500/10 text-red-700 hover:bg-red-500/20 dark:text-red-300'}"
				>
					{reviewing && sample?.review_status !== 'rejected' ? 'Saving...' : 'Mark as Wrong'}
				</button>
				<button
					type="button"
					onclick={() => updateReview('accepted')}
					disabled={!sample || loading || deleting || isRetesting() || reviewing}
					class="border px-3 py-2 text-sm transition-colors disabled:cursor-not-allowed disabled:opacity-50 {sample?.review_status === 'accepted' ? 'border-emerald-500 bg-emerald-500 text-white dark:border-emerald-500 dark:bg-emerald-500 dark:text-white' : 'border-emerald-500 bg-emerald-500/10 text-emerald-700 hover:bg-emerald-500/20 dark:text-emerald-300'}"
				>
					{reviewing && sample?.review_status !== 'accepted' ? 'Saving...' : 'Mark as Approved'}
				</button>
				<button
					type="button"
					onclick={() => updateReview(null)}
					disabled={!sample || loading || deleting || isRetesting() || reviewing || !sample.review_status}
					class="dark:border-border-dark dark:bg-bg-dark dark:text-text-dark dark:hover:bg-surface-dark border border-border bg-bg px-3 py-2 text-sm text-text transition-colors hover:bg-surface disabled:cursor-not-allowed disabled:opacity-50"
				>
					{reviewing && sample?.review_status ? 'Saving...' : 'Clear Review'}
				</button>
				<span class="mx-1 hidden sm:inline"></span>
				<button
					type="button"
					onclick={deleteSample}
					disabled={!sample || loading || deleting || isRetesting() || reviewing}
					class="border border-gray-400 bg-gray-100/50 px-3 py-2 text-sm text-red-600 transition-colors hover:bg-gray-200/70 disabled:cursor-not-allowed disabled:opacity-50 dark:border-gray-600 dark:bg-gray-800/50 dark:text-red-400 dark:hover:bg-gray-700/50"
				>
					{deleting ? 'Deleting...' : 'Delete Sample'}
				</button>
			</div>
		</div>

		{#if errorMsg}
			<div class="border border-red-400 bg-red-50 px-3 py-2 text-sm text-red-600 dark:border-red-600 dark:bg-red-900/20 dark:text-red-400">
				{errorMsg}
			</div>
		{:else if statusMsg}
			<div class="border border-emerald-400 bg-emerald-50 px-3 py-2 text-sm text-emerald-700 dark:border-emerald-600 dark:bg-emerald-900/20 dark:text-emerald-300">
				{statusMsg}
			</div>
		{/if}

		{#if sample}
			<div class="grid gap-6 xl:grid-cols-[minmax(0,1fr)_22rem]">
				<div class="flex flex-col gap-6">
						<div class="dark:border-border-dark dark:bg-surface-dark border border-border bg-surface p-4">
							<div class="mb-3 flex items-center justify-between">
								<div class="dark:text-text-dark text-sm font-semibold text-text">{sourceLabel(sample.source_role ?? sample.camera ?? 'Classification Chamber')}</div>
								<div class="flex items-center gap-3">
									{#if assetUrl(sample.classification_result?.selected_crop_url)}
										<label class="flex cursor-pointer items-center gap-1.5 text-xs">
											<span class="dark:text-text-muted-dark text-text-muted">Crop</span>
											<button
												type="button"
												onclick={() => (showClassificationCrop = !showClassificationCrop)}
												class="relative inline-flex h-4 w-7 items-center rounded-full transition-colors {showClassificationCrop ? 'bg-sky-500' : 'dark:bg-gray-600 bg-gray-300'}"
												role="switch"
												aria-checked={showClassificationCrop}
												aria-label="Toggle classification crop preview"
											>
												<span class="inline-block h-3 w-3 transform rounded-full bg-white shadow transition-transform {showClassificationCrop ? 'translate-x-3' : 'translate-x-0.5'}"></span>
											</button>
										</label>
									{/if}
									{#if assetUrl(sample.distill_result?.overlay_image_url)}
										<label class="flex cursor-pointer items-center gap-1.5 text-xs">
											<span class="dark:text-text-muted-dark text-text-muted">Distill</span>
											<button
												type="button"
												onclick={() => (showDistillOverlay = !showDistillOverlay)}
												class="relative inline-flex h-4 w-7 items-center rounded-full transition-colors {showDistillOverlay ? 'bg-emerald-500' : 'dark:bg-gray-600 bg-gray-300'}"
												role="switch"
												aria-checked={showDistillOverlay}
												aria-label="Toggle distill overlay preview"
											>
												<span class="inline-block h-3 w-3 transform rounded-full bg-white shadow transition-transform {showDistillOverlay ? 'translate-x-3' : 'translate-x-0.5'}"></span>
											</button>
										</label>
									{/if}
								<button
									type="button"
									onclick={() => { drawMode = !drawMode; if (!drawMode) { drawingBox = null; } }}
									class="rounded px-2 py-0.5 text-xs transition-colors {drawMode
										? 'bg-cyan-500/20 text-cyan-600 ring-1 ring-cyan-500 dark:text-cyan-300'
										: 'bg-gray-100 text-gray-500 hover:bg-gray-200 dark:bg-gray-700 dark:text-gray-400 dark:hover:bg-gray-600'}"
								>
									{drawMode ? 'Drawing...' : 'Draw Box'}
								</button>
								</div>
							</div>
							<div class="dark:bg-bg-dark relative aspect-[4/3] bg-bg" id="sample-image-container">
								{#if assetUrl(sample.input_image_url)}
									<img
										src={assetUrl(sample.input_image_url) ?? undefined}
										alt={`Raw sample ${sample.sample_id}`}
										class="absolute inset-0 h-full w-full object-contain"
									/>
								{/if}
								{#if showClassificationCrop && assetUrl(sample.classification_result?.selected_crop_url)}
									<img
										src={assetUrl(sample.classification_result?.selected_crop_url) ?? undefined}
										alt={`Classification crop ${sample.sample_id}`}
										class="absolute inset-0 h-full w-full object-contain"
									/>
								{/if}
								{#if showDistillOverlay && !drawMode && assetUrl(sample.distill_result?.overlay_image_url)}
									<img
										src={assetUrl(sample.distill_result?.overlay_image_url) ?? undefined}
										alt={`Distilled overlay ${sample.sample_id}`}
										class="absolute inset-0 h-full w-full object-contain"
									/>
								{/if}
								{#if drawMode || pendingBoxes.length > 0}
									<svg
										class="absolute inset-0 h-full w-full {drawMode ? 'cursor-crosshair' : 'pointer-events-none'}"
										viewBox="0 0 1000 1000"
										preserveAspectRatio="xMidYMid meet"
										onpointerdown={onDrawPointerDown}
										onpointermove={onDrawPointerMove}
										onpointerup={onDrawPointerUp}
									>
										{#each pendingBoxes as box, i}
											<rect
												x={box.bbox[0]} y={box.bbox[1]}
												width={box.bbox[2] - box.bbox[0]} height={box.bbox[3] - box.bbox[1]}
												fill="none" stroke="#06b6d4" stroke-width="3" stroke-dasharray="8 4"
											/>
											<text x={box.bbox[0] + 4} y={box.bbox[1] + 16} fill="#06b6d4" font-size="14" font-weight="bold">Added {i + 1}</text>
										{/each}
										{#if drawingBox}
											{@const x = Math.min(drawingBox.startX, drawingBox.currentX)}
											{@const y = Math.min(drawingBox.startY, drawingBox.currentY)}
											{@const w = Math.abs(drawingBox.currentX - drawingBox.startX)}
											{@const h = Math.abs(drawingBox.currentY - drawingBox.startY)}
											<rect {x} {y} width={w} height={h} fill="none" stroke="#06b6d4" stroke-width="2" stroke-dasharray="4 4" />
										{/if}
									</svg>
								{/if}
							</div>
							{#if pendingBoxes.length > 0}
								<div class="mt-2 flex items-center gap-2">
									<span class="text-xs text-cyan-500">{pendingBoxes.length} box(es) drawn</span>
									<button type="button" onclick={() => { pendingBoxes = pendingBoxes.slice(0, -1); }} class="text-xs text-gray-400 hover:text-gray-600 dark:hover:text-gray-200">Undo</button>
									<button type="button" onclick={() => { pendingBoxes = []; drawMode = false; }} class="text-xs text-gray-400 hover:text-gray-600 dark:hover:text-gray-200">Cancel</button>
									<button
										type="button"
										onclick={saveManualBoxes}
										disabled={savingBoxes}
										class="rounded border border-cyan-500 bg-cyan-500/10 px-3 py-1 text-xs text-cyan-600 transition-colors hover:bg-cyan-500/20 disabled:opacity-50 dark:text-cyan-300"
									>{savingBoxes ? 'Saving...' : 'Save to Ground Truth'}</button>
								</div>
							{/if}
						</div>

					{#if sample.bottom_frame_url}
						<div class="grid gap-4 lg:grid-cols-2">
							{#if assetUrl(sample.bottom_frame_url)}
								<div class="dark:border-border-dark dark:bg-surface-dark border border-border bg-surface p-4">
									<div class="dark:text-text-dark mb-3 text-sm font-semibold text-text">Bottom Full Frame</div>
									<div class="dark:bg-bg-dark aspect-[4/3] bg-bg">
										<img src={assetUrl(sample.bottom_frame_url) ?? undefined} alt="Bottom full frame" class="h-full w-full object-contain" />
									</div>
								</div>
							{/if}
						</div>
					{/if}

					<div class="dark:border-border-dark dark:bg-surface-dark border border-border bg-surface p-4">
						<div class="flex items-center justify-between gap-3">
							<div>
								<div class="dark:text-text-dark text-sm font-semibold text-text">Model Comparisons</div>
								<div class="dark:text-text-muted-dark mt-1 text-xs text-text-muted">
									Detection results from different models on the saved raw crop.
								</div>
							</div>
							{#if displayedRetestCards().length > 0}
								<button
									type="button"
									onclick={clearAllRetests}
									disabled={deleting || isRetesting() || reviewing}
									class="flex-shrink-0 border border-gray-400 bg-gray-100/50 px-2 py-1 text-xs text-red-600 transition-colors hover:bg-gray-200/70 disabled:cursor-not-allowed disabled:opacity-50 dark:border-gray-600 dark:bg-gray-800/50 dark:text-red-400 dark:hover:bg-gray-700/50"
								>
									Clear All
								</button>
							{/if}
						</div>

						{#if activeRetestCount() > 0}
							<div class="dark:text-text-muted-dark mt-3 text-xs text-text-muted">
								{activeRetestCount()} retest{activeRetestCount() === 1 ? '' : 's'} still running...
							</div>
						{/if}

						<div class="mt-4 grid gap-4 md:grid-cols-2 xl:grid-cols-3">
							{#if displayedRetestCards().length === 0}
								<div class="dark:text-text-muted-dark text-sm text-text-muted md:col-span-2 xl:col-span-3">
									No retests saved yet.
								</div>
							{:else}
								{#each displayedRetestCards() as retest (retest.key)}
									<article class="group/card dark:border-border-dark dark:bg-bg-dark relative overflow-hidden border border-border bg-bg">
										{#if retest.status !== 'running' && retest.retest_id}
											<button
												type="button"
												onclick={() => deleteRetest(retest.retest_id!)}
												disabled={deleting || isRetesting() || reviewing}
												class="absolute right-1 top-1 z-10 flex h-5 w-5 items-center justify-center rounded-full bg-black/50 text-xs text-white opacity-0 transition-opacity hover:bg-black/70 disabled:cursor-not-allowed group-hover/card:opacity-100"
												title="Delete this retest"
											>
												&times;
											</button>
										{/if}
										<div class="dark:bg-surface-dark aspect-[4/3] bg-surface">
											{#if retest.status === 'running'}
												<div class="flex h-full flex-col items-center justify-center gap-3">
													<div class="h-10 w-10 animate-spin rounded-full border-4 border-sky-500/20 border-t-sky-500"></div>
													<div class="text-sm text-sky-600 dark:text-sky-300">Running...</div>
												</div>
											{:else if assetUrl(retest.overlay_image_url)}
												<img
													src={assetUrl(retest.overlay_image_url) ?? undefined}
													alt={`Retest ${retest.key}`}
													class="h-full w-full object-contain"
												/>
											{:else}
												<div class="dark:text-text-muted-dark flex h-full items-center justify-center text-sm text-text-muted">
													{retest.status === 'error' ? 'Retest failed' : 'No overlay saved'}
												</div>
											{/if}
										</div>
										<div class="px-2.5 py-2">
											<div class="flex items-baseline justify-between gap-2">
												<div class="dark:text-text-dark text-sm font-semibold text-text">{modelLabel(retest.model)}</div>
												{#if retest.status === 'running'}
													<span class="text-xs font-medium text-sky-600 dark:text-sky-300">Running</span>
												{:else if retest.status === 'error'}
													<span class="text-xs font-medium text-red-600 dark:text-red-400">Error</span>
												{:else}
													<span class="text-xs font-medium text-emerald-700 dark:text-emerald-300">Saved</span>
												{/if}
											</div>
											<div class="dark:text-text-muted-dark mt-0.5 flex items-center gap-3 text-xs text-text-muted">
												<span>{formatDate(retest.created_at)}</span>
												<span>{retest.found === null ? '' : retest.found ? `${retest.bbox_count} det` : 'No det'}{typeof retest.score === 'number' ? ` / ${retest.score.toFixed(2)}` : ''}</span>
												{#if retest.bbox}<span>{bboxSummary(retest.bbox)}</span>{/if}
												{#if typeof retest.inference_ms === 'number'}
													<span class="font-mono text-violet-600 dark:text-violet-300">{retest.inference_ms.toFixed(1)}ms / {retest.fps?.toFixed(0) ?? '?'} FPS</span>
												{/if}
											</div>
											<div class="dark:text-text-muted-dark mt-0.5 flex items-center gap-2 font-mono text-xs text-text-muted">
												<span>{retest.model}</span>
												{#if retest.status !== 'running' && assetUrl(retest.result_json_url)}
													<a
														href={assetUrl(retest.result_json_url) ?? undefined}
														target="_blank"
														rel="noreferrer"
														class="text-sky-600 hover:text-sky-500 dark:text-sky-300"
													>JSON</a>
												{/if}
											</div>
											{#if retest.error}
												<div class="mt-1 text-xs text-red-600 dark:text-red-400">{retest.error}</div>
											{/if}
											{#if retest.status === 'completed' && retest.retest_id && retest.found !== false}
												<button
													type="button"
													onclick={() => promoteRetest(retest.retest_id!)}
													disabled={promoting || deleting || isRetesting() || reviewing}
													class="mt-1.5 w-full border border-amber-500 bg-amber-500/10 px-2 py-1 text-xs text-amber-700 transition-colors hover:bg-amber-500/20 disabled:cursor-not-allowed disabled:opacity-50 dark:text-amber-300"
												>
													{promoting ? 'Promoting...' : 'Use as Ground Truth'}
												</button>
											{/if}
										</div>
									</article>
								{/each}
							{/if}
						</div>
					</div>
				</div>

				<div class="flex flex-col gap-4">
						<div class="dark:border-border-dark dark:bg-surface-dark border border-border bg-surface p-4">
							<div class="dark:text-text-dark text-sm font-semibold text-text">Sample Meta</div>
							<div class="mt-2 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1">
								<span class="dark:text-text-muted-dark text-xs text-text-muted">Camera</span>
								<span class="dark:text-text-dark text-sm text-text">{sourceLabel(sample.source_role ?? sample.preferred_camera ?? sample.camera ?? 'n/a')}</span>
								{#if sample.detection_bbox_count !== undefined && sample.detection_bbox_count !== null}
									<span class="dark:text-text-muted-dark text-xs text-text-muted">Detections</span>
									<span class="dark:text-text-dark text-sm text-text">{sample.detection_bbox_count}</span>
								{/if}
								<span class="dark:text-text-muted-dark text-xs text-text-muted">Distill</span>
								<span class="dark:text-text-dark text-sm text-text">{sample.distill_status}</span>
								<span class="dark:text-text-muted-dark text-xs text-text-muted">Review</span>
								<span class="dark:text-text-dark text-sm text-text">{sample.review_status ? sourceLabel(sample.review_status) : 'Unreviewed'}</span>
							</div>
							{#if expandMeta}
								<div class="mt-1 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1">
									<span class="dark:text-text-muted-dark text-xs text-text-muted">Source</span>
									<span class="dark:text-text-dark text-sm text-text">{sourceLabel(sample.source)}</span>
									{#if sample.capture_reason}
										<span class="dark:text-text-muted-dark text-xs text-text-muted">Capture Reason</span>
										<span class="dark:text-text-dark text-sm text-text">{sourceLabel(sample.capture_reason)}</span>
									{/if}
									<span class="dark:text-text-muted-dark text-xs text-text-muted">Processor</span>
									<span class="dark:text-text-dark text-sm text-text">{sample.processor}</span>
									{#if sample.detection_algorithm}
										<span class="dark:text-text-muted-dark text-xs text-text-muted">Detection Algo</span>
										<span class="dark:text-text-dark text-sm text-text">{sample.detection_algorithm}</span>
									{/if}
									{#if sample.detection_openrouter_model}
										<span class="dark:text-text-muted-dark text-xs text-text-muted">Capture Model</span>
										<span class="dark:text-text-dark text-sm text-text">{modelLabel(sample.detection_openrouter_model)}</span>
									{/if}
									<span class="dark:text-text-muted-dark text-xs text-text-muted">Captured</span>
									<span class="dark:text-text-dark text-sm text-text">{formatDate(sample.captured_at)}</span>
									{#if sample.review_updated_at}
										<span class="dark:text-text-muted-dark text-xs text-text-muted">Review Updated</span>
										<span class="dark:text-text-dark text-sm text-text">{formatDate(sample.review_updated_at)}</span>
									{/if}
								</div>
							{/if}
							<button type="button" onclick={() => (expandMeta = !expandMeta)} class="mt-1.5 text-xs text-sky-600 hover:text-sky-500 dark:text-sky-300">
								{expandMeta ? 'Show less' : 'Show more'}
							</button>
						</div>

						<div class="dark:border-border-dark dark:bg-surface-dark border border-border bg-surface p-4">
							<div class="dark:text-text-dark text-sm font-semibold text-text">Classification</div>
							{#if sample.classification_result}
								<div class="mt-2 flex items-start gap-3">
									{#if assetUrl(sample.classification_result.preview_url)}
										<img
											src={assetUrl(sample.classification_result.preview_url) ?? undefined}
											alt="Brickognize match"
											class="h-16 w-16 flex-shrink-0 object-contain dark:bg-bg-dark bg-bg"
										/>
									{/if}
									<div class="min-w-0">
										<div class="dark:text-text-dark text-sm font-semibold text-text">{sample.classification_result.part_id ?? 'unknown'}</div>
										{#if sample.classification_result.item_name}
											<div class="dark:text-text-muted-dark text-sm font-medium text-text-muted leading-tight">{sample.classification_result.item_name}</div>
										{/if}
										{#if sample.classification_result.item_category}
											<div class="dark:text-text-muted-dark text-xs text-text-muted">{sample.classification_result.item_category}</div>
										{/if}
									</div>
								</div>
								{#if expandClassification}
									<div class="mt-2 grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5">
										<span class="dark:text-text-muted-dark text-xs text-text-muted">Provider</span>
										<span class="dark:text-text-dark text-sm text-text">{sample.classification_result.provider ?? 'brickognize'}</span>
										<span class="dark:text-text-muted-dark text-xs text-text-muted">Status</span>
										<span class="dark:text-text-dark text-sm text-text">{sourceLabel(sample.classification_result.status)}</span>
										<span class="dark:text-text-muted-dark text-xs text-text-muted">Color</span>
										<span class="dark:text-text-dark text-sm text-text">{sample.classification_result.color_name ?? 'n/a'}</span>
										{#if sample.classification_result.confidence !== null && sample.classification_result.confidence !== undefined}
											<span class="dark:text-text-muted-dark text-xs text-text-muted">Confidence</span>
											<span class="dark:text-text-dark text-sm text-text">{sample.classification_result.confidence.toFixed(2)}</span>
										{/if}
										{#if sample.classification_result.source_view}
											<span class="dark:text-text-muted-dark text-xs text-text-muted">View</span>
											<span class="dark:text-text-dark text-sm text-text">{sample.classification_result.source_view}</span>
										{/if}
										<span class="dark:text-text-muted-dark text-xs text-text-muted">Top Cand.</span>
										<span class="dark:text-text-dark text-sm text-text">{sample.classification_result.top_items_count ?? 0} items / {sample.classification_result.top_colors_count ?? 0} colors</span>
										<span class="dark:text-text-muted-dark text-xs text-text-muted">Bottom Cand.</span>
										<span class="dark:text-text-dark text-sm text-text">{sample.classification_result.bottom_items_count ?? 0} items / {sample.classification_result.bottom_colors_count ?? 0} colors</span>
										{#if sample.classification_result.completed_at}
											<span class="dark:text-text-muted-dark text-xs text-text-muted">Completed</span>
											<span class="dark:text-text-dark text-sm text-text">{formatDate(sample.classification_result.completed_at)}</span>
										{/if}
										{#if assetUrl(sample.classification_result.result_json_url)}
											<span class="dark:text-text-muted-dark text-xs text-text-muted">Result</span>
											<a
												href={assetUrl(sample.classification_result.result_json_url) ?? undefined}
												target="_blank"
												rel="noreferrer"
												class="text-sm text-sky-600 hover:text-sky-500 dark:text-sky-300"
											>
												Open JSON
											</a>
										{/if}
									</div>
									{#if sample.classification_result.error}
										<div class="mt-1 text-xs text-red-600 dark:text-red-400">{sample.classification_result.error}</div>
									{/if}
								{/if}
								<button type="button" onclick={() => (expandClassification = !expandClassification)} class="mt-1.5 text-xs text-sky-600 hover:text-sky-500 dark:text-sky-300">
									{expandClassification ? 'Show less' : 'Show more'}
								</button>
							{:else}
								<div class="dark:text-text-muted-dark mt-3 text-sm text-text-muted">
									No saved classification result yet.
								</div>
							{/if}
						</div>

						<div class="dark:border-border-dark dark:bg-surface-dark border border-border bg-surface p-4">
							<div class="dark:text-text-dark text-sm font-semibold text-text">Distillation</div>
						{#if sample.distill_result}
							<div class="mt-2 flex items-center gap-3">
								<span class="dark:text-text-muted-dark text-xs text-text-muted">Detections:</span>
								<span class="dark:text-text-dark text-sm font-medium text-text">{sample.distill_result.detections}</span>
								{#if assetUrl(sample.distill_result.yolo_label_url)}
									<a
										href={assetUrl(sample.distill_result.yolo_label_url) ?? undefined}
										target="_blank"
										rel="noreferrer"
										class="text-xs text-sky-600 hover:text-sky-500 dark:text-sky-300"
									>
										YOLO label
									</a>
								{/if}
							</div>
							{#if expandDistillation}
								<div class="mt-1 grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5">
									<span class="dark:text-text-muted-dark text-xs text-text-muted">Processed</span>
									<span class="dark:text-text-dark text-sm text-text">{formatDate(sample.distill_result.processed_at)}</span>
									{#if assetUrl(sample.distill_result.result_json_url)}
										<span class="dark:text-text-muted-dark text-xs text-text-muted">Result</span>
										<a
											href={assetUrl(sample.distill_result.result_json_url) ?? undefined}
											target="_blank"
											rel="noreferrer"
											class="text-sm text-sky-600 hover:text-sky-500 dark:text-sky-300"
										>
											Open JSON
										</a>
									{/if}
								</div>
							{/if}
							<button type="button" onclick={() => (expandDistillation = !expandDistillation)} class="mt-1.5 text-xs text-sky-600 hover:text-sky-500 dark:text-sky-300">
								{expandDistillation ? 'Show less' : 'Show more'}
							</button>
						{:else if sample.distill_error}
							<div class="mt-2 text-xs text-red-600 dark:text-red-400">{sample.distill_error}</div>
						{:else if sample.distill_status === 'skipped'}
							<div class="dark:text-text-muted-dark mt-2 text-xs text-text-muted">
								Skipped for this source. You can still retest with any available model.
							</div>
						{:else}
							<div class="dark:text-text-muted-dark mt-2 text-xs text-text-muted">
								No distillation result saved yet.
							</div>
						{/if}
					</div>

						<div class="dark:border-border-dark dark:bg-surface-dark border border-border bg-surface p-4">
							<div class="dark:text-text-dark text-sm font-semibold text-text">Run Models</div>
							<button
								type="button"
								onclick={runAllRetests}
								disabled={runnableRetestModels().length === 0}
								class="mt-3 w-full border border-sky-500 bg-sky-500/15 px-2 py-1.5 text-xs text-sky-700 transition-colors hover:bg-sky-500/25 disabled:cursor-not-allowed disabled:opacity-50 dark:text-sky-300"
							>
								{#if activeRetestCount() > 0}
									{`Run Remaining Models (${runnableRetestModels().length})`}
								{:else}
									{`Run All Models (${availableRetestModels.length})`}
								{/if}
							</button>

							{#if availableRetestModels.length > 0}
								{@const localModels = availableRetestModels.filter((m) => m.id.startsWith('local_detector:'))}
								{@const cloudModels = availableRetestModels.filter((m) => !m.id.startsWith('local_detector:'))}

								{#if localModels.length > 0}
									<div class="dark:text-text-muted-dark mt-3 text-xs font-semibold uppercase tracking-wider text-text-muted">Local Detectors</div>
									<div class="mt-1 flex flex-col gap-0.5">
										{#each localModels as model}
											<button
												type="button"
												onclick={() => void runRetest(model.id)}
												disabled={isModelRunning(model.id)}
												class="group flex items-center gap-1.5 px-1.5 py-1 text-left text-xs transition-colors hover:bg-sky-500/10 disabled:cursor-not-allowed disabled:opacity-50 dark:hover:bg-sky-500/10"
											>
													<span class="text-sky-600 dark:text-sky-400 {isModelRunning(model.id) ? 'opacity-100' : 'opacity-0 group-hover:opacity-100'}">
														{isModelRunning(model.id) ? '…' : '▶'}
												</span>
												<span class="dark:text-text-dark min-w-0 flex-1 truncate text-text">{model.label.replace('Local Detector - ', '')}</span>
											</button>
										{/each}
									</div>
								{/if}

								{#if cloudModels.length > 0}
									<div class="dark:text-text-muted-dark mt-3 text-xs font-semibold uppercase tracking-wider text-text-muted">Cloud Models</div>
									<div class="mt-1 flex flex-col gap-0.5">
										{#each cloudModels as model}
											<button
												type="button"
												onclick={() => void runRetest(model.id)}
												disabled={isModelRunning(model.id)}
												class="group flex items-center gap-1.5 px-1.5 py-1 text-left text-xs transition-colors hover:bg-sky-500/10 disabled:cursor-not-allowed disabled:opacity-50 dark:hover:bg-sky-500/10"
											>
													<span class="text-sky-600 dark:text-sky-400 {isModelRunning(model.id) ? 'opacity-100' : 'opacity-0 group-hover:opacity-100'}">
														{isModelRunning(model.id) ? '…' : '▶'}
												</span>
												<span class="dark:text-text-dark min-w-0 flex-1 truncate text-text">{model.label}</span>
											</button>
										{/each}
									</div>
								{/if}
							{:else}
								<div class="dark:text-text-muted-dark mt-3 text-xs text-text-muted">No models available.</div>
							{/if}
						</div>
				</div>
			</div>
		{/if}
	</div>
</div>
