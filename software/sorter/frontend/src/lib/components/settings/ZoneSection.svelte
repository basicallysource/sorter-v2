<script lang="ts">
	import { mjpegStream as resilientMjpegStream } from '$lib/actions/mjpegStream';
	import { backendHttpBaseUrl } from '$lib/backend';
	import Modal from '$lib/components/Modal.svelte';
	import ClassificationBaselineSection from '$lib/components/settings/ClassificationBaselineSection.svelte';
	import PictureSettingsSidebar from '$lib/components/settings/PictureSettingsSidebar.svelte';
	import StepperSidebar from '$lib/components/settings/StepperSidebar.svelte';
	import ZoneEditingSidebar from '$lib/components/settings/ZoneEditingSidebar.svelte';
	import {
		clonePictureSettings,
		pictureSettingsEqual,
		type PictureSettings
	} from '$lib/settings/picture-settings';
	import type { CameraRole, StepperKey, EndstopConfig } from '$lib/settings/stations';
	import {
		Bug,
		Camera,
		Check,
		Pencil,
		RefreshCw,
		RotateCcw,
		SlidersHorizontal,
		X
	} from 'lucide-svelte';
	import StreamControlsOverlay from '$lib/components/StreamControlsOverlay.svelte';
	import { createEventDispatcher, onMount } from 'svelte';

	type Channel = 'second' | 'third' | 'carousel' | 'class_top' | 'class_bottom';
	type ArcChannel = 'second' | 'third';
	type RectChannel = 'carousel' | 'class_top' | 'class_bottom';
	type Point = [number, number];
	type QuadParams = {
		corners: [Point, Point, Point, Point]; // TL, TR, BR, BL
	};
	type QuadHandle = 0 | 1 | 2 | 3; // corner index
	type UsbCameraInfo = {
		kind: 'usb';
		index: number;
		width: number;
		height: number;
		name?: string;
		preview_available?: boolean;
	};
	type NetworkCameraInfo = {
		kind: 'network';
		id: string;
		name: string;
		source: string;
		preview_url: string;
		health_url: string;
		host: string;
		port: number;
		model?: string | null;
		lens_facing?: string | null;
		transport: string;
		last_seen_ms: number;
	};
	type CameraSource = number | string | null;
	type ArcParams = {
		center: Point;
		innerRadius: number;
		outerRadius: number;
		dropZone: AngularZone;
		exitZone: AngularZone;
	};
	type AngularZone = {
		startAngle: number;
		endAngle: number;
	};
	type ArcHandle = 'center' | 'inner' | 'outer' | 'dropStart' | 'dropEnd' | 'exitStart' | 'exitEnd';
	type ArcParamsPayload = {
		center: number[];
		inner_radius: number;
		outer_radius: number;
		drop_zone?: AngularZonePayload;
		exit_zone?: AngularZonePayload;
	};
	type AngularZonePayload = {
		start_angle: number;
		end_angle: number;
	};
	type Snapshot = {
		userPoints: Record<Channel, number[][]>;
		arcParams: Record<ArcChannel, ArcParams | null>;
		sectionZeroPoints: Record<ArcChannel, Point | null>;
		quadParams: Record<RectChannel, QuadParams | null>;
	};
	type PreviewImageSize = {
		width: number;
		height: number;
	};
	type PicturePreviewState = {
		saved: PictureSettings;
		draft: PictureSettings;
	};
	type CalibrationHighlight = [number, number, number, number];
	type DetectionHighlight = [number, number, number, number];
	type SidePanel = 'picture' | 'zone' | 'classification' | null;
	type DragState =
		| {
				kind: 'polygon-shape';
				channel: Channel;
				start: Point;
				origPts: number[][];
				origSec0: Point | null;
		 }
		| {
				kind: 'arc-shape' | 'arc-center';
				channel: ArcChannel;
				start: Point;
				orig: ArcParams;
				origSec0: Point | null;
		 }
		| {
				kind:
					| 'arc-inner'
					| 'arc-outer'
					| 'arc-drop-start'
					| 'arc-drop-end'
					| 'arc-exit-start'
					| 'arc-exit-end';
				channel: ArcChannel;
				orig: ArcParams;
		 }
		| {
				kind: 'section-zero';
				channel: ArcChannel;
		 }
		| {
				kind: 'quad-shape';
				channel: RectChannel;
				start: Point;
				origCorners: [Point, Point, Point, Point];
		 }
		| {
				kind: 'quad-corner';
				channel: RectChannel;
				cornerIdx: QuadHandle;
		 };

	const ARC_CHANNELS: ArcChannel[] = ['second', 'third'];
	const RECT_CHANNELS: RectChannel[] = ['carousel', 'class_top', 'class_bottom'];
	const FEEDER_CHANNELS: Channel[] = ['second', 'third', 'carousel'];
	const CLASSIFICATION_CHANNELS: Channel[] = ['class_top', 'class_bottom'];
	const DETECTION_CHANNELS: Channel[] = [
		'second',
		'third',
		'carousel',
		'class_top',
		'class_bottom'
	];
	const ALL_CHANNELS: Channel[] = [...FEEDER_CHANNELS, ...CLASSIFICATION_CHANNELS];
	const HANDLE_HIT_RADIUS = 22;
	const HANDLE_DRAW_RADIUS = 9;
	const VERTEX_HIT_RADIUS = 18;
	const LABEL_EDGE_PADDING = 12;
	const ARC_SEGMENTS = 64;
	const MIN_ZONE_SPAN_DEG = 12;
	const MIN_ARC_THICKNESS = 20;
	const CHANNEL_SECTION_COUNT = 360;
	const CHANNEL_SECTION_DEG = 360 / CHANNEL_SECTION_COUNT;
	const ALL_CAMERA_ROLES: CameraRole[] = [
		'c_channel_2',
		'c_channel_3',
		'carousel',
		'classification_top',
		'classification_bottom'
	];

	const CHANNEL_LABELS: Record<Channel, string> = {
		second: 'C-Channel 2',
		third: 'C-Channel 3',
		carousel: 'Carousel',
		class_top: 'Class. Top',
		class_bottom: 'Class. Bottom'
	};

	const CHANNEL_COLORS: Record<Channel, string> = {
		second: '#ffc800',
		third: '#00c8ff',
		carousel: '#00ff80',
		class_top: '#ff6090',
		class_bottom: '#b060ff'
	};

	const CAMERA_FOR_CHANNEL: Record<Channel, CameraRole> = {
		second: 'c_channel_2',
		third: 'c_channel_3',
		carousel: 'carousel',
		class_top: 'classification_top',
		class_bottom: 'classification_bottom'
	};

	const ROLE_LABELS: Record<CameraRole, string> = {
		c_channel_2: 'C Channel 2',
		c_channel_3: 'C Channel 3',
		carousel: 'Carousel',
		classification_top: 'Classification Top',
		classification_bottom: 'Classification Bottom'
	};

	const ROLE_SUPPORTS_URL: Record<CameraRole, boolean> = {
		c_channel_2: false,
		c_channel_3: false,
		carousel: true,
		classification_top: true,
		classification_bottom: true
	};

	const LEGACY_ZONE_SECTION_RANGES: Record<
		ArcChannel,
		{ drop: [number, number]; exit: [number, number] }
	> = {
		second: {
			drop: [101, 180],
			exit: [304, 338]
		},
		third: {
			drop: [45, 119],
			exit: [315, 360]
		}
	};

	const DROP_ZONE_COLOR = '#22c55e';
	const EXIT_ZONE_COLOR = '#ef4444';

	let {
		channels = ALL_CHANNELS,
		stepperKey = undefined,
		stepperEndstop = undefined,
		wizardMode = false
	}: {
		channels?: Channel[];
		stepperKey?: StepperKey;
		stepperEndstop?: EndstopConfig;
		wizardMode?: boolean;
	} = $props();

	const dispatch = createEventDispatcher<{ saved: void }>();

	const hasStepper = $derived(!!stepperKey);

	let currentChannel = $state<Channel>('second');
	let userPoints = $state<Record<Channel, number[][]>>({
		second: [],
		third: [],
		carousel: [],
		class_top: [],
		class_bottom: []
	});
	let arcParams = $state<Record<ArcChannel, ArcParams | null>>({
		second: null,
		third: null
	});
	let sectionZeroPoints = $state<Record<ArcChannel, Point | null>>({
		second: null,
		third: null
	});
	let quadParams = $state<Record<RectChannel, QuadParams | null>>({
		carousel: null,
		class_top: null,
		class_bottom: null
	});
	let saving = $state(false);
	let statusMsg = $state('');
	let dragState = $state<DragState | null>(null);
	let didDrag = $state(false);
	let editingZone = $state(false);
	let activeSidebar = $state<SidePanel>(null);
	let previewColorCorrect = $state(true);
	let previewAnnotated = $state(true);
	let previewCropped = $state(false);
	let previewZones = $state(true);
	let cameraModalOpen = $state(false);
	let cameraLoading = $state(false);
	let cameraAbort = $state<AbortController | null>(null);
	let cameraSaving = $state(false);
	let cameraError = $state<string | null>(null);
	let cameraConfigLoaded = $state(false);
	let usbCameras = $state<UsbCameraInfo[]>([]);
	let networkCameras = $state<NetworkCameraInfo[]>([]);
	let assignments = $state<Record<CameraRole, CameraSource>>({
		c_channel_2: null,
		c_channel_3: null,
		carousel: null,
		classification_top: null,
		classification_bottom: null
	});
	let picturePreviewByRole = $state<Partial<Record<CameraRole, PicturePreviewState>>>({});
	let previewImageSizeByRole = $state<Partial<Record<CameraRole, PreviewImageSize>>>({});
	let calibrationHighlightByRole = $state<Partial<Record<CameraRole, CalibrationHighlight>>>({});
	let detectionHighlightByRole = $state<Partial<Record<CameraRole, DetectionHighlight[]>>>({});
	let feedRevision = $state(0);
	let reassignConfirm = $state<{
		source: CameraSource;
		targetRole: CameraRole;
		currentRole: CameraRole;
		cameraLabel: string;
	} | null>(null);
	let reassignModalOpen = $state(false);
	$effect(() => {
		if (!reassignModalOpen) reassignConfirm = null;
	});
	const showSidebarColumn = $derived(!wizardMode && Boolean(activeSidebar || hasStepper));
	let canvasCursor = $state<'default' | 'crosshair' | 'pointer' | 'grab' | 'grabbing'>('default');
	let canvasEl: HTMLCanvasElement;
	let previewViewportEl: HTMLDivElement | null = null;
	let previewViewportSize = $state<PreviewImageSize>({ width: 0, height: 0 });
	let persistedSnapshot: Snapshot = createSnapshot();
	let channelSetKey = $state('');

	const CANVAS_W = 1920;
	const CANVAS_H = 1080;

	$effect(() => {
		const nextKey = channels.join('|');
		if (nextKey !== channelSetKey) {
			if (activeSidebar === 'picture') {
				clearPicturePreview(currentRole());
			}
			channelSetKey = nextKey;
			currentChannel = channels[0] ?? 'second';
			editingZone = wizardMode;
			activeSidebar = wizardMode ? 'zone' : null;
			dragState = null;
			didDrag = false;
			canvasCursor = wizardMode ? 'crosshair' : 'default';
			statusMsg = '';
			return;
		}

		if (!channels.includes(currentChannel)) {
			currentChannel = channels[0] ?? 'second';
		}
	});

	$effect(() => {
		if (!wizardMode) return;
		if (currentAssignment() === null) {
			editingZone = false;
			activeSidebar = null;
			canvasCursor = 'default';
			return;
		}

		editingZone = true;
		activeSidebar = 'zone';
		canvasCursor = 'crosshair';
	});

	$effect(() => {
		for (const ch of ARC_CHANNELS) {
			if (channels.includes(ch) && arcParams[ch] === null) {
				arcParams[ch] = defaultArcParams(ch);
			}
		}
	});

	$effect(() => {
		for (const ch of RECT_CHANNELS) {
			if (channels.includes(ch) && quadParams[ch] === null) {
				quadParams[ch] = defaultQuadParams(ch);
			}
		}
	});

	function isArcChannel(ch: Channel): ch is ArcChannel {
		return ARC_CHANNELS.includes(ch as ArcChannel);
	}

	function isRectChannel(ch: Channel): ch is RectChannel {
		return RECT_CHANNELS.includes(ch as RectChannel);
	}

	function isClassificationChannel(ch: Channel): ch is (typeof CLASSIFICATION_CHANNELS)[number] {
		return CLASSIFICATION_CHANNELS.includes(ch as (typeof CLASSIFICATION_CHANNELS)[number]);
	}

	function supportsDetectionSidebar(ch: Channel): ch is (typeof DETECTION_CHANNELS)[number] {
		return DETECTION_CHANNELS.includes(ch as (typeof DETECTION_CHANNELS)[number]);
	}

	function detectionScopeForChannel(channel: Channel): 'classification' | 'feeder' | 'carousel' {
		if (channel === 'second' || channel === 'third') return 'feeder';
		if (channel === 'carousel') return 'carousel';
		return 'classification';
	}

	function detectionCameraForChannel(
		channel: Channel
	): 'top' | 'bottom' | 'c_channel_2' | 'c_channel_3' | 'carousel' {
		if (channel === 'second') return 'c_channel_2';
		if (channel === 'third') return 'c_channel_3';
		if (channel === 'carousel') return 'carousel';
		return channel === 'class_top' ? 'top' : 'bottom';
	}

	function normalizeAngle(angle: number): number {
		return ((angle % 360) + 360) % 360;
	}

	function positiveAngleSpan(start: number, end: number): number {
		const span = (normalizeAngle(end) - normalizeAngle(start) + 360) % 360;
		return span === 0 ? 360 : span;
	}

	function angularDistance(a: number, b: number): number {
		const delta = Math.abs(normalizeAngle(a) - normalizeAngle(b));
		return Math.min(delta, 360 - delta);
	}

	function clampZone(zone: AngularZone): AngularZone {
		const next = {
			startAngle: normalizeAngle(zone.startAngle),
			endAngle: normalizeAngle(zone.endAngle)
		};
		let span = positiveAngleSpan(next.startAngle, next.endAngle);
		if (span < MIN_ZONE_SPAN_DEG) {
			next.endAngle = normalizeAngle(next.startAngle + MIN_ZONE_SPAN_DEG);
			span = MIN_ZONE_SPAN_DEG;
		}
		if (span > 360 - MIN_ZONE_SPAN_DEG) {
			next.endAngle = normalizeAngle(next.startAngle + (360 - MIN_ZONE_SPAN_DEG));
		}
		return next;
	}

	function copyArcParams(params: ArcParams): ArcParams {
		return {
			center: [params.center[0], params.center[1]],
			innerRadius: params.innerRadius,
			outerRadius: params.outerRadius,
			dropZone: {
				startAngle: params.dropZone.startAngle,
				endAngle: params.dropZone.endAngle
			},
			exitZone: {
				startAngle: params.exitZone.startAngle,
				endAngle: params.exitZone.endAngle
			}
		};
	}

	function sectionRangeToZone(
		channel: ArcChannel,
		zoneKey: 'drop' | 'exit',
		sectionZeroAngle = 0
	): AngularZone {
		const [startSection, endSection] = LEGACY_ZONE_SECTION_RANGES[channel][zoneKey];
		return clampZone({
			startAngle: normalizeAngle(sectionZeroAngle + startSection * CHANNEL_SECTION_DEG),
			endAngle: normalizeAngle(sectionZeroAngle + endSection * CHANNEL_SECTION_DEG)
		});
	}

	function pointDistance(a: Point, b: Point): number {
		return Math.hypot(a[0] - b[0], a[1] - b[1]);
	}

	function clamp(value: number, min: number, max: number): number {
		return Math.min(Math.max(value, min), max);
	}

	function clonePointList(points: number[][]): number[][] {
		return points.map((pt) => [pt[0], pt[1]]);
	}

	function clonePoint(point: Point | null): Point | null {
		return point ? [point[0], point[1]] : null;
	}

	function createSnapshot(): Snapshot {
		return {
			userPoints: {
				second: [],
				third: [],
				carousel: [],
				class_top: [],
				class_bottom: []
			},
			arcParams: {
				second: null,
				third: null
			},
			sectionZeroPoints: {
				second: null,
				third: null
			},
			quadParams: {
				carousel: null,
				class_top: null,
				class_bottom: null
			}
		};
	}

	function snapshotCurrentState(): Snapshot {
		return {
			userPoints: {
				second: clonePointList(userPoints.second),
				third: clonePointList(userPoints.third),
				carousel: clonePointList(userPoints.carousel),
				class_top: clonePointList(userPoints.class_top),
				class_bottom: clonePointList(userPoints.class_bottom)
			},
			arcParams: {
				second: arcParams.second ? copyArcParams(arcParams.second) : null,
				third: arcParams.third ? copyArcParams(arcParams.third) : null
			},
			sectionZeroPoints: {
				second: clonePoint(sectionZeroPoints.second),
				third: clonePoint(sectionZeroPoints.third)
			},
			quadParams: {
				carousel: quadParams.carousel ? copyQuadParams(quadParams.carousel) : null,
				class_top: quadParams.class_top ? copyQuadParams(quadParams.class_top) : null,
				class_bottom: quadParams.class_bottom ? copyQuadParams(quadParams.class_bottom) : null
			}
		};
	}

	function restoreSnapshot(snapshot: Snapshot) {
		userPoints = {
			second: clonePointList(snapshot.userPoints.second),
			third: clonePointList(snapshot.userPoints.third),
			carousel: clonePointList(snapshot.userPoints.carousel),
			class_top: clonePointList(snapshot.userPoints.class_top),
			class_bottom: clonePointList(snapshot.userPoints.class_bottom)
		};
		arcParams = {
			second: snapshot.arcParams.second ? copyArcParams(snapshot.arcParams.second) : null,
			third: snapshot.arcParams.third ? copyArcParams(snapshot.arcParams.third) : null
		};
		sectionZeroPoints = {
			second: clonePoint(snapshot.sectionZeroPoints.second),
			third: clonePoint(snapshot.sectionZeroPoints.third)
		};
		quadParams = {
			carousel: snapshot.quadParams.carousel ? copyQuadParams(snapshot.quadParams.carousel) : null,
			class_top: snapshot.quadParams.class_top ? copyQuadParams(snapshot.quadParams.class_top) : null,
			class_bottom: snapshot.quadParams.class_bottom ? copyQuadParams(snapshot.quadParams.class_bottom) : null
		};
	}

	function currentRole(channel: Channel = currentChannel): CameraRole {
		return CAMERA_FOR_CHANNEL[channel];
	}

	function currentAssignment(channel: Channel = currentChannel): CameraSource {
		return assignments[currentRole(channel)] ?? null;
	}

	function setPicturePreview(
		role: CameraRole,
		savedSettings: PictureSettings,
		draftSettings: PictureSettings
	) {
		picturePreviewByRole = {
			...picturePreviewByRole,
			[role]: {
				saved: clonePictureSettings(savedSettings),
				draft: clonePictureSettings(draftSettings)
			}
		};
	}

	function clearPicturePreview(role: CameraRole) {
		if (!(role in picturePreviewByRole)) return;
		const nextPreview = { ...picturePreviewByRole };
		delete nextPreview[role];
		picturePreviewByRole = nextPreview;
	}

	function getPicturePreview(role: CameraRole = currentRole()): PicturePreviewState | null {
		return picturePreviewByRole[role] ?? null;
	}

	function setCalibrationHighlight(role: CameraRole, bbox: CalibrationHighlight | null) {
		const next = { ...calibrationHighlightByRole };
		if (bbox) {
			next[role] = bbox;
		} else {
			delete next[role];
		}
		calibrationHighlightByRole = next;
	}

	function getCalibrationHighlight(role: CameraRole = currentRole()): CalibrationHighlight | null {
		return calibrationHighlightByRole[role] ?? null;
	}

	function setDetectionHighlights(role: CameraRole, bboxes: DetectionHighlight[] | null) {
		const next = { ...detectionHighlightByRole };
		if (bboxes && bboxes.length > 0) {
			next[role] = bboxes;
		} else {
			delete next[role];
		}
		detectionHighlightByRole = next;
	}

	function getDetectionHighlights(role: CameraRole = currentRole()): DetectionHighlight[] {
		return detectionHighlightByRole[role] ?? [];
	}

	function rememberPreviewImageSize(role: CameraRole, target: EventTarget | null) {
		if (!(target instanceof HTMLImageElement)) return;
		const width = target.naturalWidth;
		const height = target.naturalHeight;
		if (width <= 0 || height <= 0) return;
		const current = previewImageSizeByRole[role];
		if (current?.width === width && current.height === height) return;
		previewImageSizeByRole = {
			...previewImageSizeByRole,
			[role]: { width, height }
		};
	}

	function updatePreviewViewportSize() {
		if (!previewViewportEl) return;
		const rect = previewViewportEl.getBoundingClientRect();
		const width = Math.round(rect.width);
		const height = Math.round(rect.height);
		if (width === previewViewportSize.width && height === previewViewportSize.height) return;
		previewViewportSize = { width, height };
	}

	function containedImageRect(
		container: PreviewImageSize,
		source: PreviewImageSize
	): { left: number; top: number; width: number; height: number } {
		if (container.width <= 0 || container.height <= 0 || source.width <= 0 || source.height <= 0) {
			return {
				left: 0,
				top: 0,
				width: container.width,
				height: container.height
			};
		}

		const scale = Math.min(container.width / source.width, container.height / source.height);
		const width = source.width * scale;
		const height = source.height * scale;
		return {
			left: (container.width - width) / 2,
			top: (container.height - height) / 2,
			width,
			height
		};
	}

	function hasDraftPicturePreview(role: CameraRole = currentRole()): boolean {
		const preview = getPicturePreview(role);
		return preview !== null && !pictureSettingsEqual(preview.saved, preview.draft);
	}

	type TransformMatrix = [number, number, number, number];

	function multiplyTransformMatrices(
		left: TransformMatrix,
		right: TransformMatrix
	): TransformMatrix {
		return [
			left[0] * right[0] + left[1] * right[2],
			left[0] * right[1] + left[1] * right[3],
			left[2] * right[0] + left[3] * right[2],
			left[2] * right[1] + left[3] * right[3]
		];
	}

	function inverseTransformMatrix(matrix: TransformMatrix): TransformMatrix {
		return [matrix[0], matrix[2], matrix[1], matrix[3]];
	}

	function pictureTransformMatrix(settings: PictureSettings): TransformMatrix {
		let matrix: TransformMatrix = [1, 0, 0, 1];

		const rotationMatrix: Record<number, TransformMatrix> = {
			0: [1, 0, 0, 1],
			90: [0, -1, 1, 0],
			180: [-1, 0, 0, -1],
			270: [0, 1, -1, 0]
		};

		matrix = multiplyTransformMatrices(
			rotationMatrix[settings.rotation] ?? rotationMatrix[0],
			matrix
		);
		if (settings.flip_horizontal) {
			matrix = multiplyTransformMatrices([-1, 0, 0, 1], matrix);
		}
		if (settings.flip_vertical) {
			matrix = multiplyTransformMatrices([1, 0, 0, -1], matrix);
		}
		return matrix;
	}

	function picturePreviewTransform(channel: Channel): string {
		const preview = getPicturePreview(currentRole(channel));
		if (!preview || !hasDraftPicturePreview(currentRole(channel))) return '';

		const relativeMatrix = multiplyTransformMatrices(
			pictureTransformMatrix(preview.draft),
			inverseTransformMatrix(pictureTransformMatrix(preview.saved))
		);

		const isIdentity =
			relativeMatrix[0] === 1 &&
			relativeMatrix[1] === 0 &&
			relativeMatrix[2] === 0 &&
			relativeMatrix[3] === 1;

		if (isIdentity) return '';
		return `transform: matrix(${relativeMatrix[0]}, ${relativeMatrix[2]}, ${relativeMatrix[1]}, ${relativeMatrix[3]}, 0, 0); transform-origin: center center;`;
	}

	function feedImageStyle(channel: Channel): string {
		const transformStyle = picturePreviewTransform(channel);
		return transformStyle;
	}

	function previewOverlayStyle(channel: Channel): string {
		const imageSize = previewImageSizeByRole[currentRole(channel)];
		const transformStyle = picturePreviewTransform(channel);
		if (!imageSize) {
			return `inset:0;${transformStyle}`;
		}
		const fitted = containedImageRect(previewViewportSize, imageSize);
		return `left:${fitted.left}px;top:${fitted.top}px;width:${fitted.width}px;height:${fitted.height}px;${transformStyle}`;
	}

	function togglePictureSidebar() {
		if (activeSidebar === 'classification') {
			setDetectionHighlights(currentRole(), null);
		}
		if (activeSidebar === 'picture') {
			clearPicturePreview(currentRole());
			activeSidebar = null;
			return;
		}
		activeSidebar = 'picture';
	}

	function toggleClassificationSidebar() {
		if (!supportsDetectionSidebar(currentChannel)) return;
		if (activeSidebar === 'picture') {
			clearPicturePreview(currentRole());
			setCalibrationHighlight(currentRole(), null);
		}
		if (activeSidebar === 'classification') {
			setDetectionHighlights(currentRole(), null);
			activeSidebar = null;
			return;
		}
		activeSidebar = 'classification';
	}

	function selectChannel(channel: Channel) {
		if (activeSidebar === 'picture') {
			clearPicturePreview(currentRole());
		}
		if (activeSidebar === 'classification' && !supportsDetectionSidebar(channel)) {
			activeSidebar = null;
		}
		currentChannel = channel;
		dragState = null;
		didDrag = false;
		canvasCursor = editingZone ? 'crosshair' : 'default';
		statusMsg = '';
	}

	function formatSource(source: CameraSource): string {
		if (!cameraConfigLoaded) return 'Loading camera source...';
		if (source === null) return 'No camera selected';
		if (typeof source === 'number') {
			const camera = usbCameras.find((candidate) => candidate.index === source) ?? null;
			if (camera?.name) return `${camera.name} (Camera ${source})`;
			return `Camera ${source}`;
		}
		const discovered = discoveredCameraBySource(source);
		if (discovered) return discovered.name;
		return source;
	}

	function cameraIndexPreviewUrl(index: number): string {
		return `${backendHttpBaseUrl}/api/cameras/stream/${index}`;
	}

	function discoveredCameraBySource(source: CameraSource): NetworkCameraInfo | null {
		if (typeof source !== 'string') return null;
		return networkCameras.find((camera) => camera.source === source) ?? null;
	}

	function discoveredPreviewUrl(camera: NetworkCameraInfo): string {
		return `${camera.preview_url}?t=${camera.last_seen_ms}`;
	}

	function angleFromCenter(point: Point, center: Point): number {
		return (Math.atan2(point[1] - center[1], point[0] - center[0]) * 180) / Math.PI;
	}

	function polarPoint(center: Point, radius: number, angleDeg: number): Point {
		const angleRad = (angleDeg * Math.PI) / 180;
		return [center[0] + radius * Math.cos(angleRad), center[1] + radius * Math.sin(angleRad)];
	}

	function defaultZoneLayout(
		channel: ArcChannel,
		sectionZeroAngle = 0
	): Pick<ArcParams, 'dropZone' | 'exitZone'> {
		return {
			dropZone: sectionRangeToZone(channel, 'drop', sectionZeroAngle),
			exitZone: sectionRangeToZone(channel, 'exit', sectionZeroAngle)
		};
	}

	function defaultArcParams(channel: ArcChannel): ArcParams {
		const center: Point =
			channel === 'second'
				? [CANVAS_W * 0.46, CANVAS_H * 0.55]
				: [CANVAS_W * 0.54, CANVAS_H * 0.55];
		return {
			center,
			innerRadius: 180,
			outerRadius: 360,
			...defaultZoneLayout(channel)
		};
	}

	function serializeArcParams(params: ArcParams): ArcParamsPayload {
		return {
			center: [Math.round(params.center[0]), Math.round(params.center[1])],
			inner_radius: Math.round(params.innerRadius),
			outer_radius: Math.round(params.outerRadius),
			drop_zone: {
				start_angle: params.dropZone.startAngle,
				end_angle: params.dropZone.endAngle
			},
			exit_zone: {
				start_angle: params.exitZone.startAngle,
				end_angle: params.exitZone.endAngle
			}
		};
	}

	function parseAngularZone(raw: unknown): AngularZone | null {
		if (!raw || typeof raw !== 'object') return null;
		const startAngle = (raw as AngularZonePayload).start_angle;
		const endAngle = (raw as AngularZonePayload).end_angle;
		if (typeof startAngle !== 'number' || typeof endAngle !== 'number') return null;
		return clampZone({
			startAngle,
			endAngle
		});
	}

	function parseArcParams(
		raw: unknown,
		channel: ArcChannel,
		sectionZeroAngle = 0
	): ArcParams | null {
		if (!raw || typeof raw !== 'object') return null;
		const center = (raw as ArcParamsPayload).center;
		const innerRadius = (raw as ArcParamsPayload).inner_radius;
		const outerRadius = (raw as ArcParamsPayload).outer_radius;
		if (
			!Array.isArray(center) ||
			center.length !== 2 ||
			typeof center[0] !== 'number' ||
			typeof center[1] !== 'number' ||
			typeof innerRadius !== 'number' ||
			typeof outerRadius !== 'number'
		) {
			return null;
		}
		const dropZone =
			parseAngularZone((raw as ArcParamsPayload).drop_zone) ??
			sectionRangeToZone(channel, 'drop', sectionZeroAngle);
		const exitZone =
			parseAngularZone((raw as ArcParamsPayload).exit_zone) ??
			sectionRangeToZone(channel, 'exit', sectionZeroAngle);
		return {
			center: [center[0], center[1]],
			innerRadius: Math.max(10, innerRadius),
			outerRadius: Math.max(innerRadius + MIN_ARC_THICKNESS, outerRadius),
			dropZone,
			exitZone
		};
	}

	function deriveArcParamsFromPolygon(
		points: number[][],
		channel: ArcChannel,
		sectionZeroAngle = 0
	): ArcParams | null {
		if (points.length < 3) return null;
		const center = polyCenter(points);
		if (!center) return null;

		const distances = points.map((pt) => pointDistance([pt[0], pt[1]], [center[0], center[1]]));
		const innerRadius = Math.max(10, Math.min(...distances));
		const outerRadius = Math.max(innerRadius + MIN_ARC_THICKNESS, Math.max(...distances));
		return {
			center: [center[0], center[1]],
			innerRadius,
			outerRadius,
			...defaultZoneLayout(channel, sectionZeroAngle)
		};
	}

	function zoneMidAngle(zone: AngularZone): number {
		return normalizeAngle(zone.startAngle + positiveAngleSpan(zone.startAngle, zone.endAngle) / 2);
	}

	function buildZonePolygon(params: ArcParams, zone: AngularZone): Point[] {
		const span = positiveAngleSpan(zone.startAngle, zone.endAngle);
		const segments = Math.max(8, Math.round((span / 360) * ARC_SEGMENTS));
		const pts: Point[] = [];

		for (let i = 0; i <= segments; i++) {
			const angle = zone.startAngle + (span * i) / segments;
			pts.push(polarPoint(params.center, params.outerRadius, angle));
		}
		for (let i = segments; i >= 0; i--) {
			const angle = zone.startAngle + (span * i) / segments;
			pts.push(polarPoint(params.center, params.innerRadius, angle));
		}

		return pts;
	}

	function buildCirclePoints(center: Point, radius: number, segments = ARC_SEGMENTS): Point[] {
		const pts: Point[] = [];
		for (let i = 0; i < segments; i++) {
			const angle = (i / segments) * 360;
			pts.push(polarPoint(center, radius, angle));
		}
		return pts;
	}

	function buildRingStoragePoints(params: ArcParams): Point[] {
		return [
			...buildCirclePoints(params.center, params.outerRadius),
			...buildCirclePoints(params.center, params.innerRadius).reverse()
		];
	}

	// ---- Quad helpers ----

	function quadCenter(q: QuadParams): Point {
		const cx = (q.corners[0][0] + q.corners[1][0] + q.corners[2][0] + q.corners[3][0]) / 4;
		const cy = (q.corners[0][1] + q.corners[1][1] + q.corners[2][1] + q.corners[3][1]) / 4;
		return [cx, cy];
	}

	function copyQuadParams(q: QuadParams): QuadParams {
		return { corners: q.corners.map((c) => [c[0], c[1]] as Point) as [Point, Point, Point, Point] };
	}

	function defaultQuadParams(_channel: RectChannel): QuadParams {
		const cx = CANVAS_W / 2;
		const cy = CANVAS_H / 2;
		const hw = 200;
		const hh = 150;
		return {
			corners: [
				[cx - hw, cy - hh],
				[cx + hw, cy - hh],
				[cx + hw, cy + hh],
				[cx - hw, cy + hh]
			]
		};
	}

	function pointInQuad(point: Point, q: QuadParams): boolean {
		// Ray-casting on the 4-corner polygon
		const pts = q.corners;
		let inside = false;
		for (let i = 0, j = 3; i < 4; j = i++) {
			const xi = pts[i][0], yi = pts[i][1];
			const xj = pts[j][0], yj = pts[j][1];
			if (yi > point[1] !== yj > point[1] && point[0] < ((xj - xi) * (point[1] - yi)) / (yj - yi) + xi) {
				inside = !inside;
			}
		}
		return inside;
	}

	function hitQuadCorner(channel: RectChannel, point: Point): QuadHandle | null {
		const q = quadParams[channel];
		if (!q) return null;
		for (let i = 0; i < 4; i++) {
			if (pointDistance(point, q.corners[i]) <= HANDLE_HIT_RADIUS) return i as QuadHandle;
		}
		return null;
	}

	function deriveQuadFromPolygon(points: number[][]): QuadParams | null {
		if (points.length < 3) return null;
		if (points.length === 4) {
			return {
				corners: points.map((p) => [p[0], p[1]] as Point) as [Point, Point, Point, Point]
			};
		}
		// Bounding rect fallback
		const cx = points.reduce((s, p) => s + p[0], 0) / points.length;
		const cy = points.reduce((s, p) => s + p[1], 0) / points.length;
		const maxDx = Math.max(...points.map((p) => Math.abs(p[0] - cx)));
		const maxDy = Math.max(...points.map((p) => Math.abs(p[1] - cy)));
		const hw = Math.max(20, maxDx);
		const hh = Math.max(20, maxDy);
		return {
			corners: [
				[cx - hw, cy - hh],
				[cx + hw, cy - hh],
				[cx + hw, cy + hh],
				[cx - hw, cy + hh]
			]
		};
	}

	// ---- End quad helpers ----

	function getArcHandles(channel: ArcChannel): Record<ArcHandle, Point> | null {
		const params = arcParams[channel];
		if (!params) return null;
		const ringHandleCandidates = Array.from({ length: 12 }, (_, index) => index * 30);
		const occupiedAngles = [
			params.dropZone.startAngle,
			params.dropZone.endAngle,
			params.exitZone.startAngle,
			params.exitZone.endAngle
		];
		const ringHandleAngle =
			ringHandleCandidates.reduce(
				(best, candidate) =>
					ringHandleCandidates.length === 0 ||
					Math.min(...occupiedAngles.map((angle) => angularDistance(candidate, angle))) >
						Math.min(...occupiedAngles.map((angle) => angularDistance(best, angle)))
						? candidate
						: best,
				270
			) ?? 270;
		return {
			center: [params.center[0], params.center[1]],
			inner: polarPoint(params.center, params.innerRadius, ringHandleAngle),
			outer: polarPoint(params.center, params.outerRadius, ringHandleAngle),
			dropStart: polarPoint(params.center, params.outerRadius, params.dropZone.startAngle),
			dropEnd: polarPoint(params.center, params.outerRadius, params.dropZone.endAngle),
			exitStart: polarPoint(params.center, params.outerRadius, params.exitZone.startAngle),
			exitEnd: polarPoint(params.center, params.outerRadius, params.exitZone.endAngle)
		};
	}

	function setArc(channel: ArcChannel, next: ArcParams) {
		const clamped = {
			...next,
			innerRadius: Math.max(10, Math.min(next.innerRadius, next.outerRadius - MIN_ARC_THICKNESS)),
			outerRadius: Math.max(next.innerRadius + MIN_ARC_THICKNESS, next.outerRadius),
			dropZone: clampZone(next.dropZone),
			exitZone: clampZone(next.exitZone)
		};
		arcParams[channel] = clamped;
	}

	function streamUrl(channel: Channel): string {
		if (editingZone) {
			return `${backendHttpBaseUrl}/api/cameras/feed/${CAMERA_FOR_CHANNEL[channel]}?direct=true&annotated=false&v=${feedRevision}`;
		}
		const annotatedParam = previewAnnotated ? 'true' : 'false';
		const colorParam = previewColorCorrect ? 'true' : 'false';
		const dashboardParam = previewCropped ? 'true' : 'false';
		const zonesParam = previewZones ? 'true' : 'false';
		return `${backendHttpBaseUrl}/api/cameras/feed/${CAMERA_FOR_CHANNEL[channel]}?annotated=${annotatedParam}&color_correct=${colorParam}&dashboard=${dashboardParam}&show_regions=${zonesParam}&v=${feedRevision}`;
	}

	function feedInstanceKey(channel: Channel): string {
		const assignment = currentAssignment(channel);
		const mode = editingZone
			? 'direct-raw'
			: `${previewAnnotated ? 'annot' : 'raw'}-${previewColorCorrect ? 'cc' : 'nocc'}-${previewCropped ? 'crop' : 'full'}-${previewZones ? 'z' : 'nz'}`;
		return `${currentRole(channel)}::${assignment === null ? 'none' : String(assignment)}::${mode}::${feedRevision}`;
	}

	async function loadCameraConfig() {
		try {
			const res = await fetch(`${backendHttpBaseUrl}/api/cameras/config`);
			if (!res.ok) return;
			const cfg = await res.json();
			for (const role of ALL_CAMERA_ROLES) {
				const nextValue = cfg[role] ?? null;
				assignments[role] = nextValue;
			}
		} catch {
			// ignore
		} finally {
			cameraConfigLoaded = true;
		}
	}

	function cancelCameraScan() {
		if (cameraAbort) {
			cameraAbort.abort();
			cameraAbort = null;
		}
		cameraLoading = false;
		cameraModalOpen = false;
	}

	async function refreshCameras() {
		if (cameraAbort) {
			cameraAbort.abort();
			cameraAbort = null;
		}
		cameraLoading = true;
		cameraError = null;
		const abort = new AbortController();
		cameraAbort = abort;
		try {
			await loadCameraConfig();
			const res = await fetch(`${backendHttpBaseUrl}/api/cameras/list`, { signal: abort.signal });
			if (!res.ok) throw new Error(await res.text());
			const payload = await res.json();
			if (Array.isArray(payload)) {
				usbCameras = payload;
				networkCameras = [];
				return;
			}
			usbCameras = Array.isArray(payload.usb) ? payload.usb : [];
			networkCameras = Array.isArray(payload.network) ? payload.network : [];
		} catch (e: any) {
			if (e.name === 'AbortError') return;
			cameraError = e.message ?? 'Failed to scan cameras';
		} finally {
			cameraLoading = false;
			cameraAbort = null;
		}
	}

	async function openCameraPicker() {
		cameraModalOpen = true;
		await refreshCameras();
	}

	async function saveCameraRole(role: CameraRole, source: CameraSource) {
		cameraSaving = true;
		cameraError = null;
		try {
			const res = await fetch(`${backendHttpBaseUrl}/api/cameras/assign`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ [role]: source })
			});
			if (!res.ok) throw new Error(await res.text());
			assignments[role] = source;
			feedRevision += 1;
			statusMsg = source === null ? 'Camera cleared.' : 'Camera updated.';
		} catch (e: any) {
			cameraError = e.message ?? 'Failed to save camera';
		} finally {
			cameraSaving = false;
		}
	}

	function findRoleUsing(source: CameraSource, excludeRole: CameraRole): CameraRole | null {
		for (const role of ALL_CAMERA_ROLES) {
			if (role !== excludeRole && assignments[role] === source) return role;
		}
		return null;
	}

	async function selectCamera(role: CameraRole, cameraIndex: number) {
		const otherRole = findRoleUsing(cameraIndex, role);
		if (otherRole) {
			const cam = usbCameras.find((c) => c.index === cameraIndex);
			reassignConfirm = {
				source: cameraIndex,
				targetRole: role,
				currentRole: otherRole,
				cameraLabel: cam?.name ?? `Camera ${cameraIndex}`
			};
			reassignModalOpen = true;
			return;
		}
		await saveCameraRole(role, cameraIndex);
		if (!cameraError) {
			cameraModalOpen = false;
		}
	}

	async function confirmReassign() {
		if (!reassignConfirm) return;
		const { source, targetRole, currentRole: fromRole } = reassignConfirm;
		reassignConfirm = null;
		reassignModalOpen = false;
		await saveCameraRole(fromRole, null);
		if (cameraError) return;
		await saveCameraRole(targetRole, source);
		if (!cameraError) {
			cameraModalOpen = false;
		}
	}

	function sortPolygon(pts: number[][]): number[][] {
		if (pts.length < 2) return [...pts];
		const cx = pts.reduce((sum, pt) => sum + pt[0], 0) / pts.length;
		const cy = pts.reduce((sum, pt) => sum + pt[1], 0) / pts.length;
		return [...pts].sort(
			(a, b) => Math.atan2(a[1] - cy, a[0] - cx) - Math.atan2(b[1] - cy, b[0] - cx)
		);
	}

	function polyCenter(pts: number[][]): number[] | null {
		const sorted = sortPolygon(pts);
		if (sorted.length < 2) return null;
		return [
			sorted.reduce((sum, pt) => sum + pt[0], 0) / sorted.length,
			sorted.reduce((sum, pt) => sum + pt[1], 0) / sorted.length
		];
	}

	function getShapePoints(channel: Channel): Point[] {
		if (isArcChannel(channel)) {
			const params = arcParams[channel];
			if (!params) return [];
			return buildCirclePoints(params.center, params.outerRadius);
		}
		if (isRectChannel(channel)) {
			const q = quadParams[channel];
			if (!q) return [];
			return [...q.corners];
		}
		return sortPolygon(userPoints[channel]).map((pt) => [pt[0], pt[1]]);
	}

	function getChannelCenter(channel: Channel): Point | null {
		if (isArcChannel(channel)) {
			return arcParams[channel]?.center ?? null;
		}
		if (isRectChannel(channel)) {
			const q = quadParams[channel];
			return q ? quadCenter(q) : null;
		}
		const center = polyCenter(userPoints[channel]);
		return center ? [center[0], center[1]] : null;
	}

	function computeAngle(channel: ArcChannel): number | null {
		const ref = sectionZeroPoints[channel];
		const center = getChannelCenter(channel);
		if (!ref || !center) return null;
		return angleFromCenter(ref, center);
	}

	function canvasCoords(e: MouseEvent): Point {
		const rect = canvasEl.getBoundingClientRect();
		return [
			((e.clientX - rect.left) * CANVAS_W) / rect.width,
			((e.clientY - rect.top) * CANVAS_H) / rect.height
		];
	}

	function pointInPolygon(x: number, y: number, pts: Point[]): boolean {
		if (pts.length < 3) return false;
		let inside = false;
		for (let i = 0, j = pts.length - 1; i < pts.length; j = i++) {
			const xi = pts[i][0];
			const yi = pts[i][1];
			const xj = pts[j][0];
			const yj = pts[j][1];
			if (yi > y !== yj > y && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) {
				inside = !inside;
			}
		}
		return inside;
	}

	function pointInAnnulus(point: Point, params: ArcParams): boolean {
		const distance = pointDistance(point, params.center);
		return distance >= params.innerRadius && distance <= params.outerRadius;
	}

	function hitArcHandle(channel: ArcChannel, point: Point): ArcHandle | null {
		const handles = getArcHandles(channel);
		if (!handles) return null;
		const order: ArcHandle[] = [
			'dropStart',
			'dropEnd',
			'exitStart',
			'exitEnd',
			'outer',
			'inner',
			'center'
		];
		for (const handle of order) {
			if (pointDistance(point, handles[handle]) <= HANDLE_HIT_RADIUS) {
				return handle;
			}
		}
		return null;
	}

	function hitPolygonVertex(channel: Channel, point: Point): boolean {
		return userPoints[channel].some(
			(vertex: number[]) => pointDistance(point, [vertex[0], vertex[1]]) <= VERTEX_HIT_RADIUS
		);
	}

	function updateCanvasCursor(point: Point) {
		if (!editingZone) {
			canvasCursor = 'default';
			return;
		}

		if (dragState) {
			canvasCursor = 'grabbing';
			return;
		}

		if (isArcChannel(currentChannel)) {
			const sectionZero = sectionZeroPoints[currentChannel];
			if (sectionZero && pointDistance(point, sectionZero) <= HANDLE_HIT_RADIUS) {
				canvasCursor = 'pointer';
				return;
			}
			if (hitArcHandle(currentChannel, point)) {
				canvasCursor = 'pointer';
				return;
			}
			canvasCursor =
				arcParams[currentChannel] && pointInAnnulus(point, arcParams[currentChannel]!)
					? 'grab'
					: 'crosshair';
			return;
		}

		if (isRectChannel(currentChannel)) {
			const q = quadParams[currentChannel];
			if (q) {
				if (hitQuadCorner(currentChannel, point) !== null) {
					canvasCursor = 'pointer';
					return;
				}
				if (pointInQuad(point, q)) {
					canvasCursor = 'grab';
					return;
				}
			}
			canvasCursor = 'crosshair';
			return;
		}

		if (hitPolygonVertex(currentChannel, point)) {
			canvasCursor = 'pointer';
			return;
		}

		const shape = getShapePoints(currentChannel);
		canvasCursor =
			shape.length >= 3 && pointInPolygon(point[0], point[1], shape) ? 'grab' : 'crosshair';
	}

	function onMouseDown(e: MouseEvent) {
		if (!editingZone) return;
		if (e.button !== 0) return;
		const point = canvasCoords(e);
		didDrag = false;

		if (isArcChannel(currentChannel)) {
			const sectionZero = sectionZeroPoints[currentChannel];
			if (sectionZero && pointDistance(point, sectionZero) <= HANDLE_HIT_RADIUS) {
				dragState = { kind: 'section-zero', channel: currentChannel };
				canvasCursor = 'grabbing';
				return;
			}

			const handle = hitArcHandle(currentChannel, point);
			const params = arcParams[currentChannel];
			if (handle && params) {
				if (handle === 'center') {
					dragState = {
						kind: 'arc-center',
						channel: currentChannel,
						start: point,
						orig: copyArcParams(params),
						origSec0: sectionZero ? [sectionZero[0], sectionZero[1]] : null
					};
					canvasCursor = 'grabbing';
					return;
				}
				dragState = {
					kind:
						handle === 'inner'
							? 'arc-inner'
							: handle === 'outer'
								? 'arc-outer'
								: handle === 'dropStart'
									? 'arc-drop-start'
									: handle === 'dropEnd'
										? 'arc-drop-end'
										: handle === 'exitStart'
											? 'arc-exit-start'
											: 'arc-exit-end',
					channel: currentChannel,
					orig: copyArcParams(params)
				};
				canvasCursor = 'grabbing';
				return;
			}

			if (params && pointInAnnulus(point, params) && !e.shiftKey) {
				dragState = {
					kind: 'arc-shape',
					channel: currentChannel,
					start: point,
					orig: copyArcParams(params),
					origSec0: sectionZero ? [sectionZero[0], sectionZero[1]] : null
				};
				canvasCursor = 'grabbing';
				return;
			}
			return;
		}

		if (isRectChannel(currentChannel)) {
			const q = quadParams[currentChannel];
			if (!q) {
				const def = defaultQuadParams(currentChannel);
				const dc = quadCenter(def);
				const dx = point[0] - dc[0];
				const dy = point[1] - dc[1];
				quadParams[currentChannel] = {
					corners: def.corners.map((c) => [c[0] + dx, c[1] + dy] as Point) as [Point, Point, Point, Point]
				};
				return;
			}
			const cornerIdx = hitQuadCorner(currentChannel, point);
			if (cornerIdx !== null) {
				dragState = { kind: 'quad-corner', channel: currentChannel, cornerIdx };
				canvasCursor = 'grabbing';
				return;
			}
			if (pointInQuad(point, q)) {
				dragState = {
					kind: 'quad-shape',
					channel: currentChannel,
					start: point,
					origCorners: copyQuadParams(q).corners
				};
				canvasCursor = 'grabbing';
			}
			return;
		}

		const polyChannel = currentChannel as 'second' | 'third';
		const shape = getShapePoints(polyChannel);
		if (shape.length >= 3 && pointInPolygon(point[0], point[1], shape) && !e.shiftKey) {
			dragState = {
				kind: 'polygon-shape',
				channel: polyChannel,
				start: point,
				origPts: userPoints[polyChannel].map((pt: number[]) => [pt[0], pt[1]]),
				origSec0: null
			};
			canvasCursor = 'grabbing';
		}
	}

	function onMouseMove(e: MouseEvent) {
		if (!editingZone) {
			canvasCursor = 'default';
			return;
		}

		const point = canvasCoords(e);
		if (!dragState) {
			updateCanvasCursor(point);
			return;
		}

		canvasCursor = 'grabbing';

		switch (dragState.kind) {
			case 'polygon-shape': {
				const dx = point[0] - dragState.start[0];
				const dy = point[1] - dragState.start[1];
				if (Math.hypot(dx, dy) > 5) didDrag = true;
				userPoints[dragState.channel] = dragState.origPts.map((pt) => [pt[0] + dx, pt[1] + dy]);
				break;
			}
			case 'arc-shape':
			case 'arc-center': {
				const dx = point[0] - dragState.start[0];
				const dy = point[1] - dragState.start[1];
				if (Math.hypot(dx, dy) > 5) didDrag = true;
				setArc(dragState.channel, {
					...dragState.orig,
					center: [dragState.orig.center[0] + dx, dragState.orig.center[1] + dy]
				});
				if (dragState.origSec0) {
					sectionZeroPoints[dragState.channel] = [
						dragState.origSec0[0] + dx,
						dragState.origSec0[1] + dy
					];
				}
				break;
			}
			case 'arc-inner': {
				didDrag = true;
				const radius = pointDistance(point, dragState.orig.center);
				setArc(dragState.channel, {
					...dragState.orig,
					innerRadius: Math.max(
						10,
						Math.min(radius, dragState.orig.outerRadius - MIN_ARC_THICKNESS)
					)
				});
				break;
			}
			case 'arc-outer': {
				didDrag = true;
				const radius = pointDistance(point, dragState.orig.center);
				setArc(dragState.channel, {
					...dragState.orig,
					outerRadius: Math.max(dragState.orig.innerRadius + MIN_ARC_THICKNESS, radius)
				});
				break;
			}
			case 'arc-drop-start': {
				didDrag = true;
				setArc(dragState.channel, {
					...dragState.orig,
					dropZone: {
						...dragState.orig.dropZone,
						startAngle: angleFromCenter(point, dragState.orig.center)
					}
				});
				break;
			}
			case 'arc-drop-end': {
				didDrag = true;
				setArc(dragState.channel, {
					...dragState.orig,
					dropZone: {
						...dragState.orig.dropZone,
						endAngle: angleFromCenter(point, dragState.orig.center)
					}
				});
				break;
			}
			case 'arc-exit-start': {
				didDrag = true;
				setArc(dragState.channel, {
					...dragState.orig,
					exitZone: {
						...dragState.orig.exitZone,
						startAngle: angleFromCenter(point, dragState.orig.center)
					}
				});
				break;
			}
			case 'arc-exit-end': {
				didDrag = true;
				setArc(dragState.channel, {
					...dragState.orig,
					exitZone: {
						...dragState.orig.exitZone,
						endAngle: angleFromCenter(point, dragState.orig.center)
					}
				});
				break;
			}
			case 'section-zero': {
				didDrag = true;
				sectionZeroPoints[dragState.channel] = point;
				break;
			}
			case 'quad-shape': {
				const dx = point[0] - dragState.start[0];
				const dy = point[1] - dragState.start[1];
				if (Math.hypot(dx, dy) > 5) didDrag = true;
				quadParams[dragState.channel] = {
					corners: dragState.origCorners.map((c) => [c[0] + dx, c[1] + dy] as Point) as [Point, Point, Point, Point]
				};
				break;
			}
			case 'quad-corner': {
				didDrag = true;
				const q = quadParams[dragState.channel];
				if (q) {
					const newCorners = [...q.corners] as [Point, Point, Point, Point];
					newCorners[dragState.cornerIdx] = point;
					quadParams[dragState.channel] = { corners: newCorners };
				}
				break;
			}
		}
	}

	function onMouseUp(e: MouseEvent) {
		if (!editingZone) {
			canvasCursor = 'default';
			return;
		}
		if (e.button !== 0) return;
		dragState = null;
		updateCanvasCursor(canvasCoords(e));
	}

	function onClick(e: MouseEvent) {
		if (!editingZone) return;
		if (didDrag) {
			didDrag = false;
			return;
		}

		const point = canvasCoords(e);
		if (isArcChannel(currentChannel)) {
			if (e.shiftKey) {
				sectionZeroPoints[currentChannel] = point;
			}
			return;
		}

		if (isRectChannel(currentChannel)) {
			// Click places a new rect if none exists (handled in onMouseDown)
			return;
		}

		const ch = currentChannel as 'second' | 'third';
		const shape = getShapePoints(ch);
		if (shape.length >= 3 && pointInPolygon(point[0], point[1], shape)) return;
		userPoints[ch] = [...userPoints[ch], [point[0], point[1]]];
	}

	function onContextMenu(e: MouseEvent) {
		if (!editingZone) return;
		e.preventDefault();
		if (isArcChannel(currentChannel) || isRectChannel(currentChannel)) {
			return;
		}

		const ch = currentChannel as 'second' | 'third';
		const point = canvasCoords(e);
		const pts = userPoints[ch];
		let minDist = Infinity;
		let minIdx = -1;
		for (let i = 0; i < pts.length; i++) {
			const dist = Math.hypot(pts[i][0] - point[0], pts[i][1] - point[1]);
			if (dist < minDist) {
				minDist = dist;
				minIdx = i;
			}
		}
		if (minIdx >= 0 && minDist < 40) {
			userPoints[ch] = pts.filter((_: number[], idx: number) => idx !== minIdx);
		}
	}

	function onWheel(e: WheelEvent) {
		if (!editingZone) return;
		e.preventDefault();
		const scale = e.deltaY > 0 ? 0.99 : 1.01;

		if (isArcChannel(currentChannel)) {
			const params = arcParams[currentChannel];
			if (!params) return;
			const nextInner = Math.max(10, params.innerRadius * scale);
			const nextOuter = Math.max(nextInner + MIN_ARC_THICKNESS, params.outerRadius * scale);
			setArc(currentChannel, {
				...params,
				innerRadius: nextInner,
				outerRadius: nextOuter
			});
			return;
		}

		if (isRectChannel(currentChannel)) {
			const q = quadParams[currentChannel];
			if (!q) return;
			const center = quadCenter(q);
			quadParams[currentChannel] = {
				corners: q.corners.map((c) => [
					center[0] + (c[0] - center[0]) * scale,
					center[1] + (c[1] - center[1]) * scale
				] as Point) as [Point, Point, Point, Point]
			};
			return;
		}

		const ch = currentChannel as 'second' | 'third';
		const pts = userPoints[ch];
		if (pts.length < 3) return;
		const cx = pts.reduce((sum: number, pt: number[]) => sum + pt[0], 0) / pts.length;
		const cy = pts.reduce((sum: number, pt: number[]) => sum + pt[1], 0) / pts.length;
		userPoints[ch] = pts.map((pt: number[]) => [
			cx + (pt[0] - cx) * scale,
			cy + (pt[1] - cy) * scale
		]);
	}

	function drawHandle(
		ctx: CanvasRenderingContext2D,
		point: Point,
		fill: string,
		stroke: string,
		label: string,
		offset: Point = [0, -20]
	) {
		ctx.beginPath();
		ctx.arc(point[0], point[1], HANDLE_DRAW_RADIUS, 0, Math.PI * 2);
		ctx.fillStyle = fill;
		ctx.fill();
		ctx.lineWidth = 2;
		ctx.strokeStyle = stroke;
		ctx.stroke();

		ctx.font = 'bold 13px sans-serif';
		ctx.textAlign = 'center';
		ctx.textBaseline = 'middle';
		const metrics = ctx.measureText(label);
		const textWidth = metrics.width;
		const paddingX = 9;
		const boxWidth = textWidth + paddingX * 2;
		const boxHeight = 24;
		const minLabelX = LABEL_EDGE_PADDING + boxWidth / 2;
		const maxLabelX = CANVAS_W - LABEL_EDGE_PADDING - boxWidth / 2;
		const minLabelY = LABEL_EDGE_PADDING + boxHeight / 2;
		const maxLabelY = CANVAS_H - LABEL_EDGE_PADDING - boxHeight / 2;
		const labelX = clamp(point[0] + offset[0], minLabelX, Math.max(minLabelX, maxLabelX));
		const labelY = clamp(point[1] + offset[1], minLabelY, Math.max(minLabelY, maxLabelY));
		const boxX = labelX - boxWidth / 2;
		const boxY = labelY - boxHeight / 2;
		ctx.save();
		ctx.shadowColor = 'rgba(0, 0, 0, 0.28)';
		ctx.shadowBlur = 12;
		ctx.shadowOffsetX = 0;
		ctx.shadowOffsetY = 4;
		ctx.beginPath();
		ctx.roundRect(boxX, boxY, boxWidth, boxHeight, 4);
		ctx.fillStyle = 'rgba(255, 255, 255, 0.96)';
		ctx.fill();
		ctx.restore();
		ctx.beginPath();
		ctx.roundRect(boxX, boxY, boxWidth, boxHeight, 4);
		ctx.strokeStyle = 'rgba(17, 17, 17, 0.12)';
		ctx.lineWidth = 1;
		ctx.stroke();
		ctx.fillStyle = '#111';
		ctx.fillText(label, labelX, labelY);
	}

	function drawSectionZero(ctx: CanvasRenderingContext2D, channel: ArcChannel, active: boolean) {
		if (!editingZone) return;
		const center = getChannelCenter(channel);
		const ref = sectionZeroPoints[channel];
		if (!center || !ref) return;

		ctx.beginPath();
		ctx.moveTo(center[0], center[1]);
		ctx.lineTo(ref[0], ref[1]);
		ctx.strokeStyle = `rgba(255,255,255,${active ? 0.9 : 0.3})`;
		ctx.lineWidth = active ? 2 : 1;
		ctx.setLineDash([6, 4]);
		ctx.stroke();
		ctx.setLineDash([]);

		drawHandle(ctx, ref, `rgba(255,255,255,${active ? 0.95 : 0.35})`, 'rgba(0,0,0,0.7)', '0');
	}

	function drawArcChannel(ctx: CanvasRenderingContext2D, channel: ArcChannel, active: boolean) {
		const params = arcParams[channel];
		if (!params) return;

		const color = CHANNEL_COLORS[channel];
		const alpha = active ? 1 : 0.35;
		const outerCircle = buildCirclePoints(params.center, params.outerRadius);
		const innerCircle = buildCirclePoints(params.center, params.innerRadius);
		const dropPolygon = buildZonePolygon(params, params.dropZone);
		const exitPolygon = buildZonePolygon(params, params.exitZone);

		ctx.beginPath();
		ctx.moveTo(outerCircle[0][0], outerCircle[0][1]);
		for (let i = 1; i < outerCircle.length; i++) {
			ctx.lineTo(outerCircle[i][0], outerCircle[i][1]);
		}
		ctx.closePath();
		ctx.moveTo(innerCircle[0][0], innerCircle[0][1]);
		for (let i = 1; i < innerCircle.length; i++) {
			ctx.lineTo(innerCircle[i][0], innerCircle[i][1]);
		}
		ctx.closePath();
		ctx.fillStyle = active ? `${color}14` : `${color}0a`;
		ctx.fill('evenodd');

		for (const [zonePolygon, zoneColor, zoneAlpha] of [
			[dropPolygon, DROP_ZONE_COLOR, active ? 0.22 : 0.1],
			[exitPolygon, EXIT_ZONE_COLOR, active ? 0.22 : 0.1]
		] as const) {
			ctx.beginPath();
			ctx.moveTo(zonePolygon[0][0], zonePolygon[0][1]);
			for (let i = 1; i < zonePolygon.length; i++) {
				ctx.lineTo(zonePolygon[i][0], zonePolygon[i][1]);
			}
			ctx.closePath();
			ctx.fillStyle = zoneColor;
			ctx.globalAlpha = zoneAlpha;
			ctx.fill();
			ctx.globalAlpha = 1;
		}

		ctx.beginPath();
		ctx.moveTo(outerCircle[0][0], outerCircle[0][1]);
		for (let i = 1; i < outerCircle.length; i++) {
			ctx.lineTo(outerCircle[i][0], outerCircle[i][1]);
		}
		ctx.closePath();
		ctx.strokeStyle = color;
		ctx.globalAlpha = alpha;
		ctx.lineWidth = active ? 2 : 1;
		ctx.stroke();
		ctx.beginPath();
		ctx.moveTo(innerCircle[0][0], innerCircle[0][1]);
		for (let i = 1; i < innerCircle.length; i++) {
			ctx.lineTo(innerCircle[i][0], innerCircle[i][1]);
		}
		ctx.closePath();
		ctx.stroke();
		ctx.globalAlpha = 1;

		const handles = getArcHandles(channel);
		if (!handles) return;

		if (active && editingZone) {
			ctx.strokeStyle = `${DROP_ZONE_COLOR}cc`;
			ctx.lineWidth = 1.25;
			ctx.beginPath();
			ctx.moveTo(params.center[0], params.center[1]);
			ctx.lineTo(handles.dropStart[0], handles.dropStart[1]);
			ctx.moveTo(params.center[0], params.center[1]);
			ctx.lineTo(handles.dropEnd[0], handles.dropEnd[1]);
			ctx.stroke();

			ctx.strokeStyle = `${EXIT_ZONE_COLOR}cc`;
			ctx.lineWidth = 1;
			ctx.beginPath();
			ctx.moveTo(params.center[0], params.center[1]);
			ctx.lineTo(handles.exitStart[0], handles.exitStart[1]);
			ctx.moveTo(params.center[0], params.center[1]);
			ctx.lineTo(handles.exitEnd[0], handles.exitEnd[1]);
			ctx.stroke();

			ctx.strokeStyle = `${color}aa`;
			ctx.beginPath();
			ctx.moveTo(params.center[0], params.center[1]);
			ctx.lineTo(handles.inner[0], handles.inner[1]);
			ctx.moveTo(params.center[0], params.center[1]);
			ctx.lineTo(handles.outer[0], handles.outer[1]);
			ctx.stroke();

			drawHandle(ctx, handles.center, color, '#111', 'Center');
			drawHandle(ctx, handles.inner, color, '#111', 'Inner');
			drawHandle(ctx, handles.outer, color, '#111', 'Outer');
			drawHandle(ctx, handles.dropStart, DROP_ZONE_COLOR, '#111', 'Drop Start', [-40, -20]);
			drawHandle(ctx, handles.dropEnd, DROP_ZONE_COLOR, '#111', 'Drop End', [40, -20]);
			drawHandle(ctx, handles.exitStart, EXIT_ZONE_COLOR, '#111', 'Exit Start', [-40, 24]);
			drawHandle(ctx, handles.exitEnd, EXIT_ZONE_COLOR, '#111', 'Exit End', [40, 24]);
		}

		drawSectionZero(ctx, channel, active);
	}

	function drawPolygonChannel(ctx: CanvasRenderingContext2D, channel: Channel, active: boolean) {
		const pts = sortPolygon(userPoints[channel]);
		if (pts.length < 2) return;
		const color = CHANNEL_COLORS[channel];
		const alpha = active ? 1 : 0.35;

		ctx.beginPath();
		ctx.moveTo(pts[0][0], pts[0][1]);
		for (let i = 1; i < pts.length; i++) ctx.lineTo(pts[i][0], pts[i][1]);
		ctx.closePath();
		ctx.fillStyle = active ? `${color}20` : `${color}0d`;
		ctx.fill();
		ctx.strokeStyle = color;
		ctx.globalAlpha = alpha;
		ctx.lineWidth = active ? 2 : 1;
		ctx.stroke();
		ctx.globalAlpha = 1;

		if (active && editingZone) {
			for (const pt of pts) {
				ctx.beginPath();
				ctx.arc(pt[0], pt[1], 6, 0, Math.PI * 2);
				ctx.fillStyle = color;
				ctx.fill();
			}
		}
	}

	function drawQuadChannel(ctx: CanvasRenderingContext2D, channel: RectChannel, active: boolean) {
		const q = quadParams[channel];
		if (!q) return;
		const color = CHANNEL_COLORS[channel];
		const alpha = active ? 1 : 0.35;
		const corners = q.corners;

		// Fill
		ctx.beginPath();
		ctx.moveTo(corners[0][0], corners[0][1]);
		for (let i = 1; i < 4; i++) ctx.lineTo(corners[i][0], corners[i][1]);
		ctx.closePath();
		ctx.fillStyle = active ? `${color}20` : `${color}0d`;
		ctx.fill();

		// Stroke
		ctx.strokeStyle = color;
		ctx.globalAlpha = alpha;
		ctx.lineWidth = active ? 2 : 1;
		ctx.stroke();
		ctx.globalAlpha = 1;

		if (active && editingZone) {
			// Corner handles
			for (const corner of corners) {
				ctx.beginPath();
				ctx.arc(corner[0], corner[1], HANDLE_DRAW_RADIUS, 0, Math.PI * 2);
				ctx.fillStyle = color;
				ctx.fill();
				ctx.lineWidth = 2;
				ctx.strokeStyle = '#111';
				ctx.stroke();
			}
		}
	}

	function drawChannel(ctx: CanvasRenderingContext2D, channel: Channel, active: boolean) {
		if (isArcChannel(channel)) {
			drawArcChannel(ctx, channel, active);
			return;
		}
		if (isRectChannel(channel)) {
			drawQuadChannel(ctx, channel, active);
			return;
		}
		drawPolygonChannel(ctx, channel, active);
	}

	function drawCanvas() {
		if (!canvasEl) return;
		const ctx = canvasEl.getContext('2d');
		if (!ctx) return;

		ctx.clearRect(0, 0, CANVAS_W, CANVAS_H);
		const currentCamera = CAMERA_FOR_CHANNEL[currentChannel];

		for (const channel of channels) {
			if (channel === currentChannel) continue;
			if (CAMERA_FOR_CHANNEL[channel] === currentCamera) {
				drawChannel(ctx, channel, false);
			}
		}

		drawChannel(ctx, currentChannel, true);
	}

	$effect(() => {
		void userPoints;
		void arcParams;
		void sectionZeroPoints;
		void quadParams;
		void currentChannel;
		void channels;
		void editingZone;
		drawCanvas();
	});

	async function loadPolygons() {
		try {
			const res = await fetch(`${backendHttpBaseUrl}/api/polygons`);
			if (!res.ok) return;
			const data = await res.json();

			const channelData = data.channel ?? {};
			const channelUserPts = channelData.user_pts ?? {};
			const channelPolygons = channelData.polygons ?? {};
			const channelArcParams = channelData.arc_params ?? {};
			const savedChannelAngles = channelData.channel_angles ?? {};
			const sectionZero = channelData.section_zero_pts ?? {};

			for (const channel of ARC_CHANNELS) {
				const savedUserPts = channelUserPts[channel];
				if (Array.isArray(savedUserPts)) {
					userPoints[channel] = savedUserPts;
				}

				const savedAngle =
					typeof savedChannelAngles[channel] === 'number' ? savedChannelAngles[channel] : 0;
				const savedArc = parseArcParams(channelArcParams[channel], channel, savedAngle);
				if (savedArc) {
					arcParams[channel] = savedArc;
				} else {
					const polygonKey = `${channel}_channel`;
					const fallbackPts = savedUserPts ?? channelPolygons[polygonKey];
					const derived = Array.isArray(fallbackPts)
						? deriveArcParamsFromPolygon(fallbackPts, channel, savedAngle)
						: null;
					if (derived) {
						arcParams[channel] = derived;
					}
				}

				if (
					Array.isArray(sectionZero[channel]) &&
					sectionZero[channel].length === 2 &&
					typeof sectionZero[channel][0] === 'number' &&
					typeof sectionZero[channel][1] === 'number'
				) {
					sectionZeroPoints[channel] = [sectionZero[channel][0], sectionZero[channel][1]];
				} else if (arcParams[channel]) {
					sectionZeroPoints[channel] = polarPoint(
						arcParams[channel]!.center,
						arcParams[channel]!.outerRadius,
						savedAngle
					);
				}
			}

			// Load rect params for carousel, classification channels
			const channelQuadParams = channelData.quad_params ?? {};
			const classificationData = data.classification ?? {};
			const classUserPts = classificationData.user_pts ?? {};
			const classPolygons = classificationData.polygons ?? {};
			const classQuadParams = classificationData.quad_params ?? {};

			function loadQuad(saved: any, fallbackPts: any): QuadParams | null {
				if (saved && Array.isArray(saved.corners) && saved.corners.length === 4) {
					return {
						corners: saved.corners.map((c: number[]) => [c[0], c[1]] as Point) as [Point, Point, Point, Point]
					};
				}
				if (Array.isArray(fallbackPts) && fallbackPts.length >= 3) {
					return deriveQuadFromPolygon(fallbackPts);
				}
				return null;
			}

			// Carousel
			const carouselQuad = loadQuad(channelQuadParams.carousel, channelUserPts.carousel ?? channelPolygons.carousel);
			if (carouselQuad) quadParams.carousel = carouselQuad;

			// Classification top
			const topQuad = loadQuad(classQuadParams.class_top, classUserPts.class_top ?? classPolygons.top);
			if (topQuad) quadParams.class_top = topQuad;

			// Classification bottom
			const bottomQuad = loadQuad(classQuadParams.class_bottom, classUserPts.class_bottom ?? classPolygons.bottom);
			if (bottomQuad) quadParams.class_bottom = bottomQuad;
		} catch {
			// ignore
		}
	}

	function serializeQuadParams(q: QuadParams): Record<string, any> {
		return {
			corners: q.corners.map((c) => [Math.round(c[0]), Math.round(c[1])])
		};
	}

	function quadAsPolygon(q: QuadParams): number[][] {
		return q.corners.map((c) => [Math.round(c[0]), Math.round(c[1])]);
	}

	async function saveAll(): Promise<boolean> {
		saving = true;
		try {
			const polygons: Record<string, number[][]> = {};
			const user_pts: Record<string, number[][]> = {};
			const arc_params: Record<string, ArcParamsPayload> = {};
			const quad_params_channel: Record<string, Record<string, any>> = {};

			for (const channel of FEEDER_CHANNELS) {
				const key = channel === 'carousel' ? 'carousel' : `${channel}_channel`;
				if (isArcChannel(channel) && arcParams[channel]) {
					polygons[key] = buildCirclePoints(arcParams[channel]!.center, arcParams[channel]!.outerRadius).map(
						(pt) => [Math.round(pt[0]), Math.round(pt[1])]
					);
					user_pts[channel] = buildRingStoragePoints(arcParams[channel]!).map((pt) => [
						Math.round(pt[0]),
						Math.round(pt[1])
					]);
					arc_params[channel] = serializeArcParams(arcParams[channel]);
				} else if (isRectChannel(channel) && quadParams[channel]) {
					const q = quadParams[channel]!;
					const cornerPts = quadAsPolygon(q);
					polygons[key] = cornerPts;
					user_pts[channel] = cornerPts;
					quad_params_channel[channel] = serializeQuadParams(q);
				} else {
					const points = getShapePoints(channel).map((pt) => [Math.round(pt[0]), Math.round(pt[1])]);
					polygons[key] = points;
					user_pts[channel] = points;
				}
			}

			const channel_angles: Record<string, number> = {};
			for (const channel of ARC_CHANNELS) {
				const angle = computeAngle(channel);
				channel_angles[channel] = angle ?? 0;
			}

			const section_zero_pts: Record<string, number[]> = {};
			for (const channel of ARC_CHANNELS) {
				if (sectionZeroPoints[channel]) {
					section_zero_pts[channel] = sectionZeroPoints[channel]!.map(Math.round);
				}
			}

			const class_polygons: Record<string, number[][]> = {};
			const class_user_pts: Record<string, number[][]> = {};
			const quad_params_class: Record<string, Record<string, any>> = {};
			for (const channel of CLASSIFICATION_CHANNELS) {
				const key = channel === 'class_top' ? 'top' : 'bottom';
				if (isRectChannel(channel) && quadParams[channel]) {
					const q = quadParams[channel]!;
					const cornerPts = quadAsPolygon(q);
					class_polygons[key] = cornerPts;
					class_user_pts[channel] = cornerPts;
					quad_params_class[channel] = serializeQuadParams(q);
				} else {
					const points = sortPolygon(userPoints[channel]).map((pt) => [
						Math.round(pt[0]),
						Math.round(pt[1])
					]);
					class_polygons[key] = points;
					class_user_pts[channel] = userPoints[channel].map((pt) => [
						Math.round(pt[0]),
						Math.round(pt[1])
					]);
				}
			}

			const res = await fetch(`${backendHttpBaseUrl}/api/polygons`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({
					channel: {
						polygons,
						user_pts,
						arc_params,
						quad_params: quad_params_channel,
						channel_angles,
						section_zero_pts,
						resolution: [CANVAS_W, CANVAS_H]
					},
					classification: {
						polygons: class_polygons,
						user_pts: class_user_pts,
						quad_params: quad_params_class,
						resolution: [CANVAS_W, CANVAS_H]
					}
				})
			});
			if (!res.ok) throw new Error(await res.text());
			persistedSnapshot = snapshotCurrentState();
			editingZone = false;
			activeSidebar = null;
			dragState = null;
			didDrag = false;
			canvasCursor = 'default';
			statusMsg = 'Zone saved.';
			dispatch('saved');
			return true;
		} catch (e: any) {
			statusMsg = `Error: ${e.message}`;
			return false;
		} finally {
			saving = false;
		}
	}

	function beginEditing() {
		if (currentAssignment() === null) {
			statusMsg = 'Choose a camera before editing the zone.';
			return;
		}

		if (activeSidebar === 'picture') {
			clearPicturePreview(currentRole());
		}
		if (activeSidebar === 'classification') {
			setDetectionHighlights(currentRole(), null);
		}
		restoreSnapshot(persistedSnapshot);
		editingZone = true;
		activeSidebar = 'zone';
		dragState = null;
		didDrag = false;
		canvasCursor = 'crosshair';
		statusMsg = 'Zone editing enabled.';
	}

	function cancelEditing() {
		restoreSnapshot(persistedSnapshot);
		editingZone = false;
		activeSidebar = null;
		dragState = null;
		didDrag = false;
		canvasCursor = 'default';
		statusMsg = 'Zone changes discarded.';
	}

	function resetCurrentChannel() {
		if (isArcChannel(currentChannel)) {
			arcParams[currentChannel] = defaultArcParams(currentChannel);
			sectionZeroPoints[currentChannel] = null;
			statusMsg = 'Zone reset. Save to keep it.';
			return;
		}
		if (isRectChannel(currentChannel)) {
			quadParams[currentChannel] = defaultQuadParams(currentChannel);
			statusMsg = 'Zone reset. Save to keep it.';
			return;
		}
		(userPoints as Record<string, number[][]>)[currentChannel] = [];
		statusMsg = 'Zone reset. Save to keep it.';
	}

	$effect(() => {
		if (typeof window === 'undefined') {
			return;
		}
		if (!previewViewportEl || typeof ResizeObserver === 'undefined') {
			previewViewportSize = { width: 0, height: 0 };
			return;
		}
		updatePreviewViewportSize();
		const observer = new ResizeObserver(() => {
			updatePreviewViewportSize();
		});
		observer.observe(previewViewportEl);
		return () => observer.disconnect();
	});

	onMount(() => {
		void loadCameraConfig();
		void loadPolygons().finally(() => {
			persistedSnapshot = snapshotCurrentState();
		});
	});
</script>

<div class="flex flex-col">
	<!-- Card header -->
	<div
		class="-mx-4 -mt-4 flex flex-wrap items-center gap-3 border-b border-border bg-surface px-4 py-3"
	>
		<div class="flex min-w-0 flex-1 flex-wrap items-center gap-2">
			{#if channels.length > 1}
				{#each channels as channel}
					{@const active = currentChannel === channel}
					{@const isSep =
						channel === 'class_top' &&
						channels.some((item) => item === 'second' || item === 'third' || item === 'carousel')}
					{#if isSep}
						<div class="h-6 w-px bg-border"></div>
					{/if}
					<button
						onclick={() => selectChannel(channel)}
						class="border px-3 py-1.5 text-xs font-medium transition-colors"
						style:border-color={active ? CHANNEL_COLORS[channel] : undefined}
						class:bg-surface={active}
						class:bg-bg={!active}
						class:text-text={true}
					>
						{CHANNEL_LABELS[channel]}
					</button>
				{/each}
			{:else}
				<h2 class="text-base font-semibold text-text">
					{CHANNEL_LABELS[currentChannel]}
				</h2>
			{/if}

			<div
				class="min-w-0 rounded-full bg-bg px-3 py-1 text-xs text-text-muted flex items-center gap-1"
			>
				<span class="font-medium text-text">Source:</span>
				<span class="ml-1 truncate">{formatSource(currentAssignment())}</span>
				{#if currentAssignment() === null && cameraConfigLoaded}
					<button
						onclick={openCameraPicker}
						class="ml-1 inline-flex h-4 w-4 items-center justify-center rounded-full bg-text-muted/20 text-text hover:bg-text-muted/40 transition-colors cursor-pointer"
						title="Select camera"
					>
						<svg class="h-2.5 w-2.5" viewBox="0 0 12 12" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
							<line x1="6" y1="2" x2="6" y2="10" />
							<line x1="2" y1="6" x2="10" y2="6" />
						</svg>
					</button>
				{/if}
			</div>

			{#if statusMsg}
				<div
					class={`min-w-0 rounded-full border px-3 py-1 text-xs ${
						statusMsg.startsWith('Error:')
							? 'border-danger bg-danger/10 text-danger dark:border-danger dark:bg-danger/10 dark:text-red-400'
							: 'border-border bg-bg text-text-muted'
					}`}
				>
					<span class="truncate">{statusMsg}</span>
				</div>
			{/if}
		</div>

		<div class="ml-auto flex flex-wrap items-center gap-2">
			{#if wizardMode}
				<button
					onclick={saveAll}
					disabled={saving || currentAssignment() === null}
					class="inline-flex cursor-pointer items-center gap-2 border border-success bg-success px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-success/90 disabled:cursor-not-allowed disabled:opacity-60"
				>
					<Check size={15} />
					<span>{saving ? 'Saving...' : 'Save Zone'}</span>
				</button>
			{:else}
				<button
					onclick={openCameraPicker}
					disabled={editingZone}
					class="inline-flex cursor-pointer items-center gap-2 border border-border bg-bg px-3 py-1.5 text-sm text-text transition-colors hover:bg-bg/80 disabled:cursor-not-allowed disabled:opacity-50"
				>
					<Camera size={15} />
					<span>Change Camera</span>
				</button>

				<button
					onclick={togglePictureSidebar}
					disabled={editingZone}
					class={`inline-flex cursor-pointer items-center gap-2 border px-3 py-1.5 text-sm transition-colors disabled:cursor-not-allowed disabled:opacity-50 ${
						activeSidebar === 'picture'
							? 'border-amber-500 bg-amber-500/15 text-amber-700 hover:bg-amber-500/25 dark:text-amber-300'
							: 'border-border bg-bg text-text hover:bg-bg/80'
					}`}
				>
					<SlidersHorizontal size={15} />
					<span>{activeSidebar === 'picture' ? 'Hide Picture' : 'Picture Settings'}</span>
				</button>

				{#if supportsDetectionSidebar(currentChannel)}
					<button
						onclick={toggleClassificationSidebar}
						disabled={editingZone}
						class={`inline-flex cursor-pointer items-center gap-2 border px-3 py-1.5 text-sm transition-colors disabled:cursor-not-allowed disabled:opacity-50 ${
							activeSidebar === 'classification'
								? 'border-violet-500 bg-violet-500/15 text-violet-700 hover:bg-violet-500/25 dark:text-violet-300'
								: 'border-border bg-bg text-text hover:bg-bg/80'
						}`}
					>
						<Bug size={15} />
						<span>{activeSidebar === 'classification' ? 'Hide Detection' : 'Detection'}</span>
					</button>
				{/if}

				{#if editingZone}
					<button
						onclick={resetCurrentChannel}
						class="inline-flex cursor-pointer items-center gap-2 border border-border bg-bg px-3 py-1.5 text-sm text-text transition-colors hover:bg-bg/80"
					>
						<RotateCcw size={15} />
						<span>Reset</span>
					</button>
					<button
						onclick={cancelEditing}
						class="inline-flex cursor-pointer items-center gap-2 border border-border bg-bg px-3 py-1.5 text-sm text-text transition-colors hover:bg-bg/80"
					>
						<X size={15} />
						<span>Cancel</span>
					</button>
					<button
						onclick={saveAll}
						disabled={saving}
						class="inline-flex cursor-pointer items-center gap-2 border border-success bg-success/15 px-3 py-1.5 text-sm text-success transition-colors hover:bg-success/25 disabled:cursor-not-allowed disabled:opacity-50 dark:text-emerald-300"
					>
						<Check size={15} />
						<span>{saving ? 'Saving...' : 'Save Zone'}</span>
					</button>
				{:else}
					<button
						onclick={beginEditing}
						disabled={currentAssignment() === null}
						class="inline-flex cursor-pointer items-center gap-2 border border-primary bg-primary/15 px-3 py-1.5 text-sm text-primary transition-colors hover:bg-primary/25 disabled:cursor-not-allowed disabled:opacity-50"
					>
						<Pencil size={15} />
						<span>Edit Zone</span>
					</button>
				{/if}
			{/if}
		</div>
	</div>

	<!-- Help text -->
	<div class="-mx-4 px-4 py-2 text-sm text-text-muted">
		{#if wizardMode}
			Adjust the zone overlay directly on the preview, then save to keep the updated mask.
		{:else}
			Use the assigned camera as the main view, tune picture settings from the sidebar, and only
			unlock zone editing when you want to change the mask.
		{/if}
	</div>

	<!-- Content -->
	<div class="-mx-4 -mb-4 px-4 pb-4">
		<div
			class={`grid gap-4 ${showSidebarColumn ? 'xl:grid-cols-[minmax(0,1fr)_20rem] xl:items-start' : ''}`}
		>
			<div class="flex min-w-0 flex-col gap-3">
				<div class="relative overflow-hidden bg-black">
					<div
						class={`relative ${wizardMode ? 'min-h-[26rem] sm:min-h-[32rem] lg:min-h-[38rem] xl:min-h-[44rem]' : 'aspect-video'}`}
						bind:this={previewViewportEl}
					>
						{#key feedInstanceKey(currentChannel)}
							{#if !cameraConfigLoaded}
								<div
									class="absolute inset-0 flex items-center justify-center px-6 text-center text-sm text-white/80"
								>
									<div class="max-w-sm rounded-md bg-black/55 px-4 py-3">
										Loading camera source for {CHANNEL_LABELS[currentChannel]}...
									</div>
								</div>
							{:else if currentAssignment() !== null}
								<img
									use:resilientMjpegStream={streamUrl(currentChannel)}
									alt={CHANNEL_LABELS[currentChannel]}
									class="absolute inset-0 h-full w-full object-contain"
									style={feedImageStyle(currentChannel)}
									onload={(event) =>
										rememberPreviewImageSize(currentRole(currentChannel), event.currentTarget)}
								/>
								<div
									class="pointer-events-none absolute"
									style={previewOverlayStyle(currentChannel)}
								>
									{#if getCalibrationHighlight(currentRole())}
										{@const highlight = getCalibrationHighlight(currentRole())!}
										<div
											class="absolute border-2 border-sky-400 shadow-[0_0_0_1px_rgba(255,255,255,0.35),0_0_24px_rgba(56,189,248,0.35)]"
											style={`left:${highlight[0] * 100}%;top:${highlight[1] * 100}%;width:${(highlight[2] - highlight[0]) * 100}%;height:${(highlight[3] - highlight[1]) * 100}%;`}
										>
											<div
												class="absolute -top-7 left-0 rounded bg-sky-400 px-2 py-1 text-xs font-medium text-slate-950 shadow-md"
											>
												Calibration Target
											</div>
										</div>
									{/if}
								{#each getDetectionHighlights(currentRole()) as highlight, index}
									<div
										class={`absolute border-2 shadow-[0_0_0_1px_rgba(255,255,255,0.35)] ${
											index === 0
												? 'border-violet-400 shadow-[0_0_0_1px_rgba(255,255,255,0.35),0_0_24px_rgba(167,139,250,0.35)]'
													: 'border-violet-300/80'
											}`}
										style={`left:${highlight[0] * 100}%;top:${highlight[1] * 100}%;width:${(highlight[2] - highlight[0]) * 100}%;height:${(highlight[3] - highlight[1]) * 100}%;`}
									>
										<div
											class="absolute right-1 top-1 rounded border border-white/20 bg-violet-500/60 px-1.5 py-0.5 text-xs font-semibold leading-none text-white shadow-md backdrop-blur-sm"
										>
											{index + 1}
										</div>
									</div>
								{/each}
							</div>
							{:else}
								<div
									class="absolute inset-0 flex items-center justify-center px-6 text-center text-sm text-white/80"
								>
									<div class="max-w-sm rounded-md bg-black/55 px-4 py-3">
										No camera source configured for {CHANNEL_LABELS[currentChannel]} yet.
									</div>
								</div>
							{/if}
						{/key}

						<canvas
							bind:this={canvasEl}
							width={CANVAS_W}
							height={CANVAS_H}
							class="absolute inset-0 h-full w-full"
							class:pointer-events-none={!editingZone}
							style={`object-fit: contain; cursor: ${canvasCursor}; ${picturePreviewTransform(currentChannel)}`}
							onmousedown={onMouseDown}
							onmousemove={onMouseMove}
							onmouseup={onMouseUp}
							onmouseleave={() => {
								dragState = null;
								canvasCursor = editingZone ? 'crosshair' : 'default';
							}}
							onclick={onClick}
							oncontextmenu={onContextMenu}
							onwheel={onWheel}
						></canvas>

						{#if !editingZone && currentAssignment() !== null}
							<StreamControlsOverlay
								bind:annotated={previewAnnotated}
								bind:colorCorrect={previewColorCorrect}
								bind:cropped={previewCropped}
								bind:zones={previewZones}
								showAnnotations
								showColor
								showCrop
								showZones
							/>
						{/if}
					</div>
				</div>

{#if wizardMode && editingZone}
					<div class="border border-border bg-surface px-4 py-3 text-sm text-text-muted">
						{#if isArcChannel(currentChannel)}
							<div class="grid gap-4 lg:grid-cols-[12rem_minmax(0,1fr)] lg:items-start">
								<div class="overflow-hidden rounded border border-border bg-bg/70">
									<img
										src="/setup/zone-placement-reference.png"
										alt="Drop and exit zone placement reference"
										class="h-auto w-full object-contain"
									/>
								</div>

								<div>
									<div class="font-medium text-text">Placement reference</div>
									<div class="mt-2 rounded border border-success/20 bg-success/8 px-3 py-2 leading-6 text-text-muted">
										<span class="font-medium text-success">Green Drop Zone:</span>
										position this where parts arrive from the previous stage and land on the ring.
									</div>
									<div class="mt-2 rounded border border-danger/20 bg-danger/8 px-3 py-2 leading-6 text-text-muted">
										<span class="font-medium text-danger">Red Exit Zone:</span>
										position this where parts should leave the ring into the next path or mechanism.
									</div>
									<div class="mt-2 text-xs leading-5 text-text-muted">
										Use this as an orientation guide. The exact angles depend on your camera position and the real machine geometry.
									</div>
								</div>
							</div>

							<div class="mt-4 border-t border-border pt-3">
								<div class="font-medium text-text">How to edit</div>
								<div class="mt-2 leading-6">
									Drag the handles for
									<span class="font-medium text-text">Drop</span>,
									<span class="font-medium text-text">Exit</span>,
									<span class="font-medium text-text">Center</span>,
									<span class="font-medium text-text">Inner</span> and
									<span class="font-medium text-text">Outer</span> directly on the image.
								</div>
								<div class="mt-1 leading-6">
									Drag inside the ring to move the whole zone. Use the mouse wheel for fine radius scaling and
									<span class="font-medium text-text"> Shift+Click</span> to set section 0.
								</div>
							</div>
						{:else}
							<div class="font-medium text-text">How to edit</div>
							<div class="mt-2 leading-6">
								Drag the corner handles directly on the image to reshape the zone.
							</div>
							<div class="mt-1 leading-6">
								Drag inside the zone to move it as one shape. Use the mouse wheel to scale it.
							</div>
						{/if}
					</div>
				{/if}
			</div>

			{#if !wizardMode && editingZone && activeSidebar === 'zone'}
				<ZoneEditingSidebar
					label={CHANNEL_LABELS[currentChannel]}
					isArc={isArcChannel(currentChannel)}
					statusMessage={statusMsg}
				/>
			{/if}

			{#if activeSidebar === 'picture'}
				{#key `${currentRole()}::${currentAssignment() === null ? 'none' : String(currentAssignment())}`}
					<PictureSettingsSidebar
						role={currentRole()}
						label={CHANNEL_LABELS[currentChannel]}
						source={currentAssignment()}
						hasCamera={currentAssignment() !== null}
						onPreviewChange={(role, savedSettings, draftSettings) => {
							setPicturePreview(role, savedSettings, draftSettings);
						}}
						onCalibrationHighlightChange={(bbox) => {
							setCalibrationHighlight(currentRole(), bbox);
						}}
						onClose={() => {
							clearPicturePreview(currentRole());
							setCalibrationHighlight(currentRole(), null);
							activeSidebar = null;
						}}
						onSaved={() => {
							clearPicturePreview(currentRole());
							setCalibrationHighlight(currentRole(), null);
							activeSidebar = null;
							feedRevision += 1;
							statusMsg = 'Picture settings updated.';
						}}
					/>
				{/key}
			{/if}

			{#if activeSidebar === 'classification' && supportsDetectionSidebar(currentChannel)}
				{#key `${currentChannel}::${currentAssignment() === null ? 'none' : String(currentAssignment())}`}
					<ClassificationBaselineSection
						scope={detectionScopeForChannel(currentChannel)}
						camera={detectionCameraForChannel(currentChannel)}
						label={CHANNEL_LABELS[currentChannel]}
						hasCamera={currentAssignment() !== null}
						onDetectionHighlightChange={(bboxes) => {
							setDetectionHighlights(currentRole(), bboxes);
						}}
						onClose={() => {
							setDetectionHighlights(currentRole(), null);
							activeSidebar = null;
						}}
					/>
				{/key}
			{/if}

			{#if !wizardMode && !activeSidebar && hasStepper && stepperKey}
				<StepperSidebar {stepperKey} endstop={stepperEndstop} keyboardShortcuts={true} />
			{/if}
		</div>

		<Modal
			bind:open={cameraModalOpen}
			title={`Choose Camera for ${CHANNEL_LABELS[currentChannel]}`}
			wide={true}
		>
			<div class="flex flex-col gap-4">
				{#if cameraError}
					<div
						class="border border-danger bg-danger/10 px-3 py-2 text-sm text-danger dark:border-danger dark:bg-danger/10 dark:text-red-400"
					>
						{cameraError}
					</div>
				{/if}

				{#if cameraLoading}
					<div class="py-8 text-center text-sm text-text-muted animate-pulse">
						Scanning cameras...
					</div>
				{:else}
					{@const hasAnyCameras =
						usbCameras.length > 0 ||
						(ROLE_SUPPORTS_URL[currentRole()] && networkCameras.length > 0)}
					{#if hasAnyCameras}
						<div class="grid grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-4">
							{#each usbCameras as cam}
								{@const role = currentRole()}
								{@const isSelected = assignments[role] === cam.index}
								{@const usedByOther =
									!isSelected &&
									ALL_CAMERA_ROLES.some(
										(otherRole) => otherRole !== role && assignments[otherRole] === cam.index
									)}
								<button
									onclick={() => selectCamera(role, cam.index)}
									disabled={cameraSaving}
									class="group relative overflow-hidden text-left transition-all {isSelected
										? 'ring-2 ring-primary'
										: usedByOther
											? 'opacity-60 hover:opacity-100 hover:ring-2 hover:ring-[#FFD500] dark:hover:ring-[#FFD500]'
											: 'hover:ring-2 hover:ring-primary/50'}"
								>
									{#if cam.preview_available === false}
										<div
											class="flex aspect-video items-center justify-center bg-bg text-center text-xs text-text-muted"
										>
											No preview
										</div>
									{:else}
										<img
											use:resilientMjpegStream={{
												url: cameraIndexPreviewUrl(cam.index),
												firstFrameTimeoutMs: 6000,
												stallTimeoutMs: 4000
											}}
											alt={cam.name ?? `Camera ${cam.index}`}
											class="block aspect-video w-full object-cover"
										/>
									{/if}
									<div
										class="absolute right-0 bottom-0 left-0 bg-gradient-to-t from-black/80 to-transparent px-2 pt-4 pb-1.5 text-xs text-white"
									>
										<div class="font-medium">{cam.name ?? `Camera ${cam.index}`}</div>
										{#if cam.name && cam.width > 0 && cam.height > 0}
											<div class="text-white/70">{cam.width}x{cam.height}</div>
										{:else if !cam.name}
											<div class="text-white/70">
												Index {cam.index}{#if cam.width > 0 && cam.height > 0}
													· {cam.width}x{cam.height}{/if}
											</div>
										{/if}
									</div>
									{#if isSelected}
										<div
											class="absolute top-1.5 right-1.5 rounded-sm bg-primary px-1.5 py-0.5 text-xs font-medium text-primary-contrast"
										>
											Active
										</div>
									{:else if usedByOther}
										{@const otherRole = findRoleUsing(cam.index, role)}
										<div
											class="absolute top-1.5 right-1.5 rounded-sm bg-[#FFD500] px-1.5 py-0.5 text-xs font-medium text-[#1A1A1A]"
										>
											{otherRole ? ROLE_LABELS[otherRole] : 'In use'}
										</div>
									{/if}
								</button>
							{/each}

							{#if ROLE_SUPPORTS_URL[currentRole()]}
								{#each networkCameras as cam}
									{@const role = currentRole()}
									{@const isSelected = assignments[role] === cam.source}
									{@const usedByOther =
										!isSelected &&
										ALL_CAMERA_ROLES.some(
											(otherRole) => otherRole !== role && assignments[otherRole] === cam.source
										)}
									<button
										onclick={() => {
											const otherRole = findRoleUsing(cam.source, role);
											if (otherRole) {
												reassignConfirm = {
													source: cam.source,
													targetRole: role,
													currentRole: otherRole,
													cameraLabel: cam.name
												};
												reassignModalOpen = true;
												return;
											}
											saveCameraRole(role, cam.source);
										}}
										disabled={cameraSaving}
										class="group relative overflow-hidden text-left transition-all {isSelected
											? 'ring-2 ring-primary'
											: usedByOther
												? 'opacity-60 hover:opacity-100 hover:ring-2 hover:ring-[#FFD500] dark:hover:ring-[#FFD500]'
												: 'hover:ring-2 hover:ring-primary/50'}"
									>
										<img
											src={discoveredPreviewUrl(cam)}
											alt={cam.name}
											class="block aspect-video w-full object-cover"
										/>
										<div
											class="absolute right-0 bottom-0 left-0 bg-gradient-to-t from-black/80 to-transparent px-2 pt-4 pb-1.5 text-xs text-white"
										>
											<div class="font-medium">{cam.name}</div>
											<div class="text-white/70">
												{cam.host}:{cam.port}{#if cam.lens_facing}
													· {cam.lens_facing}{/if}
											</div>
										</div>
										{#if isSelected}
											<div
												class="absolute top-1.5 right-1.5 rounded-sm bg-primary px-1.5 py-0.5 text-xs font-medium text-primary-contrast"
											>
												Active
											</div>
										{:else if usedByOther}
											{@const otherRole = findRoleUsing(cam.source, role)}
											<div
												class="absolute top-1.5 right-1.5 rounded-sm bg-[#FFD500] px-1.5 py-0.5 text-xs font-medium text-[#1A1A1A]"
											>
												{otherRole ? ROLE_LABELS[otherRole] : 'In use'}
											</div>
										{/if}
									</button>
								{/each}
							{/if}
						</div>
					{:else}
						<div
							class="border border-dashed border-border px-4 py-8 text-center text-sm text-text-muted"
						>
							No cameras detected. Click Refresh to scan again.
						</div>
					{/if}
				{/if}

				<div
					class="flex items-center justify-between border-t border-border pt-3"
				>
					{#if cameraLoading}
						<button
							onclick={cancelCameraScan}
							class="inline-flex cursor-pointer items-center gap-1.5 text-xs text-text-muted transition-colors hover:text-text"
						>
							<span>Cancel</span>
						</button>
					{:else}
						<button
							onclick={refreshCameras}
							class="inline-flex cursor-pointer items-center gap-1.5 text-xs text-text-muted transition-colors hover:text-text"
						>
							<RefreshCw size={13} />
							<span>Refresh</span>
						</button>
					{/if}
					{#if currentAssignment() !== null}
						<button
							onclick={() => saveCameraRole(currentRole(), null)}
							disabled={cameraSaving}
							class="cursor-pointer text-xs text-danger transition-colors hover:text-danger/80 disabled:cursor-not-allowed disabled:opacity-50 dark:text-red-400 dark:hover:text-red-300"
						>
							Remove current camera
						</button>
					{/if}
				</div>
			</div>
		</Modal>

		{#if reassignConfirm}
			<Modal
				bind:open={reassignModalOpen}
				title="Reassign Camera"
			>
				<div class="flex flex-col gap-4">
					<p class="text-sm text-text">
						<span class="font-medium">{reassignConfirm.cameraLabel}</span> is currently assigned to
						<span class="font-medium">{ROLE_LABELS[reassignConfirm.currentRole]}</span>.
						It will be unassigned from that role.
					</p>
					<div class="flex items-center justify-end gap-2">
						<button
							onclick={() => { reassignConfirm = null; reassignModalOpen = false; }}
							class="cursor-pointer border border-border bg-bg px-3 py-1.5 text-sm text-text hover:bg-surface"
						>
							Cancel
						</button>
						<button
							onclick={confirmReassign}
							disabled={cameraSaving}
							class="cursor-pointer border border-danger bg-danger px-3 py-1.5 text-sm text-white hover:bg-danger/90 disabled:cursor-not-allowed disabled:opacity-50"
						>
							{cameraSaving ? 'Reassigning...' : 'Reassign Camera'}
						</button>
					</div>
				</div>
			</Modal>
		{/if}
	</div>
	<!-- /content -->
</div>
