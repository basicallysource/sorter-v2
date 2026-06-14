<script lang="ts">
	import { getBackendHttpBase } from '$lib/backend';
	import CameraSourcePreview from '$lib/components/CameraSourcePreview.svelte';
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
		FlipHorizontal,
		Pencil,
		Plus,
		RefreshCw,
		RotateCcw,
		SlidersHorizontal,
		X
	} from 'lucide-svelte';
	import StreamControlsOverlay from '$lib/components/StreamControlsOverlay.svelte';
	import { createEventDispatcher, onMount } from 'svelte';

	type Channel =
		| 'second'
		| 'third'
		| 'carousel'
		| 'classification_channel'
		| 'class_top'
		| 'class_bottom';
	type ArcChannel = 'second' | 'third' | 'classification_channel';
	type RectChannel = 'carousel' | 'class_top' | 'class_bottom';
	type Point = [number, number];
	// Secondary ("foreign") zone: a polygon this camera sees that belongs to
	// ANOTHER channel (e.g. the classification camera can see C3's exit). Drawn
	// and labeled here, shown on the live feed by perception — never acted on.
	type SecondaryZoneType = 'drop' | 'exit' | 'precise';
	type SecondaryZoneUI = {
		id: string;
		sourceChannel: number;
		zoneType: SecondaryZoneType;
		points: Point[];
	};
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
		exitOuterRadius: number;
		dropZone: ChordZone;
		exitZone: ChordZone;
		// Arc adjacent to the exit, full outer radius (no exit-style cut), own
		// independently draggable width. May be zero-width (the default for
		// configs that predate it) — then it contributes nothing.
		preciseZone: ChordZone;
		ringHandleAngleDeg: number | null;
	};
	type ChordZone = {
		startInnerAngle: number;
		startOuterAngle: number;
		endInnerAngle: number;
		endOuterAngle: number;
	};
	type ArcHandle =
		| 'center'
		| 'inner'
		| 'outer'
		| 'exitOuter'
		| 'dropStartInner'
		| 'dropStartOuter'
		| 'dropEndInner'
		| 'dropEndOuter'
		| 'exitStartInner'
		| 'exitStartOuter'
		| 'exitEndInner'
		| 'exitEndOuter'
		| 'preciseStartInner'
		| 'preciseStartOuter'
		| 'preciseEndInner'
		| 'preciseEndOuter'
		| 'dropStartEdge'
		| 'dropEndEdge'
		| 'dropRotate'
		| 'exitStartEdge'
		| 'exitEndEdge'
		| 'exitRotate'
		| 'preciseStartEdge'
		| 'preciseEndEdge'
		| 'preciseRotate';
	type ArcParamsPayload = {
		center: number[];
		inner_radius: number;
		outer_radius: number;
		exit_outer_radius?: number;
		drop_zone?: ChordZonePayload;
		exit_zone?: ChordZonePayload;
		precise_zone?: ChordZonePayload;
		ring_handle_angle_deg?: number | null;
		resolution?: number[];
	};
	type ChordZonePayload = {
		start_inner_angle?: number;
		start_outer_angle?: number;
		end_inner_angle?: number;
		end_outer_angle?: number;
		outer_radius?: number;
		start_angle?: number;
		end_angle?: number;
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
				kind: 'arc-inner' | 'arc-outer' | 'arc-exit-outer';
				channel: ArcChannel;
				start: Point;
				startAngleDeg: number;
				orig: ArcParams;
		  }
		| {
				kind:
					| 'arc-drop-start-inner'
					| 'arc-drop-start-outer'
					| 'arc-drop-end-inner'
					| 'arc-drop-end-outer'
					| 'arc-exit-start-inner'
					| 'arc-exit-start-outer'
					| 'arc-exit-end-inner'
					| 'arc-exit-end-outer'
					| 'arc-precise-start-inner'
					| 'arc-precise-start-outer'
					| 'arc-precise-end-inner'
					| 'arc-precise-end-outer';
				channel: ArcChannel;
				orig: ArcParams;
		  }
		| {
				kind:
					| 'arc-drop-start-edge'
					| 'arc-drop-end-edge'
					| 'arc-exit-start-edge'
					| 'arc-exit-end-edge'
					| 'arc-drop-rotate'
					| 'arc-exit-rotate'
					| 'arc-precise-start-edge'
					| 'arc-precise-end-edge'
					| 'arc-precise-rotate';
				channel: ArcChannel;
				orig: ArcParams;
				startPointerAngleDeg: number;
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

	const ARC_CHANNELS: ArcChannel[] = ['second', 'third', 'classification_channel'];
	const RECT_CHANNELS: RectChannel[] = ['carousel', 'class_top', 'class_bottom'];
	const TRANSPORT_CHANNELS: Channel[] = ['second', 'third', 'carousel', 'classification_channel'];
	const CLASSIFICATION_CHANNELS: Channel[] = ['class_top', 'class_bottom'];
	const DETECTION_CHANNELS: Channel[] = [
		'second',
		'third',
		'carousel',
		'classification_channel',
		'class_top',
		'class_bottom'
	];
	const ALL_CHANNELS: Channel[] = [...TRANSPORT_CHANNELS, ...CLASSIFICATION_CHANNELS];
	const HANDLE_HIT_RADIUS = 22;
	const HANDLE_DRAW_RADIUS = 9;
	const VERTEX_HIT_RADIUS = 18;
	const LABEL_EDGE_PADDING = 12;
	const ARC_SEGMENTS = 64;
	const MIN_ZONE_SPAN_DEG = 12;
	const MIN_ARC_THICKNESS = 20;
	const CHANNEL_SECTION_COUNT = 360;
	const CHANNEL_SECTION_DEG = 360 / CHANNEL_SECTION_COUNT;
	const HANDLE_CANVAS_PADDING = 20;
	const ALL_CAMERA_ROLES: CameraRole[] = [
		'c_channel_2',
		'c_channel_3',
		'carousel',
		'classification_channel',
		'classification_top',
		'classification_bottom'
	];

	const CHANNEL_LABELS: Record<Channel, string> = {
		second: 'C-Channel 2',
		third: 'C-Channel 3',
		carousel: 'Carousel',
		classification_channel: 'Classification C-Channel (C4)',
		class_top: 'Class. Top',
		class_bottom: 'Class. Bottom'
	};

	const CHANNEL_COLORS: Record<Channel, string> = {
		second: '#ffc800',
		third: '#00c8ff',
		carousel: '#00ff80',
		classification_channel: '#ff8a2a',
		class_top: '#ff6090',
		class_bottom: '#b060ff'
	};

	const CAMERA_FOR_CHANNEL: Record<Channel, CameraRole> = {
		second: 'c_channel_2',
		third: 'c_channel_3',
		carousel: 'carousel',
		classification_channel: 'classification_channel',
		class_top: 'classification_top',
		class_bottom: 'classification_bottom'
	};

	const ROLE_LABELS: Record<CameraRole, string> = {
		c_channel_2: 'C Channel 2',
		c_channel_3: 'C Channel 3',
		carousel: 'Carousel',
		classification_channel: 'Classification C-Channel (C4)',
		classification_top: 'Classification Top',
		classification_bottom: 'Classification Bottom'
	};

	const ROLE_SUPPORTS_URL: Record<CameraRole, boolean> = {
		c_channel_2: false,
		c_channel_3: false,
		carousel: true,
		classification_channel: true,
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
		},
		classification_channel: {
			drop: [44, 118],
			exit: [314, 350]
		}
	};

	const DROP_ZONE_COLOR = '#22c55e';
	const EXIT_ZONE_COLOR = '#ef4444';
	const PRECISE_ZONE_COLOR = '#a855f7';

	type ZoneHandle = Exclude<
		ArcHandle,
		| 'center'
		| 'inner'
		| 'outer'
		| 'exitOuter'
		| 'dropStartEdge'
		| 'dropEndEdge'
		| 'dropRotate'
		| 'exitStartEdge'
		| 'exitEndEdge'
		| 'exitRotate'
		| 'preciseStartEdge'
		| 'preciseEndEdge'
		| 'preciseRotate'
	>;
	type ZoneDragKind =
		| 'arc-drop-start-inner'
		| 'arc-drop-start-outer'
		| 'arc-drop-end-inner'
		| 'arc-drop-end-outer'
		| 'arc-exit-start-inner'
		| 'arc-exit-start-outer'
		| 'arc-exit-end-inner'
		| 'arc-exit-end-outer'
		| 'arc-precise-start-inner'
		| 'arc-precise-start-outer'
		| 'arc-precise-end-inner'
		| 'arc-precise-end-outer';

	const ZONE_HANDLE_TO_DRAG_KIND: Record<ZoneHandle, ZoneDragKind> = {
		dropStartInner: 'arc-drop-start-inner',
		dropStartOuter: 'arc-drop-start-outer',
		dropEndInner: 'arc-drop-end-inner',
		dropEndOuter: 'arc-drop-end-outer',
		exitStartInner: 'arc-exit-start-inner',
		exitStartOuter: 'arc-exit-start-outer',
		exitEndInner: 'arc-exit-end-inner',
		exitEndOuter: 'arc-exit-end-outer',
		preciseStartInner: 'arc-precise-start-inner',
		preciseStartOuter: 'arc-precise-start-outer',
		preciseEndInner: 'arc-precise-end-inner',
		preciseEndOuter: 'arc-precise-end-outer'
	};

	type ChordZoneField = 'startInnerAngle' | 'startOuterAngle' | 'endInnerAngle' | 'endOuterAngle';

	const DRAG_KIND_TO_ZONE_FIELD: Record<
		ZoneDragKind,
		[zoneKey: 'dropZone' | 'exitZone' | 'preciseZone', edgeField: ChordZoneField]
	> = {
		'arc-drop-start-inner': ['dropZone', 'startInnerAngle'],
		'arc-drop-start-outer': ['dropZone', 'startOuterAngle'],
		'arc-drop-end-inner': ['dropZone', 'endInnerAngle'],
		'arc-drop-end-outer': ['dropZone', 'endOuterAngle'],
		'arc-exit-start-inner': ['exitZone', 'startInnerAngle'],
		'arc-exit-start-outer': ['exitZone', 'startOuterAngle'],
		'arc-exit-end-inner': ['exitZone', 'endInnerAngle'],
		'arc-exit-end-outer': ['exitZone', 'endOuterAngle'],
		'arc-precise-start-inner': ['preciseZone', 'startInnerAngle'],
		'arc-precise-start-outer': ['preciseZone', 'startOuterAngle'],
		'arc-precise-end-inner': ['preciseZone', 'endInnerAngle'],
		'arc-precise-end-outer': ['preciseZone', 'endOuterAngle']
	};

	let {
		channels = ALL_CHANNELS,
		stepperKey = undefined,
		stepperEndstop = undefined,
		stepperLabel = undefined,
		stepperGearRatio = undefined,
		wizardMode = false
	}: {
		channels?: Channel[];
		stepperKey?: StepperKey;
		stepperEndstop?: EndstopConfig;
		stepperLabel?: string;
		stepperGearRatio?: number;
		wizardMode?: boolean;
	} = $props();

	const dispatch = createEventDispatcher<{ saved: void }>();

	const hasStepper = $derived(!!stepperKey);

	let currentChannel = $state<Channel>('second');
	let userPoints = $state<Record<Channel, number[][]>>({
		second: [],
		third: [],
		carousel: [],
		classification_channel: [],
		class_top: [],
		class_bottom: []
	});
	let arcParams = $state<Record<ArcChannel, ArcParams | null>>({
		second: null,
		third: null,
		classification_channel: null
	});
	let sectionZeroPoints = $state<Record<ArcChannel, Point | null>>({
		second: null,
		third: null,
		classification_channel: null
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
	// Secondary-zone editor state. Keyed by host storage key (e.g.
	// 'classification_channel'). Edited only while ``secondaryEditMode`` is on,
	// which short-circuits the primary zone pointer handlers.
	let secondaryZones = $state<Record<string, SecondaryZoneUI[]>>({});
	let secondaryEditMode = $state(false);
	let activeSecondaryId = $state<string | null>(null);
	let secondaryVertexDrag = $state<{ id: string; vertexIdx: number } | null>(null);
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
		classification_channel: null,
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

	const DEFAULT_CANVAS_W = 1920;
	const DEFAULT_CANVAS_H = 1080;
	let cameraResolutions = $state<Partial<Record<CameraRole, { width: number; height: number }>>>(
		{}
	);
	const CANVAS_W = $derived(
		cameraResolutions[CAMERA_FOR_CHANNEL[currentChannel]]?.width ?? DEFAULT_CANVAS_W
	);
	const CANVAS_H = $derived(
		cameraResolutions[CAMERA_FOR_CHANNEL[currentChannel]]?.height ?? DEFAULT_CANVAS_H
	);
	const EDITOR_BASELINE_WIDTH = 1280;
	const editorScale = $derived(Math.max(1, CANVAS_W / EDITOR_BASELINE_WIDTH));
	// The channel physically upstream of the current one, whose zone this camera
	// may be able to see. Only these expose the "add foreign zone" affordance.
	const previousSourceChannel = $derived(
		currentChannel === 'classification_channel' ? 3 : currentChannel === 'third' ? 2 : null
	);
	const handleHitRadius = $derived(HANDLE_HIT_RADIUS * editorScale);
	const vertexHitRadius = $derived(VERTEX_HIT_RADIUS * editorScale);
	const handleCanvasPadding = $derived(HANDLE_CANVAS_PADDING * editorScale);
	const exitOuterHandlePadding = $derived(Math.max(handleCanvasPadding, 58 * editorScale));
	const labelEdgePadding = $derived(LABEL_EDGE_PADDING * editorScale);
	const RING_HANDLE_CLEARANCE_DEG = 8;
	const RING_HANDLE_SNAP_DEG = 10;

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
		if (channel === 'second' || channel === 'third' || channel === 'classification_channel') {
			return 'feeder';
		}
		if (channel === 'carousel') return 'carousel';
		return 'classification';
	}

	function detectionCameraForChannel(
		channel: Channel
	): 'top' | 'bottom' | 'c_channel_2' | 'c_channel_3' | 'carousel' | 'classification_channel' {
		if (channel === 'second') return 'c_channel_2';
		if (channel === 'third') return 'c_channel_3';
		// C4 in the classification_channel topology uses the "carousel" feeder
		// detection role on the backend — the camera is labelled
		// classification_channel in cameras/config but detection-config lives
		// under role=carousel.
		if (channel === 'classification_channel') return 'carousel';
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

	function clampSpan(
		startAngle: number,
		endAngle: number
	): { startAngle: number; endAngle: number } {
		const next = {
			startAngle: normalizeAngle(startAngle),
			endAngle: normalizeAngle(endAngle)
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

	function clampZone(zone: ChordZone): ChordZone {
		const outer = clampSpan(zone.startOuterAngle, zone.endOuterAngle);
		const inner = clampSpan(zone.startInnerAngle, zone.endInnerAngle);
		return {
			startOuterAngle: outer.startAngle,
			endOuterAngle: outer.endAngle,
			startInnerAngle: inner.startAngle,
			endInnerAngle: inner.endAngle
		};
	}

	function radialChordZone(startAngle: number, endAngle: number): ChordZone {
		return clampZone({
			startOuterAngle: startAngle,
			startInnerAngle: startAngle,
			endOuterAngle: endAngle,
			endInnerAngle: endAngle
		});
	}

	function copyChordZone(zone: ChordZone): ChordZone {
		return {
			startInnerAngle: zone.startInnerAngle,
			startOuterAngle: zone.startOuterAngle,
			endInnerAngle: zone.endInnerAngle,
			endOuterAngle: zone.endOuterAngle
		};
	}

	// Unlike clampZone, the precise zone is allowed to be zero-width (its
	// migration default), so it has no minimum span — only a maximum.
	function clampPreciseZone(zone: ChordZone): ChordZone {
		const startOuter = normalizeAngle(zone.startOuterAngle);
		const startInner = normalizeAngle(zone.startInnerAngle);
		const spanOuter = Math.min(
			(normalizeAngle(zone.endOuterAngle) - startOuter + 360) % 360,
			360 - MIN_ZONE_SPAN_DEG
		);
		const spanInner = Math.min(
			(normalizeAngle(zone.endInnerAngle) - startInner + 360) % 360,
			360 - MIN_ZONE_SPAN_DEG
		);
		return {
			startOuterAngle: startOuter,
			endOuterAngle: normalizeAngle(startOuter + spanOuter),
			startInnerAngle: startInner,
			endInnerAngle: normalizeAngle(startInner + spanInner)
		};
	}

	// A zero-width precise zone anchored at the exit's CCW (approach) edge —
	// the default when none is configured. Forward travel increases angle, so
	// the CCW side is the exit's start edge.
	function defaultPreciseZone(exitZone: ChordZone): ChordZone {
		return {
			startOuterAngle: normalizeAngle(exitZone.startOuterAngle),
			endOuterAngle: normalizeAngle(exitZone.startOuterAngle),
			startInnerAngle: normalizeAngle(exitZone.startInnerAngle),
			endInnerAngle: normalizeAngle(exitZone.startInnerAngle)
		};
	}

	// Glue the precise zone to the exit: it shares the exit's adjacent edge
	// (no gap), and sits entirely on one side of it (no overlap). Only the
	// precise zone's far edge is free; the shared edge always tracks the exit.
	// Applied in setArc so any edit — to either zone — re-establishes the bond.
	function gluePreciseToExit(exit: ChordZone, precise: ChordZone): ChordZone {
		const onCcwSide =
			angularDistance(precise.endOuterAngle, exit.startOuterAngle) <=
			angularDistance(precise.startOuterAngle, exit.endOuterAngle);
		if (onCcwSide) {
			// Just before the exit: precise's END edge is shared with exit's START.
			return {
				startOuterAngle: precise.startOuterAngle,
				startInnerAngle: precise.startInnerAngle,
				endOuterAngle: normalizeAngle(exit.startOuterAngle),
				endInnerAngle: normalizeAngle(exit.startInnerAngle)
			};
		}
		// Just after the exit: precise's START edge is shared with exit's END.
		return {
			startOuterAngle: normalizeAngle(exit.endOuterAngle),
			startInnerAngle: normalizeAngle(exit.endInnerAngle),
			endOuterAngle: precise.endOuterAngle,
			endInnerAngle: precise.endInnerAngle
		};
	}

	function copyArcParams(params: ArcParams): ArcParams {
		return {
			center: [params.center[0], params.center[1]],
			innerRadius: params.innerRadius,
			outerRadius: params.outerRadius,
			exitOuterRadius: params.exitOuterRadius,
			dropZone: copyChordZone(params.dropZone),
			exitZone: copyChordZone(params.exitZone),
			preciseZone: copyChordZone(params.preciseZone),
			ringHandleAngleDeg: params.ringHandleAngleDeg
		};
	}

	function normalizeArcParamsForChannel(_channel: ArcChannel, params: ArcParams): ArcParams {
		const innerRadius = Math.max(10, params.innerRadius);
		const outerRadius = Math.max(innerRadius + MIN_ARC_THICKNESS, params.outerRadius);
		const rawExitOuterRadius =
			typeof params.exitOuterRadius === 'number' && Number.isFinite(params.exitOuterRadius)
				? params.exitOuterRadius
				: outerRadius;
		const exitOuterRadius = clamp(rawExitOuterRadius, innerRadius + MIN_ARC_THICKNESS, outerRadius);
		return {
			center: [params.center[0], params.center[1]],
			innerRadius,
			outerRadius,
			exitOuterRadius,
			dropZone: clampZone(params.dropZone),
			exitZone: clampZone(params.exitZone),
			preciseZone: clampPreciseZone(params.preciseZone),
			ringHandleAngleDeg:
				typeof params.ringHandleAngleDeg === 'number'
					? normalizeAngle(params.ringHandleAngleDeg)
					: null
		};
	}

	function sectionRangeToZone(
		channel: ArcChannel,
		zoneKey: 'drop' | 'exit',
		sectionZeroAngle = 0
	): ChordZone | null {
		const range = LEGACY_ZONE_SECTION_RANGES[channel][zoneKey];
		if (!range) return null;
		const [startSection, endSection] = range;
		return radialChordZone(
			normalizeAngle(sectionZeroAngle + startSection * CHANNEL_SECTION_DEG),
			normalizeAngle(sectionZeroAngle + endSection * CHANNEL_SECTION_DEG)
		);
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
				classification_channel: [],
				class_top: [],
				class_bottom: []
			},
			arcParams: {
				second: null,
				third: null,
				classification_channel: null
			},
			sectionZeroPoints: {
				second: null,
				third: null,
				classification_channel: null
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
				classification_channel: clonePointList(userPoints.classification_channel),
				class_top: clonePointList(userPoints.class_top),
				class_bottom: clonePointList(userPoints.class_bottom)
			},
			arcParams: {
				second: arcParams.second ? copyArcParams(arcParams.second) : null,
				third: arcParams.third ? copyArcParams(arcParams.third) : null,
				classification_channel: arcParams.classification_channel
					? copyArcParams(arcParams.classification_channel)
					: null
			},
			sectionZeroPoints: {
				second: clonePoint(sectionZeroPoints.second),
				third: clonePoint(sectionZeroPoints.third),
				classification_channel: clonePoint(sectionZeroPoints.classification_channel)
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
			classification_channel: clonePointList(snapshot.userPoints.classification_channel),
			class_top: clonePointList(snapshot.userPoints.class_top),
			class_bottom: clonePointList(snapshot.userPoints.class_bottom)
		};
		arcParams = {
			second: snapshot.arcParams.second ? copyArcParams(snapshot.arcParams.second) : null,
			third: snapshot.arcParams.third ? copyArcParams(snapshot.arcParams.third) : null,
			classification_channel: snapshot.arcParams.classification_channel
				? copyArcParams(snapshot.arcParams.classification_channel)
				: null
		};
		sectionZeroPoints = {
			second: clonePoint(snapshot.sectionZeroPoints.second),
			third: clonePoint(snapshot.sectionZeroPoints.third),
			classification_channel: clonePoint(snapshot.sectionZeroPoints.classification_channel)
		};
		quadParams = {
			carousel: snapshot.quadParams.carousel ? copyQuadParams(snapshot.quadParams.carousel) : null,
			class_top: snapshot.quadParams.class_top
				? copyQuadParams(snapshot.quadParams.class_top)
				: null,
			class_bottom: snapshot.quadParams.class_bottom
				? copyQuadParams(snapshot.quadParams.class_bottom)
				: null
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

	function previewViewportStyle(channel: Channel): string {
		const imageSize = previewImageSizeByRole[currentRole(channel)];
		if (!wizardMode && !editingZone && previewCropped && imageSize) {
			return `aspect-ratio:${imageSize.width}/${imageSize.height};`;
		}
		return '';
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
		exitSecondaryEditMode();
		activeSecondaryId = null;
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
		return `${getBackendHttpBase()}/api/cameras/stream/${index}`;
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
	): Pick<ArcParams, 'dropZone' | 'exitZone' | 'preciseZone'> {
		const exitZone =
			sectionRangeToZone(channel, 'exit', sectionZeroAngle) ?? radialChordZone(300, 340);
		return {
			dropZone: sectionRangeToZone(channel, 'drop', sectionZeroAngle) ?? radialChordZone(40, 120),
			exitZone,
			preciseZone: defaultPreciseZone(exitZone)
		};
	}

	function defaultArcParams(channel: ArcChannel): ArcParams {
		const center: Point =
			channel === 'second'
				? [CANVAS_W * 0.46, CANVAS_H * 0.55]
				: channel === 'third'
					? [CANVAS_W * 0.54, CANVAS_H * 0.55]
					: [CANVAS_W * 0.52, CANVAS_H * 0.54];
		const innerRadius = channel === 'classification_channel' ? 210 : 180;
		const outerRadius = channel === 'classification_channel' ? 390 : 360;
		return normalizeArcParamsForChannel(channel, {
			center,
			innerRadius,
			outerRadius,
			exitOuterRadius: outerRadius,
			...defaultZoneLayout(channel),
			ringHandleAngleDeg: null
		});
	}

	function serializeChordZone(zone: ChordZone): ChordZonePayload {
		return {
			start_inner_angle: zone.startInnerAngle,
			start_outer_angle: zone.startOuterAngle,
			end_inner_angle: zone.endInnerAngle,
			end_outer_angle: zone.endOuterAngle,
			start_angle: zone.startOuterAngle,
			end_angle: zone.endOuterAngle
		};
	}

	function serializeArcParams(params: ArcParams, resolution: [number, number]): ArcParamsPayload {
		const exitZone = serializeChordZone(params.exitZone);
		exitZone.outer_radius = Math.round(params.exitOuterRadius);
		return {
			center: [Math.round(params.center[0]), Math.round(params.center[1])],
			inner_radius: Math.round(params.innerRadius),
			outer_radius: Math.round(params.outerRadius),
			exit_outer_radius: Math.round(params.exitOuterRadius),
			drop_zone: serializeChordZone(params.dropZone),
			exit_zone: exitZone,
			precise_zone: serializeChordZone(params.preciseZone),
			ring_handle_angle_deg:
				typeof params.ringHandleAngleDeg === 'number' ? params.ringHandleAngleDeg : null,
			resolution
		};
	}

	function parseChordZone(raw: unknown): ChordZone | null {
		if (!raw || typeof raw !== 'object') return null;
		const r = raw as ChordZonePayload;
		if (
			typeof r.start_inner_angle === 'number' &&
			typeof r.start_outer_angle === 'number' &&
			typeof r.end_inner_angle === 'number' &&
			typeof r.end_outer_angle === 'number'
		) {
			return clampZone({
				startInnerAngle: r.start_inner_angle,
				startOuterAngle: r.start_outer_angle,
				endInnerAngle: r.end_inner_angle,
				endOuterAngle: r.end_outer_angle
			});
		}
		if (typeof r.start_angle === 'number' && typeof r.end_angle === 'number') {
			return radialChordZone(r.start_angle, r.end_angle);
		}
		return null;
	}

	// Like parseChordZone but allows a zero-width result (no minimum span), so a
	// saved zero-width precise zone round-trips instead of being inflated.
	function parsePreciseChordZone(raw: unknown): ChordZone | null {
		if (!raw || typeof raw !== 'object') return null;
		const r = raw as ChordZonePayload;
		if (
			typeof r.start_inner_angle === 'number' &&
			typeof r.start_outer_angle === 'number' &&
			typeof r.end_inner_angle === 'number' &&
			typeof r.end_outer_angle === 'number'
		) {
			return clampPreciseZone({
				startInnerAngle: r.start_inner_angle,
				startOuterAngle: r.start_outer_angle,
				endInnerAngle: r.end_inner_angle,
				endOuterAngle: r.end_outer_angle
			});
		}
		if (typeof r.start_angle === 'number' && typeof r.end_angle === 'number') {
			return clampPreciseZone({
				startOuterAngle: r.start_angle,
				startInnerAngle: r.start_angle,
				endOuterAngle: r.end_angle,
				endInnerAngle: r.end_angle
			});
		}
		return null;
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
			parseChordZone((raw as ArcParamsPayload).drop_zone) ??
			sectionRangeToZone(channel, 'drop', sectionZeroAngle) ??
			radialChordZone(40, 120);
		const exitZonePayload = (raw as ArcParamsPayload).exit_zone;
		const exitZone =
			parseChordZone(exitZonePayload) ??
			sectionRangeToZone(channel, 'exit', sectionZeroAngle) ??
			radialChordZone(300, 340);
		const exitOuterRaw = (raw as ArcParamsPayload).exit_outer_radius;
		const nestedExitOuterRaw =
			exitZonePayload && typeof exitZonePayload === 'object'
				? (exitZonePayload as ChordZonePayload).outer_radius
				: undefined;
		const exitOuterRadius =
			typeof exitOuterRaw === 'number' && Number.isFinite(exitOuterRaw)
				? exitOuterRaw
				: typeof nestedExitOuterRaw === 'number' && Number.isFinite(nestedExitOuterRaw)
					? nestedExitOuterRaw
					: outerRadius;
		const preciseZone =
			parsePreciseChordZone((raw as ArcParamsPayload).precise_zone) ?? defaultPreciseZone(exitZone);
		const ringHandleRaw = (raw as ArcParamsPayload).ring_handle_angle_deg;
		const ringHandleAngleDeg =
			typeof ringHandleRaw === 'number' && Number.isFinite(ringHandleRaw) ? ringHandleRaw : null;
		return normalizeArcParamsForChannel(channel, {
			center: [center[0], center[1]],
			innerRadius: Math.max(10, innerRadius),
			outerRadius: Math.max(innerRadius + MIN_ARC_THICKNESS, outerRadius),
			exitOuterRadius,
			dropZone,
			exitZone,
			preciseZone,
			ringHandleAngleDeg
		});
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
		return normalizeArcParamsForChannel(channel, {
			center: [center[0], center[1]],
			innerRadius,
			outerRadius,
			exitOuterRadius: outerRadius,
			...defaultZoneLayout(channel, sectionZeroAngle),
			ringHandleAngleDeg: null
		});
	}

	function zoneMidAngle(zone: ChordZone): number {
		return normalizeAngle(
			zone.startOuterAngle + positiveAngleSpan(zone.startOuterAngle, zone.endOuterAngle) / 2
		);
	}

	function angleWithinZone(angleDeg: number, zone: ChordZone): boolean {
		const span = positiveAngleSpan(zone.startOuterAngle, zone.endOuterAngle);
		const rel = (normalizeAngle(angleDeg) - normalizeAngle(zone.startOuterAngle) + 360) % 360;
		return rel <= span;
	}

	function outerRadiusForAngle(params: ArcParams, angleDeg: number): number {
		return params.exitOuterRadius < params.outerRadius && angleWithinZone(angleDeg, params.exitZone)
			? params.exitOuterRadius
			: params.outerRadius;
	}

	function angleMatches(a: number, b: number): boolean {
		return angularDistance(a, b) < 0.0001;
	}

	function normalizeAngleAtOrAfter(angleDeg: number, floorAngle: number): number {
		let angle = normalizeAngle(angleDeg);
		while (angle < floorAngle - 0.0001) {
			angle += 360;
		}
		return angle;
	}

	function addBoundaryAngleWithin(
		angles: Set<number>,
		boundaryAngle: number,
		startAngle: number,
		endAngle: number
	) {
		let angle = normalizeAngleAtOrAfter(boundaryAngle, startAngle);
		while (angle <= endAngle + 0.0001) {
			angles.add(angle);
			angle += 360;
		}
	}

	function addOuterBoundaryPoint(points: Point[], params: ArcParams, angleDeg: number) {
		const normalizedAngle = normalizeAngle(angleDeg);
		const hasExitCut = params.exitOuterRadius < params.outerRadius - 0.5;
		if (hasExitCut && angleMatches(normalizedAngle, params.exitZone.startOuterAngle)) {
			points.push(polarPoint(params.center, params.outerRadius, normalizedAngle));
			points.push(polarPoint(params.center, params.exitOuterRadius, normalizedAngle));
			return;
		}
		if (hasExitCut && angleMatches(normalizedAngle, params.exitZone.endOuterAngle)) {
			points.push(polarPoint(params.center, params.exitOuterRadius, normalizedAngle));
			points.push(polarPoint(params.center, params.outerRadius, normalizedAngle));
			return;
		}
		points.push(
			polarPoint(params.center, outerRadiusForAngle(params, normalizedAngle), normalizedAngle)
		);
	}

	function addCropBoundaryPoint(points: Point[], params: ArcParams, angleDeg: number) {
		const normalizedAngle = normalizeAngle(angleDeg);
		const hasExitCut = params.exitOuterRadius < params.outerRadius - 0.5;
		if (hasExitCut && angleMatches(normalizedAngle, params.exitZone.startOuterAngle)) {
			points.push(polarPoint(params.center, params.outerRadius, normalizedAngle));
			points.push(polarPoint(params.center, params.exitOuterRadius, normalizedAngle));
			return;
		}
		if (hasExitCut && angleMatches(normalizedAngle, params.exitZone.endOuterAngle)) {
			points.push(polarPoint(params.center, params.exitOuterRadius, normalizedAngle));
			return;
		}
		points.push(
			polarPoint(params.center, outerRadiusForAngle(params, normalizedAngle), normalizedAngle)
		);
	}

	function buildOuterBoundaryPoints(params: ArcParams, segments = ARC_SEGMENTS): Point[] {
		const angles = new Set<number>();
		for (let i = 0; i < segments; i++) {
			angles.add(normalizeAngle((i / segments) * 360));
		}
		angles.add(normalizeAngle(params.exitZone.startOuterAngle));
		angles.add(normalizeAngle(params.exitZone.endOuterAngle));
		const pts: Point[] = [];
		for (const angle of [...angles].sort((a, b) => a - b)) {
			addOuterBoundaryPoint(pts, params, angle);
		}
		return pts;
	}

	function buildOuterArcPoints(
		params: ArcParams,
		startAngle: number,
		span: number,
		segments: number
	): Point[] {
		const start = startAngle;
		const end = startAngle + span;
		const angles = new Set<number>();
		for (let i = 0; i <= segments; i++) {
			angles.add(start + (span * i) / segments);
		}
		addBoundaryAngleWithin(angles, params.exitZone.startOuterAngle, start, end);
		addBoundaryAngleWithin(angles, params.exitZone.endOuterAngle, start, end);
		const pts: Point[] = [];
		for (const angle of [...angles].sort((a, b) => a - b)) {
			addCropBoundaryPoint(pts, params, angle);
		}
		return pts;
	}

	function buildZonePolygon(
		params: ArcParams,
		zone: ChordZone,
		outerRadius = params.outerRadius
	): Point[] {
		const outerSpan = positiveAngleSpan(zone.startOuterAngle, zone.endOuterAngle);
		const innerSpan = positiveAngleSpan(zone.startInnerAngle, zone.endInnerAngle);
		const outerSegments = Math.max(8, Math.round((outerSpan / 360) * ARC_SEGMENTS));
		const innerSegments = Math.max(8, Math.round((innerSpan / 360) * ARC_SEGMENTS));
		const pts: Point[] = [];

		for (let i = 0; i <= outerSegments; i++) {
			const angle = zone.startOuterAngle + (outerSpan * i) / outerSegments;
			pts.push(polarPoint(params.center, outerRadius, angle));
		}
		for (let i = innerSegments; i >= 0; i--) {
			const angle = zone.startInnerAngle + (innerSpan * i) / innerSegments;
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

	function constrainHandlePoint(point: Point, pad = handleCanvasPadding): Point {
		return [clamp(point[0], pad, CANVAS_W - pad), clamp(point[1], pad, CANVAS_H - pad)];
	}

	function buildRingStoragePoints(params: ArcParams): Point[] {
		return [
			...buildOuterBoundaryPoints(params),
			...buildCirclePoints(params.center, params.innerRadius).reverse()
		];
	}

	function buildCropPolygon(params: ArcParams, ccw = false): Point[] {
		const { center, innerRadius, dropZone, exitZone } = params;
		// Clockwise keeps drop-start -> exit-end. Counterclockwise (the carousel)
		// keeps exit-start -> drop-end — the arc the piece travels going the other
		// way — so the cropped gap lands on the side it never crosses.
		const outerFrom = ccw ? exitZone.startOuterAngle : dropZone.startOuterAngle;
		const outerTo = ccw ? dropZone.endOuterAngle : exitZone.endOuterAngle;
		const innerFrom = ccw ? exitZone.startInnerAngle : dropZone.startInnerAngle;
		const innerTo = ccw ? dropZone.endInnerAngle : exitZone.endInnerAngle;
		const outerSpan = positiveAngleSpan(outerFrom, outerTo);
		const innerSpan = positiveAngleSpan(innerFrom, innerTo);
		const outerSegments = Math.max(16, Math.round((outerSpan / 360) * ARC_SEGMENTS));
		const innerSegments = Math.max(16, Math.round((innerSpan / 360) * ARC_SEGMENTS));
		const pts: Point[] = buildOuterArcPoints(params, outerFrom, outerSpan, outerSegments);
		for (let i = innerSegments; i >= 0; i--) {
			const angle = innerFrom + (innerSpan * i) / innerSegments;
			pts.push(polarPoint(center, innerRadius, angle));
		}
		return pts;
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
			const xi = pts[i][0],
				yi = pts[i][1];
			const xj = pts[j][0],
				yj = pts[j][1];
			if (
				yi > point[1] !== yj > point[1] &&
				point[0] < ((xj - xi) * (point[1] - yi)) / (yj - yi) + xi
			) {
				inside = !inside;
			}
		}
		return inside;
	}

	function hitQuadCorner(channel: RectChannel, point: Point): QuadHandle | null {
		const q = quadParams[channel];
		if (!q) return null;
		for (let i = 0; i < 4; i++) {
			if (pointDistance(point, q.corners[i]) <= handleHitRadius) return i as QuadHandle;
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

	function ringHandleOccupiedAngles(params: ArcParams): number[] {
		return [
			params.dropZone.startOuterAngle,
			params.dropZone.endOuterAngle,
			params.exitZone.startOuterAngle,
			params.exitZone.endOuterAngle
		];
	}

	function autoRingHandleAngle(params: ArcParams): number {
		const ringHandleCandidates = Array.from({ length: 12 }, (_, index) => index * 30);
		const occupiedAngles = ringHandleOccupiedAngles(params);
		return (
			ringHandleCandidates.reduce(
				(best, candidate) =>
					Math.min(...occupiedAngles.map((angle) => angularDistance(candidate, angle))) >
					Math.min(...occupiedAngles.map((angle) => angularDistance(best, angle)))
						? candidate
						: best,
				270
			) ?? 270
		);
	}

	function clampRingHandleAngle(params: ArcParams, desiredDeg: number): number {
		const occupiedAngles = ringHandleOccupiedAngles(params);
		let current = normalizeAngle(desiredDeg);
		for (let pass = 0; pass < 4; pass++) {
			let nearest: { angle: number; delta: number } | null = null;
			for (const edge of occupiedAngles) {
				const edgeNorm = normalizeAngle(edge);
				let delta = current - edgeNorm;
				delta = ((delta + 540) % 360) - 180;
				if (Math.abs(delta) < RING_HANDLE_CLEARANCE_DEG) {
					if (!nearest || Math.abs(delta) < Math.abs(nearest.delta)) {
						nearest = { angle: edgeNorm, delta };
					}
				}
			}
			if (!nearest) return current;
			const sign = nearest.delta >= 0 ? 1 : -1;
			current = normalizeAngle(nearest.angle + sign * RING_HANDLE_CLEARANCE_DEG);
		}
		return current;
	}

	function effectiveRingHandleAngle(params: ArcParams): number {
		if (typeof params.ringHandleAngleDeg === 'number') {
			return clampRingHandleAngle(params, params.ringHandleAngleDeg);
		}
		return autoRingHandleAngle(params);
	}

	function innerHandlePoint(params: ArcParams, angleDeg: number): Point {
		return constrainHandlePoint(polarPoint(params.center, params.innerRadius, angleDeg));
	}

	function outerHandlePoint(
		params: ArcParams,
		angleDeg: number,
		radius = params.outerRadius,
		pad = handleCanvasPadding
	): Point {
		return constrainHandlePoint(polarPoint(params.center, radius, angleDeg), pad);
	}

	function midpoint(a: Point, b: Point): Point {
		return [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2];
	}

	function getArcHandles(channel: ArcChannel): Record<ArcHandle, Point> | null {
		const params = arcParams[channel];
		if (!params) return null;
		const ringHandleAngle = effectiveRingHandleAngle(params);
		const dropStartInner = innerHandlePoint(params, params.dropZone.startInnerAngle);
		const dropStartOuter = outerHandlePoint(params, params.dropZone.startOuterAngle);
		const dropEndInner = innerHandlePoint(params, params.dropZone.endInnerAngle);
		const dropEndOuter = outerHandlePoint(params, params.dropZone.endOuterAngle);
		const exitStartInner = innerHandlePoint(params, params.exitZone.startInnerAngle);
		const exitStartOuter = outerHandlePoint(
			params,
			params.exitZone.startOuterAngle,
			params.exitOuterRadius
		);
		const exitEndInner = innerHandlePoint(params, params.exitZone.endInnerAngle);
		const exitEndOuter = outerHandlePoint(
			params,
			params.exitZone.endOuterAngle,
			params.exitOuterRadius
		);
		// Precise zone sits at full outer radius (no exit cut).
		const preciseStartInner = innerHandlePoint(params, params.preciseZone.startInnerAngle);
		const preciseStartOuter = outerHandlePoint(params, params.preciseZone.startOuterAngle);
		const preciseEndInner = innerHandlePoint(params, params.preciseZone.endInnerAngle);
		const preciseEndOuter = outerHandlePoint(params, params.preciseZone.endOuterAngle);
		const rotateOffset = 28 * editorScale;
		const dropRotate = outerHandlePoint(
			params,
			zoneMidAngle(params.dropZone),
			params.outerRadius + rotateOffset,
			exitOuterHandlePadding
		);
		const exitRotate = outerHandlePoint(
			params,
			zoneMidAngle(params.exitZone),
			params.outerRadius + rotateOffset,
			exitOuterHandlePadding
		);
		const preciseRotate = outerHandlePoint(
			params,
			zoneMidAngle(params.preciseZone),
			params.outerRadius + rotateOffset,
			exitOuterHandlePadding
		);
		return {
			center: [params.center[0], params.center[1]],
			inner: polarPoint(params.center, params.innerRadius, ringHandleAngle),
			outer: polarPoint(params.center, params.outerRadius, ringHandleAngle),
			exitOuter: outerHandlePoint(
				params,
				zoneMidAngle(params.exitZone),
				params.exitOuterRadius,
				exitOuterHandlePadding
			),
			dropStartInner,
			dropStartOuter,
			dropEndInner,
			dropEndOuter,
			exitStartInner,
			exitStartOuter,
			exitEndInner,
			exitEndOuter,
			preciseStartInner,
			preciseStartOuter,
			preciseEndInner,
			preciseEndOuter,
			dropStartEdge: midpoint(dropStartInner, dropStartOuter),
			dropEndEdge: midpoint(dropEndInner, dropEndOuter),
			dropRotate,
			exitStartEdge: midpoint(exitStartInner, exitStartOuter),
			exitEndEdge: midpoint(exitEndInner, exitEndOuter),
			exitRotate,
			preciseStartEdge: midpoint(preciseStartInner, preciseStartOuter),
			preciseEndEdge: midpoint(preciseEndInner, preciseEndOuter),
			preciseRotate
		};
	}

	function arcEditableHandles(_channel: ArcChannel): ArcHandle[] {
		// Drop Start is intentionally a *radial* boundary — its inner angle is
		// locked to the outer angle, so we only expose the outer handle. This
		// guarantees a clean line from the channel center to the outer circle
		// at the drop-zone entry, matching the physical guide rail.
		return [
			'dropStartEdge',
			'dropEndEdge',
			'exitStartEdge',
			'exitEndEdge',
			// exitOuter (radius) shares the exit mid-angle with exitRotate and can
			// stack on it (both clamp to the canvas edge when the zone is near the
			// frame top). Check the radius handle FIRST so a click on the overlap
			// drags the radius; pulling it inward then separates the two.
			'exitOuter',
			'dropRotate',
			'exitRotate',
			'dropStartOuter',
			'dropEndInner',
			'dropEndOuter',
			'exitStartInner',
			'exitStartOuter',
			'exitEndInner',
			'exitEndOuter',
			'preciseStartEdge',
			'preciseEndEdge',
			'preciseRotate',
			'preciseStartInner',
			'preciseStartOuter',
			'preciseEndInner',
			'preciseEndOuter',
			'outer',
			'inner',
			'center'
		];
	}

	function setArc(channel: ArcChannel, next: ArcParams) {
		const innerRadius = Math.max(
			10,
			Math.min(next.innerRadius, next.outerRadius - MIN_ARC_THICKNESS)
		);
		const outerRadius = Math.max(innerRadius + MIN_ARC_THICKNESS, next.outerRadius);
		const exitOuterRadius = clamp(
			next.exitOuterRadius,
			innerRadius + MIN_ARC_THICKNESS,
			outerRadius
		);
		const clamped = normalizeArcParamsForChannel(channel, {
			...next,
			innerRadius,
			outerRadius,
			exitOuterRadius
		});
		clamped.preciseZone = clampPreciseZone(
			gluePreciseToExit(clamped.exitZone, clamped.preciseZone)
		);
		arcParams[channel] = clamped;
	}

	// Move the precise zone to the opposite adjacent side of the exit, keeping
	// its width. Forward travel increases angle: the CCW/approach side sits
	// just before the exit (precise ends where exit starts); the CW/far side
	// sits just after it (precise starts where exit ends).
	function flipPreciseSide(channel: ArcChannel) {
		const params = arcParams[channel];
		if (!params) return;
		const exit = params.exitZone;
		const precise = params.preciseZone;
		const widthOuter =
			(normalizeAngle(precise.endOuterAngle) - normalizeAngle(precise.startOuterAngle) + 360) % 360;
		const widthInner =
			(normalizeAngle(precise.endInnerAngle) - normalizeAngle(precise.startInnerAngle) + 360) % 360;
		const onCcwSide =
			angularDistance(precise.endOuterAngle, exit.startOuterAngle) <=
			angularDistance(precise.startOuterAngle, exit.endOuterAngle);
		const next: ChordZone = onCcwSide
			? {
					startOuterAngle: normalizeAngle(exit.endOuterAngle),
					endOuterAngle: normalizeAngle(exit.endOuterAngle + widthOuter),
					startInnerAngle: normalizeAngle(exit.endInnerAngle),
					endInnerAngle: normalizeAngle(exit.endInnerAngle + widthInner)
				}
			: {
					startOuterAngle: normalizeAngle(exit.startOuterAngle - widthOuter),
					endOuterAngle: normalizeAngle(exit.startOuterAngle),
					startInnerAngle: normalizeAngle(exit.startInnerAngle - widthInner),
					endInnerAngle: normalizeAngle(exit.startInnerAngle)
				};
		setArc(channel, { ...params, preciseZone: next });
	}

	function streamSrc(channel: Channel): string {
		const role = CAMERA_FOR_CHANNEL[channel];
		// The feed URL is intentionally independent of `editingZone`: entering or
		// leaving zone-edit mode must not change the stream, so the single MJPEG
		// connection (and its `<img>`) survives the toggle. A fresh connection
		// opened during a camera hiccup has no frame to show and goes black; a
		// persistent one rides the hiccup on its last frame. `beginEditing()`
		// forces crop off so the editor canvas always maps to the full frame.
		const annotated = previewAnnotated;
		const dashboard = previewCropped;
		const colorCorrect = previewColorCorrect;
		const showRegions = previewCropped && previewZones;
		const params = new URLSearchParams({
			annotated: annotated ? '1' : '0',
			layer: annotated ? 'annotated' : 'raw',
			dashboard: dashboard ? '1' : '0',
			color_correct: colorCorrect ? '1' : '0',
			show_regions: showRegions ? '1' : '0'
		});
		return `${getBackendHttpBase()}/api/cameras/feed/${encodeURIComponent(role)}?${params.toString()}`;
	}

	function feedInstanceKey(channel: Channel): string {
		const assignment = currentAssignment(channel);
		const zonesMode = previewCropped ? (previewZones ? 'z' : 'nz') : 'local-zones';
		// No `editingZone` term here — the `{#key}` block must not remount the
		// feed `<img>` when zone editing toggles. Remounting tears down a working
		// MJPEG connection; see streamSrc() for why that causes the black screen.
		const mode = `${previewAnnotated ? 'annot' : 'raw'}-${previewColorCorrect ? 'cc' : 'nocc'}-${previewCropped ? 'crop' : 'full'}-${zonesMode}`;
		return `${currentRole(channel)}::${assignment === null ? 'none' : String(assignment)}::${mode}::${feedRevision}`;
	}

	function channelStorageKey(channel: Channel): string {
		if (channel === 'second') return 'second_channel';
		if (channel === 'third') return 'third_channel';
		if (channel === 'classification_channel') return 'classification_channel';
		return channel;
	}

	async function loadCameraConfig() {
		try {
			const res = await fetch(`${getBackendHttpBase()}/api/cameras/config`);
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

	function pickRoleResolution(payload: unknown): { width: number; height: number } | null {
		if (!payload || typeof payload !== 'object') return null;
		const sources = [
			(payload as Record<string, unknown>).live,
			(payload as Record<string, unknown>).current
		];
		for (const source of sources) {
			if (!source || typeof source !== 'object') continue;
			const width = Number((source as Record<string, unknown>).width);
			const height = Number((source as Record<string, unknown>).height);
			if (Number.isFinite(width) && Number.isFinite(height) && width > 0 && height > 0) {
				return { width: Math.round(width), height: Math.round(height) };
			}
		}
		return null;
	}

	async function loadCameraResolutions(): Promise<void> {
		const results = await Promise.all(
			ALL_CAMERA_ROLES.map(async (role) => {
				try {
					const res = await fetch(`${getBackendHttpBase()}/api/cameras/capture-modes/${role}`, {
						cache: 'no-store'
					});
					if (!res.ok) return [role, null] as const;
					const payload = await res.json();
					return [role, pickRoleResolution(payload)] as const;
				} catch {
					return [role, null] as const;
				}
			})
		);
		const next: Partial<Record<CameraRole, { width: number; height: number }>> = {};
		for (const [role, dims] of results) {
			if (dims) next[role] = dims;
		}
		cameraResolutions = next;
	}

	function parseSavedResolution(raw: unknown): { width: number; height: number } | null {
		if (!Array.isArray(raw) || raw.length < 2) return null;
		const width = Number(raw[0]);
		const height = Number(raw[1]);
		if (!Number.isFinite(width) || !Number.isFinite(height) || width <= 0 || height <= 0) {
			return null;
		}
		return { width: Math.round(width), height: Math.round(height) };
	}

	function rescalePoints(
		points: number[][],
		srcW: number,
		srcH: number,
		dstW: number,
		dstH: number
	): number[][] {
		if (srcW <= 0 || srcH <= 0 || dstW <= 0 || dstH <= 0) return points;
		if (srcW === dstW && srcH === dstH) return points;
		const sx = dstW / srcW;
		const sy = dstH / srcH;
		return points.map((pt) => [pt[0] * sx, pt[1] * sy]);
	}

	function rescalePoint(
		point: Point,
		srcW: number,
		srcH: number,
		dstW: number,
		dstH: number
	): Point {
		if (srcW <= 0 || srcH <= 0 || dstW <= 0 || dstH <= 0) return point;
		if (srcW === dstW && srcH === dstH) return point;
		return [point[0] * (dstW / srcW), point[1] * (dstH / srcH)];
	}

	function rescaleArcParams(
		params: ArcParams,
		srcW: number,
		srcH: number,
		dstW: number,
		dstH: number
	): ArcParams {
		if (srcW === dstW && srcH === dstH) return params;
		const sx = dstW / srcW;
		const sy = dstH / srcH;
		const rs = Math.min(sx, sy);
		return {
			center: [params.center[0] * sx, params.center[1] * sy],
			innerRadius: params.innerRadius * rs,
			outerRadius: params.outerRadius * rs,
			exitOuterRadius: params.exitOuterRadius * rs,
			dropZone: copyChordZone(params.dropZone),
			exitZone: copyChordZone(params.exitZone),
			preciseZone: copyChordZone(params.preciseZone),
			ringHandleAngleDeg: params.ringHandleAngleDeg
		};
	}

	function rescaleQuadParams(
		params: QuadParams,
		srcW: number,
		srcH: number,
		dstW: number,
		dstH: number
	): QuadParams {
		if (srcW === dstW && srcH === dstH) return params;
		const sx = dstW / srcW;
		const sy = dstH / srcH;
		return {
			corners: params.corners.map((c) => [c[0] * sx, c[1] * sy] as Point) as [
				Point,
				Point,
				Point,
				Point
			]
		};
	}

	function channelCanvasSize(channel: Channel): { width: number; height: number } {
		const role = CAMERA_FOR_CHANNEL[channel];
		return cameraResolutions[role] ?? { width: DEFAULT_CANVAS_W, height: DEFAULT_CANVAS_H };
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
			const res = await fetch(`${getBackendHttpBase()}/api/cameras/list`, { signal: abort.signal });
			if (!res.ok) throw new Error(await res.text());
			const payload = await res.json();
			if (Array.isArray(payload)) {
				usbCameras = payload.filter((camera: UsbCameraInfo) => camera.index >= 0);
				networkCameras = [];
				return;
			}
			usbCameras = Array.isArray(payload.usb)
				? payload.usb.filter((camera: UsbCameraInfo) => camera.index >= 0)
				: [];
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
			const res = await fetch(`${getBackendHttpBase()}/api/cameras/assign`, {
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
			return buildOuterBoundaryPoints(params);
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
		const scaleX = CANVAS_W / rect.width;
		const scaleY = CANVAS_H / rect.height;
		const scale = Math.max(scaleX, scaleY);
		const contentW = CANVAS_W / scale;
		const contentH = CANVAS_H / scale;
		const padX = (rect.width - contentW) / 2;
		const padY = (rect.height - contentH) / 2;
		return [(e.clientX - rect.left - padX) * scale, (e.clientY - rect.top - padY) * scale];
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
		const angle = angleFromCenter(point, params.center);
		return distance >= params.innerRadius && distance <= outerRadiusForAngle(params, angle);
	}

	function hitArcHandle(channel: ArcChannel, point: Point): ArcHandle | null {
		const handles = getArcHandles(channel);
		if (!handles) return null;
		const order = arcEditableHandles(channel);
		for (const handle of order) {
			if (pointDistance(point, handles[handle]) <= handleHitRadius) {
				return handle;
			}
		}
		return null;
	}

	function hitPolygonVertex(channel: Channel, point: Point): boolean {
		return userPoints[channel].some(
			(vertex: number[]) => pointDistance(point, [vertex[0], vertex[1]]) <= vertexHitRadius
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
			if (sectionZero && pointDistance(point, sectionZero) <= handleHitRadius) {
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
		if (secondaryEditMode) {
			onSecondaryMouseDown(e);
			return;
		}
		if (e.button !== 0) return;
		const point = canvasCoords(e);
		didDrag = false;

		if (isArcChannel(currentChannel)) {
			const sectionZero = sectionZeroPoints[currentChannel];
			if (sectionZero && pointDistance(point, sectionZero) <= handleHitRadius) {
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
				const edgeOrRotateKind: Record<string, DragState['kind']> = {
					dropStartEdge: 'arc-drop-start-edge',
					dropEndEdge: 'arc-drop-end-edge',
					exitStartEdge: 'arc-exit-start-edge',
					exitEndEdge: 'arc-exit-end-edge',
					dropRotate: 'arc-drop-rotate',
					exitRotate: 'arc-exit-rotate',
					preciseStartEdge: 'arc-precise-start-edge',
					preciseEndEdge: 'arc-precise-end-edge',
					preciseRotate: 'arc-precise-rotate'
				};
				if (handle in edgeOrRotateKind) {
					dragState = {
						kind: edgeOrRotateKind[handle] as
							| 'arc-drop-start-edge'
							| 'arc-drop-end-edge'
							| 'arc-exit-start-edge'
							| 'arc-exit-end-edge'
							| 'arc-drop-rotate'
							| 'arc-exit-rotate'
							| 'arc-precise-start-edge'
							| 'arc-precise-end-edge'
							| 'arc-precise-rotate',
						channel: currentChannel,
						orig: copyArcParams(params),
						startPointerAngleDeg: angleFromCenter(point, params.center)
					};
					canvasCursor = 'grabbing';
					return;
				}
				if (handle === 'inner' || handle === 'outer' || handle === 'exitOuter') {
					const origParams = copyArcParams(params);
					dragState = {
						kind:
							handle === 'inner'
								? 'arc-inner'
								: handle === 'outer'
									? 'arc-outer'
									: 'arc-exit-outer',
						channel: currentChannel,
						start: point,
						startAngleDeg: effectiveRingHandleAngle(origParams),
						orig: origParams
					};
					canvasCursor = 'grabbing';
					return;
				}
				const zoneHandleKind = ZONE_HANDLE_TO_DRAG_KIND[handle as ZoneHandle] ?? null;
				if (zoneHandleKind === null) return;
				dragState = {
					kind: zoneHandleKind,
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
					corners: def.corners.map((c) => [c[0] + dx, c[1] + dy] as Point) as [
						Point,
						Point,
						Point,
						Point
					]
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
		if (secondaryEditMode) {
			onSecondaryMouseMove(e);
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
			case 'arc-inner':
			case 'arc-outer':
			case 'arc-exit-outer': {
				didDrag = true;
				const center = dragState.orig.center;
				const radius = pointDistance(point, center);
				const rawAngle = angleFromCenter(point, center);
				const snappedAngle = normalizeAngle(
					Math.round(rawAngle / RING_HANDLE_SNAP_DEG) * RING_HANDLE_SNAP_DEG
				);
				const nextRingHandleAngle = clampRingHandleAngle(dragState.orig, snappedAngle);
				if (dragState.kind === 'arc-inner') {
					setArc(dragState.channel, {
						...dragState.orig,
						innerRadius: Math.max(
							10,
							Math.min(radius, dragState.orig.outerRadius - MIN_ARC_THICKNESS)
						),
						ringHandleAngleDeg: nextRingHandleAngle
					});
				} else if (dragState.kind === 'arc-outer') {
					setArc(dragState.channel, {
						...dragState.orig,
						outerRadius: Math.max(dragState.orig.innerRadius + MIN_ARC_THICKNESS, radius),
						ringHandleAngleDeg: nextRingHandleAngle
					});
				} else {
					setArc(dragState.channel, {
						...dragState.orig,
						exitOuterRadius: clamp(
							radius,
							dragState.orig.innerRadius + MIN_ARC_THICKNESS,
							dragState.orig.outerRadius
						)
					});
				}
				break;
			}
			case 'arc-drop-start-inner':
			case 'arc-drop-start-outer':
			case 'arc-drop-end-inner':
			case 'arc-drop-end-outer':
			case 'arc-exit-start-inner':
			case 'arc-exit-start-outer':
			case 'arc-exit-end-inner':
			case 'arc-exit-end-outer':
			case 'arc-precise-start-inner':
			case 'arc-precise-start-outer':
			case 'arc-precise-end-inner':
			case 'arc-precise-end-outer': {
				didDrag = true;
				const angle = angleFromCenter(point, dragState.orig.center);
				const [zoneKey, edgeField] = DRAG_KIND_TO_ZONE_FIELD[dragState.kind];
				const update: Record<string, number> = { [edgeField]: angle };
				// Drop Start is a radial cut — keep the inner angle locked to
				// the outer one so the gap is a clean line from the channel
				// center to the outer circle.
				if (dragState.kind === 'arc-drop-start-outer') {
					update.startInnerAngle = angle;
				}
				setArc(dragState.channel, {
					...dragState.orig,
					[zoneKey]: {
						...dragState.orig[zoneKey],
						...update
					}
				});
				break;
			}
			case 'arc-drop-start-edge':
			case 'arc-drop-end-edge':
			case 'arc-exit-start-edge':
			case 'arc-exit-end-edge':
			case 'arc-drop-rotate':
			case 'arc-exit-rotate':
			case 'arc-precise-start-edge':
			case 'arc-precise-end-edge':
			case 'arc-precise-rotate': {
				didDrag = true;
				const currentAngle = angleFromCenter(point, dragState.orig.center);
				const delta = currentAngle - dragState.startPointerAngleDeg;
				const isDrop =
					dragState.kind === 'arc-drop-start-edge' ||
					dragState.kind === 'arc-drop-end-edge' ||
					dragState.kind === 'arc-drop-rotate';
				const isPrecise =
					dragState.kind === 'arc-precise-start-edge' ||
					dragState.kind === 'arc-precise-end-edge' ||
					dragState.kind === 'arc-precise-rotate';
				const zoneKey: 'dropZone' | 'exitZone' | 'preciseZone' = isDrop
					? 'dropZone'
					: isPrecise
						? 'preciseZone'
						: 'exitZone';
				const origZone = dragState.orig[zoneKey];
				const isRotate =
					dragState.kind === 'arc-drop-rotate' ||
					dragState.kind === 'arc-exit-rotate' ||
					dragState.kind === 'arc-precise-rotate';
				const isStartEdge =
					dragState.kind === 'arc-drop-start-edge' ||
					dragState.kind === 'arc-exit-start-edge' ||
					dragState.kind === 'arc-precise-start-edge';
				let newZone: ChordZone;
				if (isRotate) {
					newZone = {
						startInnerAngle: origZone.startInnerAngle + delta,
						startOuterAngle: origZone.startOuterAngle + delta,
						endInnerAngle: origZone.endInnerAngle + delta,
						endOuterAngle: origZone.endOuterAngle + delta
					};
				} else if (isStartEdge) {
					newZone = {
						...origZone,
						startInnerAngle: origZone.startInnerAngle + delta,
						startOuterAngle: origZone.startOuterAngle + delta
					};
				} else {
					newZone = {
						...origZone,
						endInnerAngle: origZone.endInnerAngle + delta,
						endOuterAngle: origZone.endOuterAngle + delta
					};
				}
				const nextParams: ArcParams = { ...dragState.orig, [zoneKey]: newZone };
				// Rotating the exit carries the precise zone rigidly with it (the
				// glue in setArc keeps the shared edge bonded either way; this
				// makes the precise zone travel instead of stretch on rotation).
				if (zoneKey === 'exitZone' && isRotate) {
					const op = dragState.orig.preciseZone;
					nextParams.preciseZone = {
						startInnerAngle: op.startInnerAngle + delta,
						startOuterAngle: op.startOuterAngle + delta,
						endInnerAngle: op.endInnerAngle + delta,
						endOuterAngle: op.endOuterAngle + delta
					};
				}
				setArc(dragState.channel, nextParams);
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
					corners: dragState.origCorners.map((c) => [c[0] + dx, c[1] + dy] as Point) as [
						Point,
						Point,
						Point,
						Point
					]
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
		if (secondaryEditMode) {
			onSecondaryMouseUp(e);
			return;
		}
		if (e.button !== 0) return;
		dragState = null;
		updateCanvasCursor(canvasCoords(e));
	}

	function onClick(e: MouseEvent) {
		if (!editingZone) return;
		if (secondaryEditMode) {
			onSecondaryClick(e);
			return;
		}
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
		if (secondaryEditMode) {
			onSecondaryContextMenu(e);
			return;
		}
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
			const nextExitOuter = clamp(
				params.exitOuterRadius * scale,
				nextInner + MIN_ARC_THICKNESS,
				nextOuter
			);
			setArc(currentChannel, {
				...params,
				innerRadius: nextInner,
				outerRadius: nextOuter,
				exitOuterRadius: nextExitOuter
			});
			return;
		}

		if (isRectChannel(currentChannel)) {
			const q = quadParams[currentChannel];
			if (!q) return;
			const center = quadCenter(q);
			quadParams[currentChannel] = {
				corners: q.corners.map(
					(c) =>
						[
							center[0] + (c[0] - center[0]) * scale,
							center[1] + (c[1] - center[1]) * scale
						] as Point
				) as [Point, Point, Point, Point]
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
		label = '',
		offset: Point = [0, -20]
	) {
		const s = editorScale;
		if (label) {
			ctx.font = `bold ${Math.round(13 * s)}px sans-serif`;
			ctx.textAlign = 'center';
			ctx.textBaseline = 'middle';
			const metrics = ctx.measureText(label);
			const textWidth = metrics.width;
			const paddingX = 9 * s;
			const boxWidth = textWidth + paddingX * 2;
			const boxHeight = 24 * s;
			const edgePad = labelEdgePadding;
			const minLabelX = edgePad + boxWidth / 2;
			const maxLabelX = CANVAS_W - edgePad - boxWidth / 2;
			const minLabelY = edgePad + boxHeight / 2;
			const maxLabelY = CANVAS_H - edgePad - boxHeight / 2;
			const labelX = clamp(point[0] + offset[0] * s, minLabelX, Math.max(minLabelX, maxLabelX));
			const labelY = clamp(point[1] + offset[1] * s, minLabelY, Math.max(minLabelY, maxLabelY));
			const boxX = labelX - boxWidth / 2;
			const boxY = labelY - boxHeight / 2;
			ctx.save();
			ctx.shadowColor = 'rgba(0, 0, 0, 0.28)';
			ctx.shadowBlur = 12 * s;
			ctx.shadowOffsetX = 0;
			ctx.shadowOffsetY = 4 * s;
			ctx.beginPath();
			ctx.roundRect(boxX, boxY, boxWidth, boxHeight, 4 * s);
			ctx.fillStyle = 'rgba(255, 255, 255, 0.96)';
			ctx.fill();
			ctx.restore();
			ctx.beginPath();
			ctx.roundRect(boxX, boxY, boxWidth, boxHeight, 4 * s);
			ctx.strokeStyle = 'rgba(17, 17, 17, 0.12)';
			ctx.lineWidth = 1 * s;
			ctx.stroke();
			ctx.fillStyle = '#111';
			ctx.fillText(label, labelX, labelY);
		}

		ctx.beginPath();
		ctx.arc(point[0], point[1], HANDLE_DRAW_RADIUS * s, 0, Math.PI * 2);
		ctx.fillStyle = fill;
		ctx.fill();
		ctx.lineWidth = 2 * s;
		ctx.strokeStyle = stroke;
		ctx.stroke();
	}

	function drawEdgeHandle(
		ctx: CanvasRenderingContext2D,
		point: Point,
		innerEnd: Point,
		outerEnd: Point,
		color: string
	) {
		const s = editorScale;
		const dx = outerEnd[0] - innerEnd[0];
		const dy = outerEnd[1] - innerEnd[1];
		const len = Math.hypot(dx, dy) || 1;
		const ux = dx / len;
		const uy = dy / len;
		// perpendicular to the radial line
		const px = -uy;
		const py = ux;
		const halfLen = 7 * s;
		const halfThick = 2.5 * s;
		const c1: Point = [
			point[0] + ux * halfThick + px * halfLen,
			point[1] + uy * halfThick + py * halfLen
		];
		const c2: Point = [
			point[0] + ux * halfThick - px * halfLen,
			point[1] + uy * halfThick - py * halfLen
		];
		const c3: Point = [
			point[0] - ux * halfThick - px * halfLen,
			point[1] - uy * halfThick - py * halfLen
		];
		const c4: Point = [
			point[0] - ux * halfThick + px * halfLen,
			point[1] - uy * halfThick + py * halfLen
		];
		ctx.beginPath();
		ctx.moveTo(c1[0], c1[1]);
		ctx.lineTo(c2[0], c2[1]);
		ctx.lineTo(c3[0], c3[1]);
		ctx.lineTo(c4[0], c4[1]);
		ctx.closePath();
		ctx.fillStyle = color;
		ctx.globalAlpha = 0.85;
		ctx.fill();
		ctx.globalAlpha = 1;
		ctx.lineWidth = 1 * s;
		ctx.strokeStyle = 'rgba(0,0,0,0.55)';
		ctx.stroke();
	}

	function drawRotateHandle(
		ctx: CanvasRenderingContext2D,
		point: Point,
		center: Point,
		color: string
	) {
		const s = editorScale;
		const r = HANDLE_DRAW_RADIUS * 0.7 * s;
		ctx.beginPath();
		ctx.arc(point[0], point[1], r, 0, Math.PI * 2);
		ctx.fillStyle = color;
		ctx.globalAlpha = 0.85;
		ctx.fill();
		ctx.globalAlpha = 1;
		ctx.lineWidth = 1 * s;
		ctx.strokeStyle = 'rgba(0,0,0,0.55)';
		ctx.stroke();

		// curved arrow hint indicating rotation around the ring center
		const dx = point[0] - center[0];
		const dy = point[1] - center[1];
		const len = Math.hypot(dx, dy) || 1;
		const ux = dx / len;
		const uy = dy / len;
		const px = -uy;
		const py = ux;
		const armLen = 4.5 * s;
		ctx.beginPath();
		ctx.moveTo(point[0] - px * armLen, point[1] - py * armLen);
		ctx.lineTo(point[0] + px * armLen, point[1] + py * armLen);
		ctx.strokeStyle = '#fff';
		ctx.lineWidth = 1.8 * s;
		ctx.stroke();
		// little arrowheads
		ctx.beginPath();
		ctx.moveTo(point[0] + px * armLen, point[1] + py * armLen);
		ctx.lineTo(
			point[0] + px * armLen * 0.55 + ux * 2.5 * s,
			point[1] + py * armLen * 0.55 + uy * 2.5 * s
		);
		ctx.moveTo(point[0] - px * armLen, point[1] - py * armLen);
		ctx.lineTo(
			point[0] - px * armLen * 0.55 + ux * 2.5 * s,
			point[1] - py * armLen * 0.55 + uy * 2.5 * s
		);
		ctx.stroke();
	}

	function exitOuterLabelOffset(point: Point): Point {
		return point[1] > CANVAS_H - 90 * editorScale ? [0, -26] : [0, 24];
	}

	function drawSectionZero(ctx: CanvasRenderingContext2D, channel: ArcChannel, active: boolean) {
		if (!editingZone) return;
		const center = getChannelCenter(channel);
		const ref = sectionZeroPoints[channel];
		if (!center || !ref) return;

		const s = editorScale;
		ctx.beginPath();
		ctx.moveTo(center[0], center[1]);
		ctx.lineTo(ref[0], ref[1]);
		ctx.strokeStyle = `rgba(255,255,255,${active ? 0.9 : 0.3})`;
		ctx.lineWidth = (active ? 2 : 1) * s;
		ctx.setLineDash([6 * s, 4 * s]);
		ctx.stroke();
		ctx.setLineDash([]);

		drawHandle(ctx, ref, `rgba(255,255,255,${active ? 0.95 : 0.35})`, 'rgba(0,0,0,0.7)', '0');
	}

	function drawArcChannel(ctx: CanvasRenderingContext2D, channel: ArcChannel, active: boolean) {
		const params = arcParams[channel];
		if (!params) return;

		const s = editorScale;
		const color = CHANNEL_COLORS[channel];
		const alpha = active ? 1 : 0.35;
		const outerBoundary = buildOuterBoundaryPoints(params);
		const innerCircle = buildCirclePoints(params.center, params.innerRadius);
		const dropPolygon = buildZonePolygon(params, params.dropZone, params.outerRadius);
		const exitPolygon = buildZonePolygon(params, params.exitZone, params.exitOuterRadius);
		// Zero-width precise (the default) has no fill — positiveAngleSpan would
		// otherwise treat a zero span as a full ring. Its handles are still drawn
		// below so it can be dragged out to give it width.
		const preciseWidthDeg =
			(normalizeAngle(params.preciseZone.endOuterAngle) -
				normalizeAngle(params.preciseZone.startOuterAngle) +
				360) %
			360;
		const precisePolygon =
			preciseWidthDeg > 0.01
				? buildZonePolygon(params, params.preciseZone, params.outerRadius)
				: null;

		ctx.beginPath();
		ctx.moveTo(outerBoundary[0][0], outerBoundary[0][1]);
		for (let i = 1; i < outerBoundary.length; i++) {
			ctx.lineTo(outerBoundary[i][0], outerBoundary[i][1]);
		}
		ctx.closePath();
		ctx.moveTo(innerCircle[0][0], innerCircle[0][1]);
		for (let i = 1; i < innerCircle.length; i++) {
			ctx.lineTo(innerCircle[i][0], innerCircle[i][1]);
		}
		ctx.closePath();
		ctx.fillStyle = active ? `${color}14` : `${color}0a`;
		ctx.fill('evenodd');

		const zoneOverlays: Array<{ polygon: Point[]; color: string; alpha: number }> = [
			{ polygon: dropPolygon, color: DROP_ZONE_COLOR, alpha: active ? 0.22 : 0.1 },
			{ polygon: exitPolygon, color: EXIT_ZONE_COLOR, alpha: active ? 0.22 : 0.1 },
			...(precisePolygon
				? [{ polygon: precisePolygon, color: PRECISE_ZONE_COLOR, alpha: active ? 0.22 : 0.1 }]
				: [])
		];

		for (const { polygon: zonePolygon, color: zoneColor, alpha: zoneAlpha } of zoneOverlays) {
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
		ctx.moveTo(outerBoundary[0][0], outerBoundary[0][1]);
		for (let i = 1; i < outerBoundary.length; i++) {
			ctx.lineTo(outerBoundary[i][0], outerBoundary[i][1]);
		}
		ctx.closePath();
		ctx.strokeStyle = color;
		ctx.globalAlpha = alpha;
		ctx.lineWidth = (active ? 2 : 1) * s;
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
			ctx.lineWidth = 1.25 * s;
			ctx.beginPath();
			// Drop Start is locked radial — draw straight from the center to
			// the outer handle so the user sees the true cut geometry.
			ctx.moveTo(params.center[0], params.center[1]);
			ctx.lineTo(handles.dropStartOuter[0], handles.dropStartOuter[1]);
			ctx.moveTo(handles.dropEndInner[0], handles.dropEndInner[1]);
			ctx.lineTo(handles.dropEndOuter[0], handles.dropEndOuter[1]);
			ctx.stroke();

			ctx.strokeStyle = `${EXIT_ZONE_COLOR}cc`;
			ctx.lineWidth = 1 * s;
			ctx.beginPath();
			ctx.moveTo(handles.exitStartInner[0], handles.exitStartInner[1]);
			ctx.lineTo(handles.exitStartOuter[0], handles.exitStartOuter[1]);
			ctx.moveTo(handles.exitEndInner[0], handles.exitEndInner[1]);
			ctx.lineTo(handles.exitEndOuter[0], handles.exitEndOuter[1]);
			ctx.stroke();

			ctx.strokeStyle = `${color}aa`;
			ctx.beginPath();
			ctx.moveTo(params.center[0], params.center[1]);
			ctx.lineTo(handles.inner[0], handles.inner[1]);
			ctx.moveTo(params.center[0], params.center[1]);
			ctx.lineTo(handles.outer[0], handles.outer[1]);
			ctx.stroke();

			ctx.strokeStyle = `${EXIT_ZONE_COLOR}99`;
			ctx.beginPath();
			ctx.moveTo(params.center[0], params.center[1]);
			ctx.lineTo(handles.exitOuter[0], handles.exitOuter[1]);
			ctx.stroke();

			drawHandle(ctx, handles.center, color, '#111', 'Center');
			drawHandle(ctx, handles.inner, color, '#111', 'Inner');
			drawHandle(ctx, handles.outer, color, '#111', 'Outer');
			drawHandle(
				ctx,
				handles.exitOuter,
				EXIT_ZONE_COLOR,
				'#111',
				'Exit Outer',
				exitOuterLabelOffset(handles.exitOuter)
			);
			// The classification carousel travels counterclockwise, so the edge a
			// piece reaches FIRST is the geometric "end" edge. Label in travel order
			// so "Start" is always the entry edge (Start comes before End going CCW).
			const ccwZones = currentChannel === 'classification_channel';
			drawHandle(ctx, handles.dropStartOuter, DROP_ZONE_COLOR, '#111', ccwZones ? 'Drop End' : 'Drop Start', [-42, -18]);
			// Drop Start has no inner handle — the boundary is locked radial.
			drawHandle(ctx, handles.dropEndOuter, DROP_ZONE_COLOR, '#111', ccwZones ? 'Drop Start' : 'Drop End', [42, -18]);
			drawHandle(ctx, handles.dropEndInner, DROP_ZONE_COLOR, '#111');
			drawHandle(ctx, handles.exitStartOuter, EXIT_ZONE_COLOR, '#111', ccwZones ? 'Exit End' : 'Exit Start', [-42, 22]);
			drawHandle(ctx, handles.exitStartInner, EXIT_ZONE_COLOR, '#111');
			drawHandle(ctx, handles.exitEndOuter, EXIT_ZONE_COLOR, '#111', ccwZones ? 'Exit Start' : 'Exit End', [42, 22]);
			drawHandle(ctx, handles.exitEndInner, EXIT_ZONE_COLOR, '#111');
			drawHandle(
				ctx,
				handles.preciseStartOuter,
				PRECISE_ZONE_COLOR,
				'#111',
				ccwZones ? 'Precise End' : 'Precise Start',
				[-42, 22]
			);
			drawHandle(ctx, handles.preciseStartInner, PRECISE_ZONE_COLOR, '#111');
			drawHandle(ctx, handles.preciseEndOuter, PRECISE_ZONE_COLOR, '#111', ccwZones ? 'Precise Start' : 'Precise End', [42, 22]);
			drawHandle(ctx, handles.preciseEndInner, PRECISE_ZONE_COLOR, '#111');

			drawEdgeHandle(
				ctx,
				handles.dropStartEdge,
				handles.dropStartInner,
				handles.dropStartOuter,
				DROP_ZONE_COLOR
			);
			drawEdgeHandle(
				ctx,
				handles.dropEndEdge,
				handles.dropEndInner,
				handles.dropEndOuter,
				DROP_ZONE_COLOR
			);
			drawEdgeHandle(
				ctx,
				handles.exitStartEdge,
				handles.exitStartInner,
				handles.exitStartOuter,
				EXIT_ZONE_COLOR
			);
			drawEdgeHandle(
				ctx,
				handles.exitEndEdge,
				handles.exitEndInner,
				handles.exitEndOuter,
				EXIT_ZONE_COLOR
			);
			drawEdgeHandle(
				ctx,
				handles.preciseStartEdge,
				handles.preciseStartInner,
				handles.preciseStartOuter,
				PRECISE_ZONE_COLOR
			);
			drawEdgeHandle(
				ctx,
				handles.preciseEndEdge,
				handles.preciseEndInner,
				handles.preciseEndOuter,
				PRECISE_ZONE_COLOR
			);
			drawRotateHandle(ctx, handles.dropRotate, params.center, DROP_ZONE_COLOR);
			drawRotateHandle(ctx, handles.exitRotate, params.center, EXIT_ZONE_COLOR);
			drawRotateHandle(ctx, handles.preciseRotate, params.center, PRECISE_ZONE_COLOR);
		}

		drawSectionZero(ctx, channel, active);
	}

	function drawPolygonChannel(ctx: CanvasRenderingContext2D, channel: Channel, active: boolean) {
		const pts = sortPolygon(userPoints[channel]);
		if (pts.length < 2) return;
		const s = editorScale;
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
		ctx.lineWidth = (active ? 2 : 1) * s;
		ctx.stroke();
		ctx.globalAlpha = 1;

		if (active && editingZone) {
			for (const pt of pts) {
				ctx.beginPath();
				ctx.arc(pt[0], pt[1], 6 * s, 0, Math.PI * 2);
				ctx.fillStyle = color;
				ctx.fill();
			}
		}
	}

	function drawQuadChannel(ctx: CanvasRenderingContext2D, channel: RectChannel, active: boolean) {
		const q = quadParams[channel];
		if (!q) return;
		const s = editorScale;
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
		ctx.lineWidth = (active ? 2 : 1) * s;
		ctx.stroke();
		ctx.globalAlpha = 1;

		if (active && editingZone) {
			// Corner handles
			for (const corner of corners) {
				ctx.beginPath();
				ctx.arc(corner[0], corner[1], HANDLE_DRAW_RADIUS * s, 0, Math.PI * 2);
				ctx.fillStyle = color;
				ctx.fill();
				ctx.lineWidth = 2 * s;
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

	// --- secondary (foreign) zones -------------------------------------------

	const SECONDARY_ZONE_COLOR = '#38bdf8';

	function secondaryHostKey(): string {
		return channelStorageKey(currentChannel);
	}

	function currentSecondaryList(): SecondaryZoneUI[] {
		return secondaryZones[secondaryHostKey()] ?? [];
	}

	function genSecondaryId(sourceChannel: number, zoneType: SecondaryZoneType): string {
		const rand =
			typeof crypto !== 'undefined' && 'randomUUID' in crypto
				? crypto.randomUUID().slice(0, 8)
				: Math.floor(Math.random() * 1e9).toString(36);
		return `sz_${sourceChannel}_${zoneType}_${rand}`;
	}

	function addSecondaryZone(sourceChannel: number, zoneType: SecondaryZoneType = 'exit') {
		const host = secondaryHostKey();
		const zone: SecondaryZoneUI = {
			id: genSecondaryId(sourceChannel, zoneType),
			sourceChannel,
			zoneType,
			points: []
		};
		secondaryZones[host] = [...(secondaryZones[host] ?? []), zone];
		activeSecondaryId = zone.id;
		secondaryEditMode = true;
	}

	function selectSecondaryZone(id: string) {
		activeSecondaryId = id;
		secondaryEditMode = true;
	}

	function deleteSecondaryZone(id: string) {
		const host = secondaryHostKey();
		secondaryZones[host] = (secondaryZones[host] ?? []).filter((z) => z.id !== id);
		if (activeSecondaryId === id) activeSecondaryId = null;
	}

	function setSecondaryZoneType(id: string, zoneType: SecondaryZoneType) {
		const host = secondaryHostKey();
		secondaryZones[host] = (secondaryZones[host] ?? []).map((z) =>
			z.id === id ? { ...z, zoneType } : z
		);
	}

	function exitSecondaryEditMode() {
		secondaryEditMode = false;
		secondaryVertexDrag = null;
	}

	function activeSecondaryZone(): SecondaryZoneUI | null {
		return currentSecondaryList().find((z) => z.id === activeSecondaryId) ?? null;
	}

	function hitSecondaryVertex(point: Point): { id: string; vertexIdx: number } | null {
		const zone = activeSecondaryZone();
		if (!zone) return null;
		for (let i = 0; i < zone.points.length; i++) {
			if (pointDistance(point, zone.points[i]) <= vertexHitRadius) {
				return { id: zone.id, vertexIdx: i };
			}
		}
		return null;
	}

	function updateSecondaryPoints(id: string, points: Point[]) {
		const host = secondaryHostKey();
		secondaryZones[host] = (secondaryZones[host] ?? []).map((z) =>
			z.id === id ? { ...z, points } : z
		);
	}

	function onSecondaryMouseDown(e: MouseEvent) {
		if (e.button !== 0) return;
		const point = canvasCoords(e);
		didDrag = false;
		const hit = hitSecondaryVertex(point);
		if (hit) {
			secondaryVertexDrag = hit;
			canvasCursor = 'grabbing';
		}
	}

	function onSecondaryMouseMove(e: MouseEvent) {
		const point = canvasCoords(e);
		if (!secondaryVertexDrag) {
			canvasCursor = hitSecondaryVertex(point) ? 'pointer' : 'crosshair';
			return;
		}
		didDrag = true;
		canvasCursor = 'grabbing';
		const zone = activeSecondaryZone();
		if (!zone || zone.id !== secondaryVertexDrag.id) return;
		const next = zone.points.map((pt, i) =>
			i === secondaryVertexDrag!.vertexIdx ? ([point[0], point[1]] as Point) : pt
		);
		updateSecondaryPoints(zone.id, next);
	}

	function onSecondaryMouseUp(e: MouseEvent) {
		if (e.button !== 0) return;
		secondaryVertexDrag = null;
	}

	function onSecondaryClick(e: MouseEvent) {
		if (didDrag) {
			didDrag = false;
			return;
		}
		const zone = activeSecondaryZone();
		if (!zone) return;
		const point = canvasCoords(e);
		updateSecondaryPoints(zone.id, [...zone.points, [point[0], point[1]]]);
	}

	function onSecondaryContextMenu(e: MouseEvent) {
		e.preventDefault();
		const zone = activeSecondaryZone();
		if (!zone) return;
		const point = canvasCoords(e);
		let minDist = Infinity;
		let minIdx = -1;
		for (let i = 0; i < zone.points.length; i++) {
			const d = pointDistance(point, zone.points[i]);
			if (d < minDist) {
				minDist = d;
				minIdx = i;
			}
		}
		if (minIdx >= 0 && minDist < 40) {
			updateSecondaryPoints(
				zone.id,
				zone.points.filter((_, idx) => idx !== minIdx)
			);
		}
	}

	function drawSecondaryZones(ctx: CanvasRenderingContext2D) {
		const zones = currentSecondaryList();
		if (zones.length === 0) return;
		const s = editorScale;
		const color = SECONDARY_ZONE_COLOR;
		for (const zone of zones) {
			const pts = zone.points;
			const isActive = secondaryEditMode && zone.id === activeSecondaryId;
			if (pts.length >= 2) {
				ctx.beginPath();
				ctx.moveTo(pts[0][0], pts[0][1]);
				for (let i = 1; i < pts.length; i++) ctx.lineTo(pts[i][0], pts[i][1]);
				if (pts.length >= 3) ctx.closePath();
				ctx.fillStyle = `${color}1f`;
				if (pts.length >= 3) ctx.fill();
				ctx.strokeStyle = color;
				ctx.globalAlpha = isActive ? 1 : 0.6;
				ctx.setLineDash([8 * s, 6 * s]);
				ctx.lineWidth = (isActive ? 2 : 1.5) * s;
				ctx.stroke();
				ctx.setLineDash([]);
				ctx.globalAlpha = 1;
			}
			if (isActive) {
				for (const pt of pts) {
					ctx.beginPath();
					ctx.arc(pt[0], pt[1], 6 * s, 0, Math.PI * 2);
					ctx.fillStyle = color;
					ctx.fill();
				}
			}
			if (pts.length >= 1) {
				const lx = pts.reduce((a, p) => a + p[0], 0) / pts.length;
				const ly = pts.reduce((a, p) => a + p[1], 0) / pts.length;
				ctx.fillStyle = color;
				ctx.font = `${Math.round(20 * s)}px sans-serif`;
				ctx.fillText(`C${zone.sourceChannel} ${zone.zoneType}`, lx, ly);
			}
		}
	}

	function drawCanvas() {
		if (!canvasEl) return;
		const ctx = canvasEl.getContext('2d');
		if (!ctx) return;

		ctx.clearRect(0, 0, CANVAS_W, CANVAS_H);
		if (!editingZone && previewCropped) return;
		if (!editingZone && !previewZones) return;
		const currentCamera = CAMERA_FOR_CHANNEL[currentChannel];

		for (const channel of channels) {
			if (channel === currentChannel) continue;
			if (CAMERA_FOR_CHANNEL[channel] === currentCamera) {
				drawChannel(ctx, channel, false);
			}
		}

		drawChannel(ctx, currentChannel, true);
		drawSecondaryZones(ctx);
	}

	$effect(() => {
		void userPoints;
		void arcParams;
		void sectionZeroPoints;
		void quadParams;
		void currentChannel;
		void channels;
		void editingZone;
		void previewZones;
		void secondaryZones;
		void secondaryEditMode;
		void activeSecondaryId;
		void CANVAS_W;
		void CANVAS_H;
		drawCanvas();
	});

	async function loadPolygonsPayload(): Promise<Record<string, any> | null> {
		const res = await fetch(`${getBackendHttpBase()}/api/polygons`, { cache: 'no-store' });
		if (!res.ok) return null;
		return await res.json();
	}

	async function loadPolygonsIntoState() {
		try {
			const data = await loadPolygonsPayload();
			if (!data) return;

			const channelData = data.channel ?? {};
			const channelUserPts = channelData.user_pts ?? {};
			const channelPolygons = channelData.polygons ?? {};
			const channelArcParams = channelData.arc_params ?? {};
			const savedChannelAngles = channelData.channel_angles ?? {};
			const sectionZero = channelData.section_zero_pts ?? {};
			const channelSavedResolution = parseSavedResolution(channelData.resolution);

			function resolveChannelSource(
				perChannelRes: unknown,
				fallback: { width: number; height: number } | null
			): { width: number; height: number } {
				return (
					parseSavedResolution(perChannelRes) ??
					fallback ?? { width: DEFAULT_CANVAS_W, height: DEFAULT_CANVAS_H }
				);
			}

			for (const channel of ARC_CHANNELS) {
				const rawArc = channelArcParams[channel] as { resolution?: unknown } | undefined;
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
					const polygonKey = channelStorageKey(channel);
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

				const src = resolveChannelSource(rawArc?.resolution, channelSavedResolution);
				const dst = channelCanvasSize(channel);
				if (src.width !== dst.width || src.height !== dst.height) {
					if (Array.isArray(userPoints[channel]) && userPoints[channel].length > 0) {
						userPoints[channel] = rescalePoints(
							userPoints[channel],
							src.width,
							src.height,
							dst.width,
							dst.height
						);
					}
					const params = arcParams[channel];
					if (params) {
						arcParams[channel] = rescaleArcParams(
							params,
							src.width,
							src.height,
							dst.width,
							dst.height
						);
					}
					const ref = sectionZeroPoints[channel];
					if (ref) {
						sectionZeroPoints[channel] = rescalePoint(
							ref,
							src.width,
							src.height,
							dst.width,
							dst.height
						);
					}
				}
			}

			// Load secondary (foreign) zones, keyed by host storage key. Points are
			// saved in the host channel's arc resolution, so rescale them the same
			// way the primary polygon for that host is rescaled.
			const channelSecondary = channelData.secondary_zones ?? {};
			const nextSecondary: Record<string, SecondaryZoneUI[]> = {};
			for (const [hostKey, rawList] of Object.entries(channelSecondary)) {
				if (!Array.isArray(rawList)) continue;
				const chName = ARC_CHANNELS.find((c) => channelStorageKey(c) === hostKey) ?? null;
				let src: { width: number; height: number } | null = null;
				let dst: { width: number; height: number } | null = null;
				if (chName) {
					const rawArc = channelArcParams[chName] as { resolution?: unknown } | undefined;
					src = resolveChannelSource(rawArc?.resolution, channelSavedResolution);
					dst = channelCanvasSize(chName);
				}
				const list: SecondaryZoneUI[] = [];
				for (const raw of rawList as any[]) {
					if (!raw || !Array.isArray(raw.points)) continue;
					let pts: Point[] = raw.points.map((p: number[]) => [p[0], p[1]] as Point);
					if (src && dst) {
						pts = rescalePoints(pts, src.width, src.height, dst.width, dst.height) as Point[];
					}
					const sourceChannel = Number(raw.source_channel ?? 0);
					const zoneType: SecondaryZoneType = ['drop', 'exit', 'precise'].includes(raw.zone_type)
						? raw.zone_type
						: 'exit';
					list.push({
						id: String(raw.id ?? genSecondaryId(sourceChannel, zoneType)),
						sourceChannel,
						zoneType,
						points: pts
					});
				}
				nextSecondary[hostKey] = list;
			}
			secondaryZones = nextSecondary;

			// Load rect params for carousel, classification channels
			const channelQuadParams = channelData.quad_params ?? {};
			const classificationData = data.classification ?? {};
			const classUserPts = classificationData.user_pts ?? {};
			const classPolygons = classificationData.polygons ?? {};
			const classQuadParams = classificationData.quad_params ?? {};
			const classificationSavedResolution = parseSavedResolution(classificationData.resolution);

			function loadQuad(saved: any, fallbackPts: any): QuadParams | null {
				if (saved && Array.isArray(saved.corners) && saved.corners.length === 4) {
					return {
						corners: saved.corners.map((c: number[]) => [c[0], c[1]] as Point) as [
							Point,
							Point,
							Point,
							Point
						]
					};
				}
				if (Array.isArray(fallbackPts) && fallbackPts.length >= 3) {
					return deriveQuadFromPolygon(fallbackPts);
				}
				return null;
			}

			function rescaleRectChannel(
				channel: RectChannel,
				rawQuad: unknown,
				groupFallback: { width: number; height: number } | null
			) {
				const quadRes = (rawQuad as { resolution?: unknown } | undefined)?.resolution;
				const src = resolveChannelSource(quadRes, groupFallback);
				const dst = channelCanvasSize(channel);
				if (src.width === dst.width && src.height === dst.height) return;
				const pts = userPoints[channel];
				if (Array.isArray(pts) && pts.length > 0) {
					userPoints[channel] = rescalePoints(pts, src.width, src.height, dst.width, dst.height);
				}
				const params = quadParams[channel];
				if (params) {
					quadParams[channel] = rescaleQuadParams(
						params,
						src.width,
						src.height,
						dst.width,
						dst.height
					);
				}
			}

			// Carousel
			const carouselQuad = loadQuad(
				channelQuadParams.carousel,
				channelUserPts.carousel ?? channelPolygons.carousel
			);
			if (carouselQuad) quadParams.carousel = carouselQuad;
			rescaleRectChannel('carousel', channelQuadParams.carousel, channelSavedResolution);

			// Classification top
			const topQuad = loadQuad(
				classQuadParams.class_top,
				classUserPts.class_top ?? classPolygons.top
			);
			if (topQuad) quadParams.class_top = topQuad;
			rescaleRectChannel('class_top', classQuadParams.class_top, classificationSavedResolution);

			// Classification bottom
			const bottomQuad = loadQuad(
				classQuadParams.class_bottom,
				classUserPts.class_bottom ?? classPolygons.bottom
			);
			if (bottomQuad) quadParams.class_bottom = bottomQuad;
			rescaleRectChannel(
				'class_bottom',
				classQuadParams.class_bottom,
				classificationSavedResolution
			);
		} catch {
			// ignore
		}
	}

	function serializeQuadParams(q: QuadParams, resolution: [number, number]): Record<string, any> {
		return {
			corners: q.corners.map((c) => [Math.round(c[0]), Math.round(c[1])]),
			resolution
		};
	}

	function quadAsPolygon(q: QuadParams): number[][] {
		return q.corners.map((c) => [Math.round(c[0]), Math.round(c[1])]);
	}

	async function saveAll(): Promise<boolean> {
		saving = true;
		try {
			let existingPayload: Record<string, any> = {};
			try {
				existingPayload = (await loadPolygonsPayload()) ?? {};
			} catch {
				// Fall back to saving from the current in-memory state only.
			}

			const existingChannel = existingPayload.channel ?? {};
			const existingClassification = existingPayload.classification ?? {};

			const polygons: Record<string, number[][]> = { ...(existingChannel.polygons ?? {}) };
			const user_pts: Record<string, number[][]> = { ...(existingChannel.user_pts ?? {}) };
			const arc_params: Record<string, ArcParamsPayload> = {
				...(existingChannel.arc_params ?? {})
			};
			const quad_params_channel: Record<string, Record<string, any>> = {
				...(existingChannel.quad_params ?? {})
			};
			const channel_angles: Record<string, number> = { ...(existingChannel.channel_angles ?? {}) };
			const section_zero_pts: Record<string, number[]> = {
				...(existingChannel.section_zero_pts ?? {})
			};
			// Preserve secondary zones for other hosts; rewrite only the current
			// host's list. Points are in the current canvas resolution, which is the
			// camera/frame resolution, so the backend rescales them correctly.
			const secondary_zones: Record<string, any[]> = {
				...(existingChannel.secondary_zones ?? {})
			};

			const current = currentChannel;
			const currentResolution: [number, number] = [CANVAS_W, CANVAS_H];

			if (TRANSPORT_CHANNELS.includes(current)) {
				const key = channelStorageKey(current);
				if (isArcChannel(current) && arcParams[current]) {
					const cropPts = buildCropPolygon(
						arcParams[current]!,
						current === 'classification_channel'
					).map((pt) => [Math.round(pt[0]), Math.round(pt[1])]);
					polygons[key] = cropPts;
					user_pts[current] = cropPts;
					arc_params[current] = serializeArcParams(arcParams[current]!, currentResolution);
					delete quad_params_channel[current];
				} else if (isRectChannel(current) && quadParams[current]) {
					const q = quadParams[current]!;
					const cornerPts = quadAsPolygon(q);
					polygons[key] = cornerPts;
					user_pts[current] = cornerPts;
					quad_params_channel[current] = serializeQuadParams(q, currentResolution);
					delete arc_params[current];
				} else {
					const points = getShapePoints(current).map((pt) => [
						Math.round(pt[0]),
						Math.round(pt[1])
					]);
					polygons[key] = points;
					user_pts[current] = points;
					delete arc_params[current];
					delete quad_params_channel[current];
				}
				if (isArcChannel(current)) {
					const angle = computeAngle(current);
					channel_angles[current] = angle ?? 0;
					if (sectionZeroPoints[current]) {
						section_zero_pts[current] = sectionZeroPoints[current]!.map(Math.round);
					} else {
						delete section_zero_pts[current];
					}
				}
				if (isArcChannel(current)) {
					secondary_zones[key] = (secondaryZones[key] ?? [])
						.filter((z) => z.points.length >= 3)
						.map((z) => ({
							id: z.id,
							source_channel: z.sourceChannel,
							zone_type: z.zoneType,
							points: z.points.map((p) => [Math.round(p[0]), Math.round(p[1])])
						}));
				}
			}

			const class_polygons: Record<string, number[][]> = {
				...(existingClassification.polygons ?? {})
			};
			const class_user_pts: Record<string, number[][]> = {
				...(existingClassification.user_pts ?? {})
			};
			const quad_params_class: Record<string, Record<string, any>> = {
				...(existingClassification.quad_params ?? {})
			};
			const channelGroupResolution = Array.isArray(existingChannel.resolution)
				? existingChannel.resolution
				: [CANVAS_W, CANVAS_H];
			const classificationGroupResolution = Array.isArray(existingClassification.resolution)
				? existingClassification.resolution
				: [CANVAS_W, CANVAS_H];
			if (isClassificationChannel(current)) {
				const key = current === 'class_top' ? 'top' : 'bottom';
				if (isRectChannel(current) && quadParams[current]) {
					const q = quadParams[current]!;
					const cornerPts = quadAsPolygon(q);
					class_polygons[key] = cornerPts;
					class_user_pts[current] = cornerPts;
					quad_params_class[current] = serializeQuadParams(q, currentResolution);
				} else {
					const points = sortPolygon(userPoints[current]).map((pt) => [
						Math.round(pt[0]),
						Math.round(pt[1])
					]);
					class_polygons[key] = points;
					class_user_pts[current] = userPoints[current].map((pt) => [
						Math.round(pt[0]),
						Math.round(pt[1])
					]);
					delete quad_params_class[current];
				}
			}

			const res = await fetch(`${getBackendHttpBase()}/api/polygons`, {
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
						secondary_zones,
						resolution: channelGroupResolution
					},
					classification: {
						polygons: class_polygons,
						user_pts: class_user_pts,
						quad_params: quad_params_class,
						resolution: classificationGroupResolution
					}
				})
			});
			if (!res.ok) throw new Error(await res.text());
			persistedSnapshot = snapshotCurrentState();
			editingZone = false;
			activeSidebar = null;
			dragState = null;
			didDrag = false;
			exitSecondaryEditMode();
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
		// Editing always works on the full uncropped frame so the canvas overlay
		// maps 1:1 to camera coordinates. Crop is normally off, so this is a
		// no-op and the feed connection is untouched.
		previewCropped = false;
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
		exitSecondaryEditMode();
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
		void loadCameraResolutions().finally(() => {
			void loadPolygonsIntoState().finally(() => {
				persistedSnapshot = snapshotCurrentState();
			});
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
				class="flex min-w-0 items-center gap-1 rounded-full bg-bg px-3 py-1 text-xs text-text-muted"
			>
				<span class="font-medium text-text">Source:</span>
				<span class="ml-1 truncate">{formatSource(currentAssignment())}</span>
				{#if currentAssignment() === null && cameraConfigLoaded}
					<button
						onclick={openCameraPicker}
						class="ml-1 inline-flex h-4 w-4 cursor-pointer items-center justify-center rounded-full bg-text-muted/20 text-text transition-colors hover:bg-text-muted/40"
						title="Select camera"
					>
						<svg
							class="h-2.5 w-2.5"
							viewBox="0 0 12 12"
							fill="none"
							stroke="currentColor"
							stroke-width="2"
							stroke-linecap="round"
						>
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
					{#if isArcChannel(currentChannel)}
						<button
							onclick={() => flipPreciseSide(currentChannel as ArcChannel)}
							class="inline-flex cursor-pointer items-center gap-2 border border-violet-500 bg-violet-500/15 px-3 py-1.5 text-sm text-violet-700 transition-colors hover:bg-violet-500/25 dark:text-violet-300"
						>
							<FlipHorizontal size={15} />
							<span>Flip Precise Side</span>
						</button>
					{/if}
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
						style={previewViewportStyle(currentChannel)}
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
									src={streamSrc(currentChannel)}
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
												class="absolute top-1 right-1 rounded border border-white/20 bg-violet-500/60 px-1.5 py-0.5 text-xs leading-none font-semibold text-white shadow-md backdrop-blur-sm"
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

				{#if editingZone && previousSourceChannel !== null}
					<div class="border border-border bg-surface px-4 py-3 text-sm text-text-muted">
						<div class="flex flex-wrap items-center justify-between gap-2">
							<div class="font-semibold text-text">
								Add Channel {previousSourceChannel} Zone
							</div>
							<button
								onclick={() => addSecondaryZone(previousSourceChannel!, 'exit')}
								class="inline-flex cursor-pointer items-center gap-2 border border-info bg-info/15 px-3 py-1.5 text-sm text-info transition-colors hover:bg-info/25"
							>
								<Plus size={15} />
								<span>Add Zone</span>
							</button>
						</div>
						<div class="mt-2 leading-6">
							If this camera's view can see the previous channel (C{previousSourceChannel}), denote
							its zone here for more reliable feeding and more angles for classification. These are
							shown on the live feed but not acted on yet.
						</div>

						{#if currentSecondaryList().length > 0}
							<div class="mt-3 flex flex-col gap-2">
								{#each currentSecondaryList() as zone (zone.id)}
									{@const isEditing = secondaryEditMode && zone.id === activeSecondaryId}
									<div
										class="flex flex-wrap items-center gap-2 border border-border bg-bg px-3 py-2"
										class:border-info={isEditing}
									>
										<span class="font-medium text-text">C{zone.sourceChannel}</span>
										<select
											value={zone.zoneType}
											onchange={(e) =>
												setSecondaryZoneType(
													zone.id,
													(e.currentTarget as HTMLSelectElement).value as SecondaryZoneType
												)}
											class="border border-border bg-surface px-2 py-1 text-sm text-text"
										>
											<option value="drop">drop</option>
											<option value="exit">exit</option>
											<option value="precise">precise</option>
										</select>
										<span class="text-sm text-text-muted">{zone.points.length} pts</span>
										<div class="ml-auto flex items-center gap-2">
											{#if isEditing}
												<button
													onclick={exitSecondaryEditMode}
													class="inline-flex cursor-pointer items-center gap-1 border border-success bg-success/15 px-2 py-1 text-sm text-success transition-colors hover:bg-success/25"
												>
													<Check size={14} />
													<span>Done</span>
												</button>
											{:else}
												<button
													onclick={() => selectSecondaryZone(zone.id)}
													class="inline-flex cursor-pointer items-center gap-1 border border-border bg-bg px-2 py-1 text-sm text-text transition-colors hover:bg-bg/80"
												>
													<Pencil size={14} />
													<span>Edit</span>
												</button>
											{/if}
											<button
												onclick={() => deleteSecondaryZone(zone.id)}
												class="inline-flex cursor-pointer items-center gap-1 border border-border bg-bg px-2 py-1 text-sm text-text transition-colors hover:bg-bg/80"
											>
												<X size={14} />
											</button>
										</div>
									</div>
								{/each}
							</div>
						{/if}

						{#if secondaryEditMode}
							<div class="mt-2 text-sm text-info">
								Drawing C{activeSecondaryZone()?.sourceChannel} zone: click to add points, drag a point
								to move it, right-click a point to remove it.
							</div>
						{/if}
					</div>
				{/if}

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
									<div
										class="mt-2 rounded border border-success/20 bg-success/8 px-3 py-2 leading-6 text-text-muted"
									>
										<span class="font-medium text-success">Green Drop Zone:</span>
										position this where parts arrive from the previous stage and land on the ring.
									</div>
									<div
										class="mt-2 rounded border border-danger/20 bg-danger/8 px-3 py-2 leading-6 text-text-muted"
									>
										<span class="font-medium text-danger">Red Exit Zone:</span>
										position this where parts should leave the ring into the next path or mechanism.
									</div>
									<div class="mt-2 text-xs leading-5 text-text-muted">
										Use this as an orientation guide. The exact angles depend on your camera
										position and the real machine geometry.
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
									<span class="font-medium text-text">Outer</span> directly on the image. Use
									<span class="font-medium text-text">Exit Outer</span> to pull the exit crop inward when
									the opening shows the next plate.
								</div>
								<div class="mt-1 leading-6">
									Drag inside the ring to move the whole zone. Use the mouse wheel for fine radius
									scaling and
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
				<StepperSidebar
					{stepperKey}
					endstop={stepperEndstop}
					label={stepperLabel}
					gearRatioOverride={stepperGearRatio}
					keyboardShortcuts={true}
				/>
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
					<div class="animate-pulse py-8 text-center text-sm text-text-muted">
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
										<CameraSourcePreview
											src={cameraIndexPreviewUrl(cam.index)}
											label={cam.name ?? `Camera ${cam.index}`}
											fit="cover"
											block
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
										<CameraSourcePreview
											src={discoveredPreviewUrl(cam)}
											label={cam.name}
											fit="cover"
											block
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

				<div class="flex items-center justify-between border-t border-border pt-3">
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
			<Modal bind:open={reassignModalOpen} title="Reassign Camera">
				<div class="flex flex-col gap-4">
					<p class="text-sm text-text">
						<span class="font-medium">{reassignConfirm.cameraLabel}</span> is currently assigned to
						<span class="font-medium">{ROLE_LABELS[reassignConfirm.currentRole]}</span>. It will be
						unassigned from that role.
					</p>
					<div class="flex items-center justify-end gap-2">
						<button
							onclick={() => {
								reassignConfirm = null;
								reassignModalOpen = false;
							}}
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
