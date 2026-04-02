<script lang="ts">
	import { onMount } from 'svelte';
	import {
		createImageAnnotator,
		ShapeType,
		type AnnotationBody,
		type DrawingTool,
		type DrawingStyle,
		type ImageAnnotation,
		type ImageAnnotator as AnnotoriousImageAnnotator
	} from '@annotorious/annotorious';
	import '@annotorious/annotorious/annotorious.css';
	import { api, type SavedSampleAnnotation } from '$lib/api';
	import { auth } from '$lib/auth.svelte';
	import { AnnotatorApi } from './annotator-api.svelte';

	export interface SeedBox {
		x: number;
		y: number;
		w: number;
		h: number;
		source: 'primary' | 'candidate';
	}

	interface Props {
		sampleId: string;
		imageUrl: string;
		imageAlt?: string;
		imageWidth?: number | null;
		imageHeight?: number | null;
		seedBoxes?: SeedBox[];
		persistedAnnotations?: SavedSampleAnnotation[];
		hasPersistedAnnotations?: boolean;
		isActive?: boolean;
		/** When provided, toolbar is rendered externally via this API bridge. */
		externalApi?: AnnotatorApi;
	}

	type Bounds = {
		minX: number;
		minY: number;
		maxX: number;
		maxY: number;
	};

	type ShapeLike = {
		type?: string;
		geometry?: Record<string, unknown>;
	};

	const annotationPalette = [
		{ stroke: '#22c55e', fill: '#22c55e' },
		{ stroke: '#06b6d4', fill: '#06b6d4' },
		{ stroke: '#f97316', fill: '#f97316' },
		{ stroke: '#a855f7', fill: '#a855f7' },
		{ stroke: '#eab308', fill: '#eab308' },
		{ stroke: '#ef4444', fill: '#ef4444' }
	] as const;

	let {
		sampleId,
		imageUrl,
		imageAlt = 'Sample annotation workspace',
		imageWidth = null,
		imageHeight = null,
		seedBoxes = [],
		persistedAnnotations = [],
		hasPersistedAnnotations = false,
		isActive = true,
		externalApi
	}: Props = $props();

	const hasExternalControls = $derived(!!externalApi);

	let imageEl = $state<HTMLImageElement | null>(null);
	let annotator: AnnotoriousImageAnnotator<ImageAnnotation, ImageAnnotation> | null = null;
	let detachHandlers: (() => void) | null = null;

	let loadedWidth = $state(0);
	let loadedHeight = $state(0);
	let annotations = $state<ImageAnnotation[]>([]);
	let selectedAnnotationIds = $state<string[]>([]);
	let activeTool = $state<DrawingTool>('rectangle');
	let feedback = $state<string | null>(null);
	let feedbackTone = $state<'neutral' | 'success' | 'danger'>('neutral');
	let saving = $state(false);
	let savedRecords = $state<SavedSampleAnnotation[]>([]);
	let savedSignature = $state('[]');
	let hasSavedBaseline = $state(false);

	const dimensions = $derived({
		width: loadedWidth || imageWidth || 0,
		height: loadedHeight || imageHeight || 0
	});

	const currentRecords = $derived.by(() => serializeAnnotations(annotations));
	const currentSignature = $derived.by(() => JSON.stringify(currentRecords));
	const isDirty = $derived(currentSignature !== savedSignature);

	const annotationStats = $derived.by(() => {
		return annotations.reduce(
			(stats, annotation) => {
				const source = getAnnotationSource(annotation);
				const shapeType = getShape(annotation)?.type;

				if (source === 'manual') stats.manual += 1;
				else stats.seeded += 1;

				if (shapeType === 'RECTANGLE') stats.rectangles += 1;
				if (shapeType === 'POLYGON' || shapeType === 'MULTIPOLYGON') stats.polygons += 1;

				return stats;
			},
			{
				total: annotations.length,
				manual: 0,
				seeded: 0,
				rectangles: 0,
				polygons: 0
			}
		);
	});

	$effect(() => {
		imageUrl;
		destroyAnnotator();
		loadedWidth = imageWidth ?? 0;
		loadedHeight = imageHeight ?? 0;
		annotations = [];
		selectedAnnotationIds = [];
		activeTool = 'rectangle';
		feedback = null;
		feedbackTone = 'neutral';
		saving = false;

		const normalizedSaved = normalizeSavedAnnotations(persistedAnnotations);
		savedRecords = normalizedSaved;
		savedSignature = JSON.stringify(normalizedSaved);
		hasSavedBaseline = hasPersistedAnnotations;
	});

	$effect(() => {
		if (!annotator) return;
		activeTool;
		annotator.setDrawingTool(activeTool);
	});

	// ── External API: sync state out ──
	$effect(() => {
		if (!externalApi) return;
		externalApi.isDirty = isDirty;
		externalApi.saving = saving;
		externalApi.totalAnnotations = annotationStats.total;
		externalApi.seededCount = annotationStats.seeded;
		externalApi.manualCount = annotationStats.manual;
		externalApi.rectangleCount = annotationStats.rectangles;
		externalApi.polygonCount = annotationStats.polygons;
		externalApi.selectedCount = selectedAnnotationIds.length;
		externalApi.feedback = feedback;
		externalApi.feedbackTone = feedbackTone;
		externalApi.hasSavedBaseline = hasSavedBaseline;
		externalApi.hasSeedBoxes = seedBoxes.length > 0;
	});

	// ── External API: sync activeTool in ──
	$effect(() => {
		if (!externalApi) return;
		activeTool = externalApi.activeTool;
	});

	// ── External API: register actions ──
	$effect(() => {
		if (!externalApi) return;
		externalApi.save = saveAnnotations;
		externalApi.deleteSelected = deleteSelected;
		externalApi.undo = () => annotator?.undo();
		externalApi.redo = () => annotator?.redo();
		externalApi.revert = restoreBaseline;
		externalApi.loadSorterBoxes = loadSorterBoxes;
		externalApi.clearAll = clearAll;
	});

	onMount(() => {
		window.addEventListener('keydown', handleWindowKeydown);

		if (imageEl?.complete && imageEl.naturalWidth > 0) {
			handleImageLoad();
		}

		return () => {
			window.removeEventListener('keydown', handleWindowKeydown);
			destroyAnnotator();
		};
	});

	function handleWindowKeydown(event: KeyboardEvent) {
		if (!isActive || !annotator) return;
		if (isTextInputTarget(event.target)) return;

		if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 's') {
			event.preventDefault();
			void saveAnnotations();
			return;
		}

		if ((event.key === 'Delete' || event.key === 'Backspace') && selectedAnnotationIds.length > 0) {
			event.preventDefault();
			deleteSelected();
		}
	}

	function isTextInputTarget(target: EventTarget | null) {
		if (!(target instanceof HTMLElement)) return false;
		return (
			target instanceof HTMLInputElement ||
			target instanceof HTMLTextAreaElement ||
			target.isContentEditable
		);
	}

	function cloneJson<T>(value: T): T {
		return JSON.parse(JSON.stringify(value)) as T;
	}

	function makeId(prefix: string) {
		if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) {
			return `${prefix}-${crypto.randomUUID()}`;
		}
		return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
	}

	function colorIndexForAnnotation(annotation: ImageAnnotation): number {
		const explicitIndex = annotation.properties?.colorIndex;
		if (typeof explicitIndex === 'number' && Number.isFinite(explicitIndex)) {
			return Math.abs(Math.trunc(explicitIndex)) % annotationPalette.length;
		}

		const id = annotation.id ?? '';
		let hash = 0;
		for (let i = 0; i < id.length; i += 1) {
			hash = (hash * 31 + id.charCodeAt(i)) >>> 0;
		}
		return hash % annotationPalette.length;
	}

	function buildBounds(x: number, y: number, w: number, h: number): Bounds {
		return {
			minX: x,
			minY: y,
			maxX: x + w,
			maxY: y + h
		};
	}

	function normalizeRectangleGeometry(geometry: Record<string, unknown> | null | undefined) {
		if (!geometry) return null;

		const x = geometry.x;
		const y = geometry.y;
		const w = geometry.w;
		const h = geometry.h;

		if (
			typeof x === 'number' &&
			typeof y === 'number' &&
			typeof w === 'number' &&
			typeof h === 'number'
		) {
			return {
				...geometry,
				bounds: buildBounds(x, y, w, h)
			};
		}

		return geometry;
	}

	function normalizeSavedAnnotations(input: SavedSampleAnnotation[]) {
		return input.flatMap((annotation) => {
			if (!annotation?.id || !annotation.shape_type) return [];
			if (
				annotation.source !== 'manual' &&
				annotation.source !== 'primary' &&
				annotation.source !== 'candidate'
			) {
				return [];
			}

			return [
				{
					id: annotation.id,
					source: annotation.source,
					shape_type: annotation.shape_type,
					geometry:
						annotation.shape_type === 'RECTANGLE'
							? normalizeRectangleGeometry(annotation.geometry)
							: annotation.geometry
								? cloneJson(annotation.geometry)
								: null,
					bodies: Array.isArray(annotation.bodies)
						? annotation.bodies.map((body) => ({
								id: body.id ?? null,
								purpose: body.purpose ?? null,
								value: body.value ?? null
							}))
						: []
				}
			];
		});
	}

	function buildSeedAnnotations(): ImageAnnotation[] {
		return seedBoxes.map((box, index) => ({
			id: makeId(`seed-${box.source}-${index + 1}`),
			bodies: [],
			properties: {
				source: box.source,
				colorIndex: index
			},
			target: {
				annotation: makeId(`target-seed-${box.source}-${index + 1}`),
				selector: {
					type: ShapeType.RECTANGLE,
					geometry: {
						x: box.x,
						y: box.y,
						w: box.w,
						h: box.h,
						bounds: buildBounds(box.x, box.y, box.w, box.h)
					}
				}
			}
		}));
	}

	function buildSavedAnnotation(record: SavedSampleAnnotation, index: number): ImageAnnotation {
		return {
			id: record.id,
			bodies: record.bodies.map((body, bodyIndex) => ({
				id: body.id ?? makeId(`body-${index + 1}-${bodyIndex + 1}`),
				annotation: record.id,
				purpose: body.purpose ?? undefined,
				value: body.value ?? undefined
			})) as AnnotationBody[],
			properties: {
				source: record.source,
				colorIndex: index
			},
			target: {
				annotation: makeId(`target-saved-${index + 1}`),
				selector: {
					type: record.shape_type as ShapeType,
					geometry:
						record.shape_type === 'RECTANGLE'
							? ((normalizeRectangleGeometry(record.geometry) ?? { bounds: buildBounds(0, 0, 0, 0) }) as unknown as ImageAnnotation['target']['selector']['geometry'])
							: (cloneJson(record.geometry ?? { bounds: buildBounds(0, 0, 0, 0) }) as unknown as ImageAnnotation['target']['selector']['geometry'])
				}
			}
		};
	}

	function buildPersistedAnnotations() {
		return savedRecords.map((record, index) => buildSavedAnnotation(record, index));
	}

	function getShape(annotation: ImageAnnotation): ShapeLike | null {
		const selector = annotation.target?.selector;
		if (!selector || typeof selector !== 'object') return null;
		return selector as unknown as ShapeLike;
	}

	function getBounds(annotation: ImageAnnotation): Bounds | null {
		const shape = getShape(annotation);
		if (!shape?.geometry) return null;

		const maybeBounds = shape.geometry.bounds as Record<string, unknown> | undefined;
		if (
			maybeBounds &&
			typeof maybeBounds.minX === 'number' &&
			typeof maybeBounds.minY === 'number' &&
			typeof maybeBounds.maxX === 'number' &&
			typeof maybeBounds.maxY === 'number'
		) {
			return maybeBounds as unknown as Bounds;
		}

		const x = shape.geometry.x;
		const y = shape.geometry.y;
		const w = shape.geometry.w;
		const h = shape.geometry.h;

		if (typeof x === 'number' && typeof y === 'number' && typeof w === 'number' && typeof h === 'number') {
			return buildBounds(x, y, w, h);
		}

		return null;
	}

	function getAnnotationSource(annotation: ImageAnnotation): 'primary' | 'candidate' | 'manual' {
		const source = annotation.properties?.source;
		if (source === 'primary' || source === 'candidate') return source;
		return 'manual';
	}

	function serializeAnnotations(currentAnnotations: ImageAnnotation[]): SavedSampleAnnotation[] {
		return currentAnnotations.flatMap((annotation, index) => {
			const shape = getShape(annotation);
			if (!shape?.type) return [];

			const geometry = shape.geometry ? cloneJson(shape.geometry) : null;
			const normalizedGeometry =
				shape.type === 'RECTANGLE' ? normalizeRectangleGeometry(geometry) : geometry;

			return [
				{
					id: annotation.id || `annotation-${index + 1}`,
					source: getAnnotationSource(annotation),
					shape_type: shape.type,
					geometry: normalizedGeometry,
					bodies:
						annotation.bodies?.map((body) => ({
							id: body.id ?? null,
							purpose: body.purpose ?? null,
							value: body.value ?? null
						})) ?? []
				}
			];
		});
	}

	function annotationStyle(annotation: ImageAnnotation): DrawingStyle {
		const palette = annotationPalette[colorIndexForAnnotation(annotation)];
		return {
			stroke: palette.stroke,
			strokeWidth: 2.5,
			fill: palette.fill,
			fillOpacity: getAnnotationSource(annotation) === 'manual' ? 0.08 : 0.06
		};
	}

	function destroyAnnotator() {
		detachHandlers?.();
		detachHandlers = null;
		annotator?.destroy();
		annotator = null;
	}

	function syncAnnotations() {
		if (!annotator) return;
		annotations = annotator.getAnnotations();
		selectedAnnotationIds = annotator
			.getSelected()
			.map((annotation) => annotation.id)
			.filter((id): id is string => Boolean(id));
	}

	function applyAnnotationSet(nextAnnotations: ImageAnnotation[]) {
		if (!annotator) return;
		annotator.setAnnotations(nextAnnotations, true);
		syncAnnotations();
	}

	function restoreBaseline() {
		if (!annotator) return;
		selectedAnnotationIds = [];
		applyAnnotationSet(hasSavedBaseline ? buildPersistedAnnotations() : buildSeedAnnotations());
		setFeedback(
			hasSavedBaseline ? 'Restored the last saved annotations.' : 'Restored the current Sorter boxes.',
			'neutral'
		);
	}

	function loadSorterBoxes() {
		if (!annotator) return;
		selectedAnnotationIds = [];
		applyAnnotationSet(buildSeedAnnotations());
		setFeedback('Loaded the current Sorter boxes into the editor.', 'neutral');
	}

	function clearAll() {
		if (!annotator) return;
		annotator.clearAnnotations();
		syncAnnotations();
		setFeedback('Cleared all annotations in the current editor view.', 'neutral');
	}

	function deleteSelected() {
		if (!annotator || selectedAnnotationIds.length === 0) return;

		const ids = [...selectedAnnotationIds];
		for (const id of ids) {
			annotator.removeAnnotation(id);
		}

		selectedAnnotationIds = [];
		syncAnnotations();
		setFeedback(`Deleted ${ids.length} selected annotation${ids.length === 1 ? '' : 's'}.`, 'neutral');
	}

	function setFeedback(message: string, tone: 'neutral' | 'success' | 'danger') {
		feedback = message;
		feedbackTone = tone;
	}

	function attachLifecycleHandlers(instance: AnnotoriousImageAnnotator<ImageAnnotation, ImageAnnotation>) {
		const sync = () => {
			syncAnnotations();
		};

		const handleSelectionChanged = (selected: ImageAnnotation[]) => {
			selectedAnnotationIds = selected
				.map((annotation) => annotation.id)
				.filter((id): id is string => Boolean(id));
		};

		instance.on('createAnnotation', sync);
		instance.on('updateAnnotation', sync);
		instance.on('deleteAnnotation', sync);
		instance.on('selectionChanged', handleSelectionChanged);

		detachHandlers = () => {
			instance.off('createAnnotation', sync);
			instance.off('updateAnnotation', sync);
			instance.off('deleteAnnotation', sync);
			instance.off('selectionChanged', handleSelectionChanged);
		};
	}

	function initializeAnnotator() {
		if (!imageEl || annotator) return;

		const currentUser = auth.user
			? {
					id: auth.user.id,
					name: auth.user.display_name ?? auth.user.email,
					avatar: auth.user.avatar_url ?? undefined
				}
			: {
					id: 'sorthive-local',
					name: 'SortHive'
				};

		const instance = createImageAnnotator(imageEl, {
			drawingMode: 'drag',
			style: annotationStyle
		});

		attachLifecycleHandlers(instance);
		instance.setDrawingTool(activeTool);
		instance.setUser(currentUser);

		annotator = instance;
		applyAnnotationSet(hasSavedBaseline ? buildPersistedAnnotations() : buildSeedAnnotations());
	}

	function handleImageLoad() {
		if (!imageEl) return;
		loadedWidth = imageEl.naturalWidth || imageWidth || 0;
		loadedHeight = imageEl.naturalHeight || imageHeight || 0;
		initializeAnnotator();
	}

	async function saveAnnotations() {
		if (saving) return false;

		saving = true;
		try {
			const response = await api.saveSampleAnnotations(sampleId, {
				annotations: currentRecords
			});

			savedRecords = normalizeSavedAnnotations(response.data.annotations);
			savedSignature = JSON.stringify(savedRecords);
			hasSavedBaseline = true;

			setFeedback(
				`Saved ${response.annotation_count} annotation${response.annotation_count === 1 ? '' : 's'}.`,
				'success'
			);
			return true;
		} catch {
			setFeedback('Saving annotations failed. Please try again.', 'danger');
			return false;
		} finally {
			saving = false;
		}
	}
</script>

{#if hasExternalControls}
	<!-- Canvas-only mode: external controls are rendered by the parent -->
	<!-- svelte-ignore a11y_no_static_element_interactions -->
	<div
		class="overflow-hidden rounded-lg border border-gray-200 bg-slate-950/95"
		onpointerup={() => { requestAnimationFrame(() => syncAnnotations()); }}
	>
		<div class="flex min-h-[50vh] items-center justify-center p-2">
			<img
				bind:this={imageEl}
				src={imageUrl}
				alt={imageAlt}
				class="block max-h-[80vh] max-w-full"
				onload={handleImageLoad}
			/>
		</div>
	</div>
{:else}
	<!-- Self-contained mode: toolbar + canvas -->
	<div class="space-y-4 rounded-xl border border-gray-200 bg-white p-4 shadow-sm">
		<div class="flex flex-wrap items-center gap-2">
			<div class="inline-flex rounded-lg border border-gray-200 bg-gray-50 p-1">
				<button type="button" onclick={() => { activeTool = 'rectangle'; }}
					class="rounded-md px-3 py-1.5 text-xs font-medium transition-colors {activeTool === 'rectangle' ? 'bg-gray-900 text-white' : 'text-gray-600 hover:bg-white'}"
				>Rectangle</button>
				<button type="button" onclick={() => { activeTool = 'polygon'; }}
					class="rounded-md px-3 py-1.5 text-xs font-medium transition-colors {activeTool === 'polygon' ? 'bg-gray-900 text-white' : 'text-gray-600 hover:bg-white'}"
				>Polygon</button>
			</div>
			<button type="button" onclick={() => { void saveAnnotations(); }} disabled={saving || !isDirty}
				class="rounded-lg px-3 py-1.5 text-xs font-medium text-white transition-colors disabled:cursor-not-allowed disabled:bg-blue-300 {saving || !isDirty ? 'bg-blue-300' : 'bg-blue-600 hover:bg-blue-700'}"
			>{saving ? 'Saving...' : 'Save'}</button>
			<button type="button" onclick={deleteSelected} disabled={selectedAnnotationIds.length === 0}
				class="rounded-lg border border-red-200 px-3 py-1.5 text-xs font-medium text-red-700 transition-colors disabled:cursor-not-allowed disabled:border-gray-200 disabled:text-gray-400 {selectedAnnotationIds.length === 0 ? '' : 'hover:bg-red-50'}"
			>Delete Selected</button>
			<button type="button" onclick={() => annotator?.undo()} class="rounded-lg border border-gray-200 px-3 py-1.5 text-xs font-medium text-gray-700 hover:bg-gray-50">Undo</button>
			<button type="button" onclick={() => annotator?.redo()} class="rounded-lg border border-gray-200 px-3 py-1.5 text-xs font-medium text-gray-700 hover:bg-gray-50">Redo</button>
			<button type="button" onclick={restoreBaseline} class="rounded-lg border border-gray-200 px-3 py-1.5 text-xs font-medium text-gray-700 hover:bg-gray-50">Revert</button>
			{#if seedBoxes.length > 0}
				<button type="button" onclick={loadSorterBoxes} class="rounded-lg border border-gray-200 px-3 py-1.5 text-xs font-medium text-gray-700 hover:bg-gray-50">Load Sorter Boxes</button>
			{/if}
			<button type="button" onclick={clearAll} class="rounded-lg border border-orange-200 px-3 py-1.5 text-xs font-medium text-orange-700 hover:bg-orange-50">Clear</button>
		</div>

		<div class="flex flex-wrap items-center gap-x-4 gap-y-2 rounded-lg border border-gray-200 bg-gray-50 px-3 py-2 text-xs text-gray-600">
			<span>{annotationStats.total} annotations</span>
			<span>{annotationStats.seeded} seeded</span>
			<span>{annotationStats.manual} manual</span>
			<span>{annotationStats.rectangles} rectangles</span>
			<span>{annotationStats.polygons} polygons</span>
			<span>{selectedAnnotationIds.length} selected</span>
			<span class="ml-auto font-medium {isDirty ? 'text-amber-700' : 'text-emerald-700'}">
				{#if isDirty}Unsaved changes{:else if hasSavedBaseline}Saved{:else}Not saved yet{/if}
			</span>
		</div>

		<div class="rounded-lg border border-blue-100 bg-blue-50 px-3 py-2 text-xs text-blue-900">
			Click a box to edit it. Press `Delete` or `Backspace` to remove the selected box, or use `Ctrl/Cmd + S` to save.
		</div>

		{#if feedback}
			<p class="rounded-lg px-3 py-2 text-xs {feedbackTone === 'danger' ? 'bg-red-50 text-red-700' : feedbackTone === 'success' ? 'bg-emerald-50 text-emerald-700' : 'bg-gray-50 text-gray-700'}">
				{feedback}
			</p>
		{/if}

		<!-- svelte-ignore a11y_no_static_element_interactions -->
		<div
			class="overflow-auto rounded-xl border border-gray-200 bg-slate-950/95 p-4"
			onpointerup={() => { requestAnimationFrame(() => syncAnnotations()); }}
		>
			<div class="flex min-h-[28rem] items-center justify-center">
				<img
					bind:this={imageEl}
					src={imageUrl}
					alt={imageAlt}
					class="block max-h-[72vh] max-w-full"
					onload={handleImageLoad}
				/>
			</div>
		</div>
	</div>
{/if}
