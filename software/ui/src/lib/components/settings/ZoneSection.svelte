<script lang="ts">
	import { backendHttpBaseUrl } from '$lib/backend';
	import Modal from '$lib/components/Modal.svelte';
	import PictureSettingsSidebar from '$lib/components/settings/PictureSettingsSidebar.svelte';
	import ZoneEditingSidebar from '$lib/components/settings/ZoneEditingSidebar.svelte';
	import {
		clonePictureSettings,
		pictureSettingsEqual,
		type PictureSettings
	} from '$lib/settings/picture-settings';
	import type { CameraRole } from '$lib/settings/stations';
	import { Camera, Check, Pencil, RefreshCw, RotateCcw, SlidersHorizontal, X } from 'lucide-svelte';
	import { onMount } from 'svelte';

	type Channel = 'second' | 'third' | 'carousel' | 'class_top' | 'class_bottom';
	type ArcChannel = 'second' | 'third';
	type Point = [number, number];
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
		startAngle: number;
		endAngle: number;
	};
	type ArcHandle = 'center' | 'inner' | 'outer' | 'start' | 'end';
	type ArcParamsPayload = {
		center: number[];
		inner_radius: number;
		outer_radius: number;
		start_angle: number;
		end_angle: number;
	};
	type Snapshot = {
		userPoints: Record<Channel, number[][]>;
		arcParams: Record<ArcChannel, ArcParams | null>;
		sectionZeroPoints: Record<ArcChannel, Point | null>;
	};
	type PicturePreviewState = {
		saved: PictureSettings;
		draft: PictureSettings;
	};
	type SidePanel = 'picture' | 'zone' | null;
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
				kind: 'arc-inner' | 'arc-outer' | 'arc-start' | 'arc-end';
				channel: ArcChannel;
				orig: ArcParams;
		  }
		| {
				kind: 'section-zero';
				channel: ArcChannel;
		  };

	const ARC_CHANNELS: ArcChannel[] = ['second', 'third'];
	const FEEDER_CHANNELS: Channel[] = ['second', 'third', 'carousel'];
	const CLASSIFICATION_CHANNELS: Channel[] = ['class_top', 'class_bottom'];
	const ALL_CHANNELS: Channel[] = [...FEEDER_CHANNELS, ...CLASSIFICATION_CHANNELS];
	const HANDLE_HIT_RADIUS = 22;
	const HANDLE_DRAW_RADIUS = 9;
	const VERTEX_HIT_RADIUS = 18;
	const LABEL_EDGE_PADDING = 12;
	const ARC_SEGMENTS = 64;
	const MIN_ARC_SPAN_DEG = 12;
	const MIN_ARC_THICKNESS = 20;
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

	let {
		channels = ALL_CHANNELS
	}: {
		channels?: Channel[];
	} = $props();

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
	let saving = $state(false);
	let statusMsg = $state('');
	let dragState = $state<DragState | null>(null);
	let didDrag = $state(false);
	let editingZone = $state(false);
	let activeSidebar = $state<SidePanel>(null);
	let cameraModalOpen = $state(false);
	let cameraLoading = $state(false);
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
	let feedRevision = $state(0);
	let canvasCursor = $state<'default' | 'crosshair' | 'pointer' | 'grab' | 'grabbing'>('default');
	let canvasEl: HTMLCanvasElement;
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
			editingZone = false;
			activeSidebar = null;
			dragState = null;
			didDrag = false;
			canvasCursor = 'default';
			statusMsg = '';
			return;
		}

		if (!channels.includes(currentChannel)) {
			currentChannel = channels[0] ?? 'second';
		}
	});

	$effect(() => {
		for (const ch of ARC_CHANNELS) {
			if (channels.includes(ch) && arcParams[ch] === null) {
				arcParams[ch] = defaultArcParams(ch);
			}
		}
	});

	function isArcChannel(ch: Channel): ch is ArcChannel {
		return ARC_CHANNELS.includes(ch as ArcChannel);
	}

	function normalizeAngle(angle: number): number {
		return ((angle % 360) + 360) % 360;
	}

	function positiveAngleSpan(start: number, end: number): number {
		const span = (normalizeAngle(end) - normalizeAngle(start) + 360) % 360;
		return span === 0 ? 360 : span;
	}

	function clampAngleSpan(params: ArcParams): ArcParams {
		const next = copyArcParams(params);
		let span = positiveAngleSpan(next.startAngle, next.endAngle);
		if (span < MIN_ARC_SPAN_DEG) {
			next.endAngle = normalizeAngle(next.startAngle + MIN_ARC_SPAN_DEG);
			span = MIN_ARC_SPAN_DEG;
		}
		if (span > 360 - MIN_ARC_SPAN_DEG) {
			next.endAngle = normalizeAngle(next.startAngle + (360 - MIN_ARC_SPAN_DEG));
		}
		return next;
	}

	function copyArcParams(params: ArcParams): ArcParams {
		return {
			center: [params.center[0], params.center[1]],
			innerRadius: params.innerRadius,
			outerRadius: params.outerRadius,
			startAngle: params.startAngle,
			endAngle: params.endAngle
		};
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

	function previewFilterId(role: CameraRole = currentRole()): string {
		return `picture-preview-${role}`;
	}

	function hasDraftPicturePreview(role: CameraRole = currentRole()): boolean {
		const preview = getPicturePreview(role);
		return preview !== null && !pictureSettingsEqual(preview.saved, preview.draft);
	}

	function normalizeLinearSlope(value: number): number {
		return Math.max(value, 0.0001);
	}

	function normalizeGammaValue(value: number): number {
		return Math.max(value, 0.0001);
	}

	function normalizeSaturationValue(value: number): number {
		return Math.max(value, 0.0001);
	}

	function forwardLinearIntercept(settings: PictureSettings): number {
		return settings.brightness / 255;
	}

	function inverseLinearSlope(settings: PictureSettings): number {
		return 1 / normalizeLinearSlope(settings.contrast);
	}

	function inverseLinearIntercept(settings: PictureSettings): number {
		return -forwardLinearIntercept(settings) / normalizeLinearSlope(settings.contrast);
	}

	function forwardGammaExponent(settings: PictureSettings): number {
		return 1 / normalizeGammaValue(settings.gamma);
	}

	function inverseGammaExponent(settings: PictureSettings): number {
		return normalizeGammaValue(settings.gamma);
	}

	function inverseSaturation(settings: PictureSettings): number {
		return 1 / normalizeSaturationValue(settings.saturation);
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

		matrix = multiplyTransformMatrices(rotationMatrix[settings.rotation] ?? rotationMatrix[0], matrix);
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
		const role = currentRole(channel);
		const styles: string[] = [];
		if (hasDraftPicturePreview(role)) {
			styles.push(`filter: url(#${previewFilterId(role)});`);
		}
		const transformStyle = picturePreviewTransform(channel);
		if (transformStyle) styles.push(transformStyle);
		return styles.join(' ');
	}

	function togglePictureSidebar() {
		if (activeSidebar === 'picture') {
			clearPicturePreview(currentRole());
			activeSidebar = null;
			return;
		}
		activeSidebar = 'picture';
	}

	function selectChannel(channel: Channel) {
		if (activeSidebar === 'picture') {
			clearPicturePreview(currentRole());
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

	function defaultArcParams(channel: ArcChannel): ArcParams {
		const center: Point =
			channel === 'second'
				? [CANVAS_W * 0.46, CANVAS_H * 0.55]
				: [CANVAS_W * 0.54, CANVAS_H * 0.55];
		return {
			center,
			innerRadius: 180,
			outerRadius: 360,
			startAngle: -150,
			endAngle: 150
		};
	}

	function serializeArcParams(params: ArcParams): ArcParamsPayload {
		return {
			center: [Math.round(params.center[0]), Math.round(params.center[1])],
			inner_radius: Math.round(params.innerRadius),
			outer_radius: Math.round(params.outerRadius),
			start_angle: params.startAngle,
			end_angle: params.endAngle
		};
	}

	function parseArcParams(raw: unknown): ArcParams | null {
		if (!raw || typeof raw !== 'object') return null;
		const center = (raw as ArcParamsPayload).center;
		const innerRadius = (raw as ArcParamsPayload).inner_radius;
		const outerRadius = (raw as ArcParamsPayload).outer_radius;
		const startAngle = (raw as ArcParamsPayload).start_angle;
		const endAngle = (raw as ArcParamsPayload).end_angle;
		if (
			!Array.isArray(center) ||
			center.length !== 2 ||
			typeof center[0] !== 'number' ||
			typeof center[1] !== 'number' ||
			typeof innerRadius !== 'number' ||
			typeof outerRadius !== 'number' ||
			typeof startAngle !== 'number' ||
			typeof endAngle !== 'number'
		) {
			return null;
		}
		return clampAngleSpan({
			center: [center[0], center[1]],
			innerRadius: Math.max(10, innerRadius),
			outerRadius: Math.max(innerRadius + MIN_ARC_THICKNESS, outerRadius),
			startAngle,
			endAngle
		});
	}

	function deriveArcParamsFromPolygon(points: number[][]): ArcParams | null {
		if (points.length < 3) return null;
		const center = polyCenter(points);
		if (!center) return null;

		const distances = points.map((pt) => pointDistance([pt[0], pt[1]], [center[0], center[1]]));
		const innerRadius = Math.max(10, Math.min(...distances));
		const outerRadius = Math.max(innerRadius + MIN_ARC_THICKNESS, Math.max(...distances));
		const angles = points
			.map((pt) => normalizeAngle(angleFromCenter([pt[0], pt[1]], [center[0], center[1]])))
			.sort((a, b) => a - b);

		let largestGap = -1;
		let gapIndex = -1;
		for (let i = 0; i < angles.length; i++) {
			const nextIndex = (i + 1) % angles.length;
			const gap = (angles[nextIndex] - angles[i] + 360) % 360;
			if (gap > largestGap) {
				largestGap = gap;
				gapIndex = i;
			}
		}

		const startAngle = angles[(gapIndex + 1) % angles.length];
		const endAngle = angles[gapIndex];

		return clampAngleSpan({
			center: [center[0], center[1]],
			innerRadius,
			outerRadius,
			startAngle,
			endAngle
		});
	}

	function arcMidAngle(params: ArcParams): number {
		return normalizeAngle(
			params.startAngle + positiveAngleSpan(params.startAngle, params.endAngle) / 2
		);
	}

	function buildArcPolygon(params: ArcParams): Point[] {
		const span = positiveAngleSpan(params.startAngle, params.endAngle);
		const segments = Math.max(12, Math.round((span / 360) * ARC_SEGMENTS));
		const pts: Point[] = [];

		for (let i = 0; i <= segments; i++) {
			const angle = params.startAngle + (span * i) / segments;
			pts.push(polarPoint(params.center, params.outerRadius, angle));
		}
		for (let i = segments; i >= 0; i--) {
			const angle = params.startAngle + (span * i) / segments;
			pts.push(polarPoint(params.center, params.innerRadius, angle));
		}

		return pts;
	}

	function getArcPolygon(channel: ArcChannel): Point[] {
		const params = arcParams[channel];
		if (!params) return [];
		return buildArcPolygon(params);
	}

	function getArcHandles(channel: ArcChannel): Record<ArcHandle, Point> | null {
		const params = arcParams[channel];
		if (!params) return null;
		const midAngle = arcMidAngle(params);
		return {
			center: [params.center[0], params.center[1]],
			inner: polarPoint(params.center, params.innerRadius, midAngle),
			outer: polarPoint(params.center, params.outerRadius, midAngle),
			start: polarPoint(params.center, params.outerRadius, params.startAngle),
			end: polarPoint(params.center, params.outerRadius, params.endAngle)
		};
	}

	function setArc(channel: ArcChannel, next: ArcParams) {
		const clamped = clampAngleSpan({
			...next,
			innerRadius: Math.max(10, Math.min(next.innerRadius, next.outerRadius - MIN_ARC_THICKNESS)),
			outerRadius: Math.max(next.innerRadius + MIN_ARC_THICKNESS, next.outerRadius)
		});
		arcParams[channel] = clamped;
	}

	function streamUrl(channel: Channel): string {
		return `${backendHttpBaseUrl}/api/cameras/feed/${CAMERA_FOR_CHANNEL[channel]}?v=${feedRevision}`;
	}

	function feedInstanceKey(channel: Channel): string {
		const assignment = currentAssignment(channel);
		return `${currentRole(channel)}::${assignment === null ? 'none' : String(assignment)}::${feedRevision}`;
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

	async function refreshCameras() {
		cameraLoading = true;
		cameraError = null;
		try {
			await loadCameraConfig();
			const res = await fetch(`${backendHttpBaseUrl}/api/cameras/list`);
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
			cameraError = e.message ?? 'Failed to scan cameras';
		} finally {
			cameraLoading = false;
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

	async function selectCamera(role: CameraRole, cameraIndex: number) {
		await saveCameraRole(role, cameraIndex);
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
			return getArcPolygon(channel);
		}
		return sortPolygon(userPoints[channel]).map((pt) => [pt[0], pt[1]]);
	}

	function getChannelCenter(channel: Channel): Point | null {
		if (isArcChannel(channel)) {
			return arcParams[channel]?.center ?? null;
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

	function hitArcHandle(channel: ArcChannel, point: Point): ArcHandle | null {
		const handles = getArcHandles(channel);
		if (!handles) return null;
		const order: ArcHandle[] = ['start', 'end', 'outer', 'inner', 'center'];
		for (const handle of order) {
			if (pointDistance(point, handles[handle]) <= HANDLE_HIT_RADIUS) {
				return handle;
			}
		}
		return null;
	}

	function hitPolygonVertex(channel: Exclude<Channel, ArcChannel>, point: Point): boolean {
		return userPoints[channel].some(
			(vertex) => pointDistance(point, [vertex[0], vertex[1]]) <= VERTEX_HIT_RADIUS
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
			const shape = getShapePoints(currentChannel);
			canvasCursor =
				shape.length >= 3 && pointInPolygon(point[0], point[1], shape) ? 'grab' : 'crosshair';
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
								: handle === 'start'
									? 'arc-start'
									: 'arc-end',
					channel: currentChannel,
					orig: copyArcParams(params)
				};
				canvasCursor = 'grabbing';
				return;
			}

			const shape = getShapePoints(currentChannel);
			if (shape.length >= 3 && pointInPolygon(point[0], point[1], shape) && !e.shiftKey && params) {
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

		const shape = getShapePoints(currentChannel);
		if (shape.length >= 3 && pointInPolygon(point[0], point[1], shape) && !e.shiftKey) {
			dragState = {
				kind: 'polygon-shape',
				channel: currentChannel,
				start: point,
				origPts: userPoints[currentChannel].map((pt) => [pt[0], pt[1]]),
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
			case 'arc-start': {
				didDrag = true;
				setArc(dragState.channel, {
					...dragState.orig,
					startAngle: angleFromCenter(point, dragState.orig.center)
				});
				break;
			}
			case 'arc-end': {
				didDrag = true;
				setArc(dragState.channel, {
					...dragState.orig,
					endAngle: angleFromCenter(point, dragState.orig.center)
				});
				break;
			}
			case 'section-zero': {
				didDrag = true;
				sectionZeroPoints[dragState.channel] = point;
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

		const shape = getShapePoints(currentChannel);
		if (shape.length >= 3 && pointInPolygon(point[0], point[1], shape)) return;
		userPoints[currentChannel] = [...userPoints[currentChannel], [point[0], point[1]]];
	}

	function onContextMenu(e: MouseEvent) {
		if (!editingZone) return;
		e.preventDefault();
		if (isArcChannel(currentChannel)) {
			return;
		}

		const point = canvasCoords(e);
		const pts = userPoints[currentChannel];
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
			userPoints[currentChannel] = pts.filter((_, idx) => idx !== minIdx);
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

		const pts = userPoints[currentChannel];
		if (pts.length < 3) return;
		const cx = pts.reduce((sum, pt) => sum + pt[0], 0) / pts.length;
		const cy = pts.reduce((sum, pt) => sum + pt[1], 0) / pts.length;
		userPoints[currentChannel] = pts.map((pt) => [
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

		const polygon = buildArcPolygon(params);
		const color = CHANNEL_COLORS[channel];
		const alpha = active ? 1 : 0.35;

		ctx.beginPath();
		ctx.moveTo(polygon[0][0], polygon[0][1]);
		for (let i = 1; i < polygon.length; i++) {
			ctx.lineTo(polygon[i][0], polygon[i][1]);
		}
		ctx.closePath();
		ctx.fillStyle = active ? `${color}22` : `${color}0d`;
		ctx.fill();
		ctx.strokeStyle = color;
		ctx.globalAlpha = alpha;
		ctx.lineWidth = active ? 2 : 1;
		ctx.stroke();
		ctx.globalAlpha = 1;

		const handles = getArcHandles(channel);
		if (!handles) return;

		if (active && editingZone) {
			ctx.strokeStyle = `${color}aa`;
			ctx.lineWidth = 1;
			ctx.beginPath();
			ctx.moveTo(params.center[0], params.center[1]);
			ctx.lineTo(handles.start[0], handles.start[1]);
			ctx.moveTo(params.center[0], params.center[1]);
			ctx.lineTo(handles.end[0], handles.end[1]);
			ctx.moveTo(params.center[0], params.center[1]);
			ctx.lineTo(handles.inner[0], handles.inner[1]);
			ctx.moveTo(params.center[0], params.center[1]);
			ctx.lineTo(handles.outer[0], handles.outer[1]);
			ctx.stroke();

			drawHandle(ctx, handles.center, color, '#111', 'Center');
			drawHandle(ctx, handles.inner, color, '#111', 'Inner');
			drawHandle(ctx, handles.outer, color, '#111', 'Outer');
			drawHandle(ctx, handles.start, color, '#111', 'Start', [-34, -20]);
			drawHandle(ctx, handles.end, color, '#111', 'Exit', [34, -20]);
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

	function drawChannel(ctx: CanvasRenderingContext2D, channel: Channel, active: boolean) {
		if (isArcChannel(channel)) {
			drawArcChannel(ctx, channel, active);
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

			for (const channel of ARC_CHANNELS) {
				const savedUserPts = channelUserPts[channel];
				if (Array.isArray(savedUserPts)) {
					userPoints[channel] = savedUserPts;
				}

				const savedArc = parseArcParams(channelArcParams[channel]);
				if (savedArc) {
					arcParams[channel] = savedArc;
					continue;
				}

				const polygonKey = `${channel}_channel`;
				const fallbackPts = savedUserPts ?? channelPolygons[polygonKey];
				const derived = Array.isArray(fallbackPts) ? deriveArcParamsFromPolygon(fallbackPts) : null;
				if (derived) {
					arcParams[channel] = derived;
				}
			}

			if (Array.isArray(channelUserPts.carousel)) {
				userPoints.carousel = channelUserPts.carousel;
			} else if (Array.isArray(channelPolygons.carousel)) {
				userPoints.carousel = channelPolygons.carousel;
			}

			const sectionZero = channelData.section_zero_pts ?? {};
			if (Array.isArray(sectionZero.second)) sectionZeroPoints.second = sectionZero.second;
			if (Array.isArray(sectionZero.third)) sectionZeroPoints.third = sectionZero.third;

			const classificationData = data.classification ?? {};
			const classUserPts = classificationData.user_pts ?? {};
			const classPolygons = classificationData.polygons ?? {};
			if (Array.isArray(classUserPts.class_top)) {
				userPoints.class_top = classUserPts.class_top;
			} else if (Array.isArray(classPolygons.top)) {
				userPoints.class_top = classPolygons.top;
			}
			if (Array.isArray(classUserPts.class_bottom)) {
				userPoints.class_bottom = classUserPts.class_bottom;
			} else if (Array.isArray(classPolygons.bottom)) {
				userPoints.class_bottom = classPolygons.bottom;
			}
		} catch {
			// ignore
		}
	}

	async function saveAll(): Promise<boolean> {
		saving = true;
		try {
			const polygons: Record<string, number[][]> = {};
			const user_pts: Record<string, number[][]> = {};
			const arc_params: Record<string, ArcParamsPayload> = {};

			for (const channel of FEEDER_CHANNELS) {
				const key = channel === 'carousel' ? 'carousel' : `${channel}_channel`;
				const points = getShapePoints(channel).map((pt) => [Math.round(pt[0]), Math.round(pt[1])]);
				polygons[key] = points;
				user_pts[channel] = points;
				if (isArcChannel(channel) && arcParams[channel]) {
					arc_params[channel] = serializeArcParams(arcParams[channel]);
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
			for (const channel of CLASSIFICATION_CHANNELS) {
				const key = channel === 'class_top' ? 'top' : 'bottom';
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

			const res = await fetch(`${backendHttpBaseUrl}/api/polygons`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({
					channel: {
						polygons,
						user_pts,
						arc_params,
						channel_angles,
						section_zero_pts,
						resolution: [CANVAS_W, CANVAS_H]
					},
					classification: {
						polygons: class_polygons,
						user_pts: class_user_pts,
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
		userPoints[currentChannel] = [];
		statusMsg = 'Zone reset. Save to keep it.';
	}

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
		class="dark:border-border-dark dark:bg-surface-dark -mx-4 -mt-4 flex flex-wrap items-center gap-3 border-b border-border bg-surface px-4 py-3"
	>
		<div class="flex min-w-0 flex-1 flex-wrap items-center gap-2">
			{#if channels.length > 1}
				{#each channels as channel}
					{@const active = currentChannel === channel}
					{@const isSep =
						channel === 'class_top' &&
						channels.some((item) => item === 'second' || item === 'third' || item === 'carousel')}
					{#if isSep}
						<div class="dark:bg-border-dark h-6 w-px bg-border"></div>
					{/if}
					<button
						onclick={() => selectChannel(channel)}
						class="border px-3 py-1.5 text-xs font-medium transition-colors"
						style:border-color={active ? CHANNEL_COLORS[channel] : undefined}
						class:bg-surface={active}
						class:dark:bg-surface-dark={active}
						class:bg-bg={!active}
						class:dark:bg-bg-dark={!active}
						class:text-text={true}
						class:dark:text-text-dark={true}
					>
						{CHANNEL_LABELS[channel]}
					</button>
				{/each}
			{:else}
				<h2 class="dark:text-text-dark text-base font-semibold text-text">
					{CHANNEL_LABELS[currentChannel]}
				</h2>
			{/if}

			<div
				class="dark:bg-bg-dark dark:text-text-muted-dark min-w-0 rounded-full bg-bg px-3 py-1 text-xs text-text-muted"
			>
				<span class="dark:text-text-dark font-medium text-text">Source:</span>
				<span class="ml-1 truncate">{formatSource(currentAssignment())}</span>
			</div>

			{#if statusMsg}
				<div
					class={`min-w-0 rounded-full border px-3 py-1 text-xs ${
						statusMsg.startsWith('Error:')
							? 'border-red-400 bg-red-50 text-red-600 dark:border-red-600 dark:bg-red-900/20 dark:text-red-400'
							: 'dark:bg-bg-dark dark:text-text-muted-dark border-border bg-bg text-text-muted'
					}`}
				>
					<span class="truncate">{statusMsg}</span>
				</div>
			{/if}
		</div>

		<div class="ml-auto flex flex-wrap items-center gap-2">
			<button
				onclick={openCameraPicker}
				disabled={editingZone}
				class="dark:border-border-dark dark:bg-bg-dark dark:text-text-dark dark:hover:bg-bg-dark/80 inline-flex cursor-pointer items-center gap-2 border border-border bg-bg px-3 py-1.5 text-sm text-text transition-colors hover:bg-bg/80 disabled:cursor-not-allowed disabled:opacity-50"
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
						: 'dark:border-border-dark dark:bg-bg-dark dark:text-text-dark dark:hover:bg-bg-dark/80 border-border bg-bg text-text hover:bg-bg/80'
				}`}
			>
				<SlidersHorizontal size={15} />
				<span>{activeSidebar === 'picture' ? 'Hide Picture' : 'Picture Settings'}</span>
			</button>

			{#if editingZone}
				<button
					onclick={resetCurrentChannel}
					class="dark:border-border-dark dark:bg-bg-dark dark:text-text-dark dark:hover:bg-bg-dark/80 inline-flex cursor-pointer items-center gap-2 border border-border bg-bg px-3 py-1.5 text-sm text-text transition-colors hover:bg-bg/80"
				>
					<RotateCcw size={15} />
					<span>Reset</span>
				</button>
				<button
					onclick={cancelEditing}
					class="dark:border-border-dark dark:bg-bg-dark dark:text-text-dark dark:hover:bg-bg-dark/80 inline-flex cursor-pointer items-center gap-2 border border-border bg-bg px-3 py-1.5 text-sm text-text transition-colors hover:bg-bg/80"
				>
					<X size={15} />
					<span>Cancel</span>
				</button>
				<button
					onclick={saveAll}
					disabled={saving}
					class="inline-flex cursor-pointer items-center gap-2 border border-emerald-500 bg-emerald-500/15 px-3 py-1.5 text-sm text-emerald-700 transition-colors hover:bg-emerald-500/25 disabled:cursor-not-allowed disabled:opacity-50 dark:text-emerald-300"
				>
					<Check size={15} />
					<span>{saving ? 'Saving...' : 'Save Zone'}</span>
				</button>
			{:else}
				<button
					onclick={beginEditing}
					disabled={currentAssignment() === null}
					class="inline-flex cursor-pointer items-center gap-2 border border-blue-500 bg-blue-500/15 px-3 py-1.5 text-sm text-blue-700 transition-colors hover:bg-blue-500/25 disabled:cursor-not-allowed disabled:opacity-50 dark:text-blue-300"
				>
					<Pencil size={15} />
					<span>Edit Zone</span>
				</button>
			{/if}
		</div>
	</div>

	<!-- Help text -->
	<div class="dark:text-text-muted-dark -mx-4 px-4 py-2 text-xs text-text-muted">
		Use the assigned camera as the main view, tune picture settings from the sidebar, and only unlock zone editing when you want to change the mask.
	</div>

	<!-- Content -->
	<div class="-mx-4 -mb-4 px-4 pb-4">
	<div
		class={`grid gap-4 ${activeSidebar ? 'xl:grid-cols-[minmax(0,1fr)_20rem] xl:items-start' : ''}`}
	>
		<div class="flex min-w-0 flex-col gap-3">
			<div class="relative overflow-hidden bg-black">
				{#if hasDraftPicturePreview() && getPicturePreview()}
					{@const currentPreview = getPicturePreview()!}
					<svg
						class="pointer-events-none absolute h-0 w-0 overflow-hidden"
						aria-hidden="true"
						focusable="false"
					>
						<defs>
							<filter id={previewFilterId()} color-interpolation-filters="sRGB">
								<feColorMatrix
									in="SourceGraphic"
									type="saturate"
									values={String(inverseSaturation(currentPreview.saved))}
									result="previewInverseSaturation"
								/>
								<feComponentTransfer in="previewInverseSaturation" result="previewInverseGamma">
									<feFuncR
										type="gamma"
										amplitude="1"
										exponent={String(inverseGammaExponent(currentPreview.saved))}
										offset="0"
									/>
									<feFuncG
										type="gamma"
										amplitude="1"
										exponent={String(inverseGammaExponent(currentPreview.saved))}
										offset="0"
									/>
									<feFuncB
										type="gamma"
										amplitude="1"
										exponent={String(inverseGammaExponent(currentPreview.saved))}
										offset="0"
									/>
								</feComponentTransfer>
								<feComponentTransfer in="previewInverseGamma" result="previewInverseLinear">
									<feFuncR
										type="linear"
										slope={String(inverseLinearSlope(currentPreview.saved))}
										intercept={String(inverseLinearIntercept(currentPreview.saved))}
									/>
									<feFuncG
										type="linear"
										slope={String(inverseLinearSlope(currentPreview.saved))}
										intercept={String(inverseLinearIntercept(currentPreview.saved))}
									/>
									<feFuncB
										type="linear"
										slope={String(inverseLinearSlope(currentPreview.saved))}
										intercept={String(inverseLinearIntercept(currentPreview.saved))}
									/>
								</feComponentTransfer>
								<feComponentTransfer in="previewInverseLinear" result="previewDraftLinear">
									<feFuncR
										type="linear"
										slope={String(normalizeLinearSlope(currentPreview.draft.contrast))}
										intercept={String(forwardLinearIntercept(currentPreview.draft))}
									/>
									<feFuncG
										type="linear"
										slope={String(normalizeLinearSlope(currentPreview.draft.contrast))}
										intercept={String(forwardLinearIntercept(currentPreview.draft))}
									/>
									<feFuncB
										type="linear"
										slope={String(normalizeLinearSlope(currentPreview.draft.contrast))}
										intercept={String(forwardLinearIntercept(currentPreview.draft))}
									/>
								</feComponentTransfer>
								<feComponentTransfer in="previewDraftLinear" result="previewDraftGamma">
									<feFuncR
										type="gamma"
										amplitude="1"
										exponent={String(forwardGammaExponent(currentPreview.draft))}
										offset="0"
									/>
									<feFuncG
										type="gamma"
										amplitude="1"
										exponent={String(forwardGammaExponent(currentPreview.draft))}
										offset="0"
									/>
									<feFuncB
										type="gamma"
										amplitude="1"
										exponent={String(forwardGammaExponent(currentPreview.draft))}
										offset="0"
									/>
								</feComponentTransfer>
								<feColorMatrix
									in="previewDraftGamma"
									type="saturate"
									values={String(normalizeSaturationValue(currentPreview.draft.saturation))}
								/>
							</filter>
						</defs>
					</svg>
				{/if}

				<div class="relative aspect-video">
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
								src={streamUrl(currentChannel)}
								alt={CHANNEL_LABELS[currentChannel]}
								class="absolute inset-0 h-full w-full object-contain"
								style={feedImageStyle(currentChannel)}
							/>
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
				</div>
			</div>
		</div>

		{#if editingZone && activeSidebar === 'zone'}
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
					onClose={() => {
						clearPicturePreview(currentRole());
						activeSidebar = null;
					}}
					onSaved={() => {
						clearPicturePreview(currentRole());
						activeSidebar = null;
						feedRevision += 1;
						statusMsg = 'Picture settings updated.';
					}}
				/>
			{/key}
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
					class="border border-red-400 bg-red-50 px-3 py-2 text-sm text-red-600 dark:border-red-600 dark:bg-red-900/20 dark:text-red-400"
				>
					{cameraError}
				</div>
			{/if}

			{#if cameraLoading}
				<div class="dark:text-text-muted-dark py-8 text-center text-sm text-text-muted">
					Scanning cameras...
				</div>
			{:else}
				{@const hasAnyCameras = usbCameras.length > 0 || (ROLE_SUPPORTS_URL[currentRole()] && networkCameras.length > 0)}
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
								disabled={usedByOther || cameraSaving}
								class="group relative overflow-hidden text-left transition-all {isSelected
									? 'ring-2 ring-blue-500'
									: usedByOther
										? 'cursor-not-allowed opacity-40'
										: 'hover:ring-2 hover:ring-blue-300 dark:hover:ring-blue-600'}"
							>
								{#if cam.preview_available === false}
									<div
										class="dark:bg-bg-dark dark:text-text-muted-dark flex aspect-video items-center justify-center bg-bg text-center text-xs text-text-muted"
									>
										No preview
									</div>
								{:else}
									<img
										src={cameraIndexPreviewUrl(cam.index)}
										alt={cam.name ?? `Camera ${cam.index}`}
										class="block aspect-video w-full object-cover"
									/>
								{/if}
								<div
									class="absolute right-0 bottom-0 left-0 bg-gradient-to-t from-black/80 to-transparent px-2 pt-4 pb-1.5 text-[11px] text-white"
								>
									<div class="font-medium">{cam.name ?? `Camera ${cam.index}`}</div>
									{#if cam.name && cam.width > 0 && cam.height > 0}
										<div class="text-white/70">{cam.width}x{cam.height}</div>
									{:else if !cam.name}
										<div class="text-white/70">
											Index {cam.index}{#if cam.width > 0 && cam.height > 0} · {cam.width}x{cam.height}{/if}
										</div>
									{/if}
								</div>
								{#if isSelected}
									<div class="absolute top-1.5 right-1.5 rounded-sm bg-blue-500 px-1.5 py-0.5 text-[10px] font-medium text-white">
										Active
									</div>
								{:else if usedByOther}
									<div class="absolute top-1.5 right-1.5 rounded-sm bg-black/70 px-1.5 py-0.5 text-[10px] font-medium text-white">
										In use
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
									onclick={() => saveCameraRole(role, cam.source)}
									disabled={usedByOther || cameraSaving}
									class="group relative overflow-hidden text-left transition-all {isSelected
										? 'ring-2 ring-blue-500'
										: usedByOther
											? 'cursor-not-allowed opacity-40'
											: 'hover:ring-2 hover:ring-blue-300 dark:hover:ring-blue-600'}"
								>
									<img
										src={discoveredPreviewUrl(cam)}
										alt={cam.name}
										class="block aspect-video w-full object-cover"
									/>
									<div
										class="absolute right-0 bottom-0 left-0 bg-gradient-to-t from-black/80 to-transparent px-2 pt-4 pb-1.5 text-[11px] text-white"
									>
										<div class="font-medium">{cam.name}</div>
										<div class="text-white/70">
											{cam.host}:{cam.port}{#if cam.lens_facing} · {cam.lens_facing}{/if}
										</div>
									</div>
									{#if isSelected}
										<div class="absolute top-1.5 right-1.5 rounded-sm bg-blue-500 px-1.5 py-0.5 text-[10px] font-medium text-white">
											Active
										</div>
									{:else if usedByOther}
										<div class="absolute top-1.5 right-1.5 rounded-sm bg-black/70 px-1.5 py-0.5 text-[10px] font-medium text-white">
											In use
										</div>
									{/if}
								</button>
							{/each}
						{/if}
					</div>
				{:else}
					<div
						class="dark:border-border-dark dark:text-text-muted-dark border border-dashed border-border px-4 py-8 text-center text-sm text-text-muted"
					>
						No cameras detected. Click Refresh to scan again.
					</div>
				{/if}
			{/if}

			<div class="dark:border-border-dark flex items-center justify-between border-t border-border pt-3">
				<button
					onclick={refreshCameras}
					disabled={cameraLoading}
					class="dark:text-text-muted-dark inline-flex cursor-pointer items-center gap-1.5 text-xs text-text-muted transition-colors hover:text-text disabled:cursor-not-allowed disabled:opacity-50 dark:hover:text-text-dark"
				>
					<RefreshCw size={13} />
					<span>{cameraLoading ? 'Scanning...' : 'Refresh'}</span>
				</button>
				{#if currentAssignment() !== null}
					<button
						onclick={() => saveCameraRole(currentRole(), null)}
						disabled={cameraSaving}
						class="cursor-pointer text-xs text-red-500 transition-colors hover:text-red-600 disabled:cursor-not-allowed disabled:opacity-50 dark:text-red-400 dark:hover:text-red-300"
					>
						Remove current camera
					</button>
				{/if}
			</div>
		</div>
	</Modal>
</div><!-- /content -->
</div>
