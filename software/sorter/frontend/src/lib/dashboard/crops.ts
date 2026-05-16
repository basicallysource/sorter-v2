type Point = [number, number];

type CropViewBox = {
	x: number;
	y: number;
	width: number;
	height: number;
};

type PolygonPayload = {
	channel?: {
		polygons?: Record<string, unknown>;
		arc_params?: Record<string, unknown>;
		quad_params?: Record<string, unknown>;
		resolution?: [unknown, unknown];
	};
	classification?: {
		polygons?: Record<string, unknown>;
		quad_params?: Record<string, unknown>;
		resolution?: [unknown, unknown];
	};
};

type PerKeyResolutionMap = Record<string, { resolution?: unknown } | undefined>;

const POLYGON_KEY_TO_PARAM_KEY: Record<string, string> = {
	second_channel: 'second',
	third_channel: 'third',
	classification_channel: 'classification_channel',
	carousel: 'carousel',
	top: 'class_top',
	bottom: 'class_bottom'
};

export type DashboardFeedCrop = {
	sourceWidth: number;
	sourceHeight: number;
	viewBox: CropViewBox;
	polygons: Point[][];
	rotationDeg?: number;
	rotationCenter?: Point;
};

const DEFAULT_SOURCE_WIDTH = 1920;
const DEFAULT_SOURCE_HEIGHT = 1080;
const VIEWBOX_PADDING_FACTOR = 0.12;
const MIN_VIEWBOX_PADDING = 44;

function centerOfViewBox(box: CropViewBox): Point {
	return [box.x + box.width / 2, box.y + box.height / 2];
}

function rotatePoint([x, y]: Point, center: Point, degrees: number): Point {
	const radians = (degrees * Math.PI) / 180;
	const cos = Math.cos(radians);
	const sin = Math.sin(radians);
	const dx = x - center[0];
	const dy = y - center[1];
	return [center[0] + dx * cos - dy * sin, center[1] + dx * sin + dy * cos];
}

function rotatePolygons(polygons: Point[][], center: Point, degrees: number): Point[][] {
	if (Math.abs(degrees) < 0.001) return polygons;
	return polygons.map((polygon) => polygon.map((point) => rotatePoint(point, center, degrees)));
}

function nearestAxisAlignedRotation(angleDeg: number): number {
	const normalized = ((angleDeg % 180) + 180) % 180;
	const targets = [0, 90, 180];
	let bestTarget = targets[0];
	let bestDistance = Number.POSITIVE_INFINITY;
	for (const target of targets) {
		const distance = Math.abs(target - normalized);
		if (distance < bestDistance) {
			bestDistance = distance;
			bestTarget = target;
		}
	}
	let rotation = bestTarget - normalized;
	if (rotation > 90) rotation -= 180;
	if (rotation < -90) rotation += 180;
	return rotation;
}

function straightenRotationForRole(role: string, polygons: Point[][]): number {
	if (!['carousel', 'classification_top', 'classification_bottom'].includes(role)) return 0;
	if (polygons.length !== 1 || polygons[0].length < 4) return 0;

	const polygon = polygons[0];
	let longestEdgeAngle = 0;
	let longestEdgeLength = -1;

	for (let index = 0; index < polygon.length; index += 1) {
		const current = polygon[index];
		const next = polygon[(index + 1) % polygon.length];
		const dx = next[0] - current[0];
		const dy = next[1] - current[1];
		const length = Math.hypot(dx, dy);
		if (length > longestEdgeLength) {
			longestEdgeLength = length;
			longestEdgeAngle = (Math.atan2(dy, dx) * 180) / Math.PI;
		}
	}

	return nearestAxisAlignedRotation(longestEdgeAngle);
}

function positiveNumber(value: unknown, fallback: number): number {
	return typeof value === 'number' && Number.isFinite(value) && value > 0 ? value : fallback;
}

function readResolution(resolution: unknown): { width: number; height: number } {
	const tuple = Array.isArray(resolution) ? resolution : undefined;
	return {
		width: positiveNumber(tuple?.[0], DEFAULT_SOURCE_WIDTH),
		height: positiveNumber(tuple?.[1], DEFAULT_SOURCE_HEIGHT)
	};
}

function readResolutionStrict(resolution: unknown): { width: number; height: number } | null {
	if (!Array.isArray(resolution) || resolution.length < 2) return null;
	const [rawWidth, rawHeight] = resolution;
	if (typeof rawWidth !== 'number' || typeof rawHeight !== 'number') return null;
	if (!Number.isFinite(rawWidth) || !Number.isFinite(rawHeight)) return null;
	if (rawWidth <= 0 || rawHeight <= 0) return null;
	return { width: rawWidth, height: rawHeight };
}

function resolutionForPolygonKey(
	data: PolygonPayload['channel'] | PolygonPayload['classification'] | undefined,
	polygonKey: string,
	fallbackResolution: { width: number; height: number }
): { width: number; height: number } {
	const paramKey = POLYGON_KEY_TO_PARAM_KEY[polygonKey];
	if (!paramKey || !data) return fallbackResolution;
	const arcParams = ((data as PolygonPayload['channel'])?.arc_params ?? {}) as PerKeyResolutionMap;
	const arc = readResolutionStrict(arcParams[paramKey]?.resolution);
	if (arc) return arc;
	const quadParams = (data.quad_params ?? {}) as PerKeyResolutionMap;
	const quad = readResolutionStrict(quadParams[paramKey]?.resolution);
	if (quad) return quad;
	return fallbackResolution;
}

function readPolygon(raw: unknown): Point[] {
	if (!Array.isArray(raw)) return [];
	return raw
		.map((point) => {
			if (!Array.isArray(point) || point.length < 2) return null;
			const [x, y] = point;
			if (typeof x !== 'number' || typeof y !== 'number' || !Number.isFinite(x) || !Number.isFinite(y)) {
				return null;
			}
			return [x, y] as Point;
		})
		.filter((point): point is Point => point !== null);
}

function bboxForPolygons(polygons: Point[][]): CropViewBox | null {
	let minX = Number.POSITIVE_INFINITY;
	let minY = Number.POSITIVE_INFINITY;
	let maxX = Number.NEGATIVE_INFINITY;
	let maxY = Number.NEGATIVE_INFINITY;

	for (const polygon of polygons) {
		for (const [x, y] of polygon) {
			minX = Math.min(minX, x);
			minY = Math.min(minY, y);
			maxX = Math.max(maxX, x);
			maxY = Math.max(maxY, y);
		}
	}

	if (!Number.isFinite(minX) || !Number.isFinite(minY) || !Number.isFinite(maxX) || !Number.isFinite(maxY)) {
		return null;
	}

	return {
		x: minX,
		y: minY,
		width: Math.max(1, maxX - minX),
		height: Math.max(1, maxY - minY)
	};
}

function paddedViewBox(
	bbox: CropViewBox,
	sourceWidth: number,
	sourceHeight: number
): CropViewBox {
	const paddingX = Math.max(MIN_VIEWBOX_PADDING, bbox.width * VIEWBOX_PADDING_FACTOR);
	const paddingY = Math.max(MIN_VIEWBOX_PADDING, bbox.height * VIEWBOX_PADDING_FACTOR);
	const x = Math.max(0, bbox.x - paddingX);
	const y = Math.max(0, bbox.y - paddingY);
	const maxX = Math.min(sourceWidth, bbox.x + bbox.width + paddingX);
	const maxY = Math.min(sourceHeight, bbox.y + bbox.height + paddingY);

	return {
		x,
		y,
		width: Math.max(1, maxX - x),
		height: Math.max(1, maxY - y)
	};
}

function polygonsForKeys(source: Record<string, unknown> | undefined, keys: string[]): Point[][] {
	return keys
		.map((key) => readPolygon(source?.[key]))
		.filter((polygon) => polygon.length >= 3);
}

function buildCrop(
	role: string,
	polygons: Point[][],
	sourceWidth: number,
	sourceHeight: number
): DashboardFeedCrop | null {
	if (polygons.length === 0) return null;
	const bbox = bboxForPolygons(polygons);
	if (!bbox) return null;
	const rotationCenter = centerOfViewBox(bbox);
	const rotationDeg = straightenRotationForRole(role, polygons);
	const displayPolygons = rotatePolygons(polygons, rotationCenter, rotationDeg);
	const displayBbox = bboxForPolygons(displayPolygons);
	if (!displayBbox) return null;

	return {
		sourceWidth,
		sourceHeight,
		viewBox: paddedViewBox(displayBbox, sourceWidth, sourceHeight),
		polygons: displayPolygons,
		rotationDeg,
		rotationCenter
	};
}

export function buildDashboardFeedCrops(payload: unknown): Record<string, DashboardFeedCrop | null> {
	const data = (payload ?? {}) as PolygonPayload;
	const channelData = data.channel;
	const classificationData = data.classification;
	const channelResolution = readResolution(channelData?.resolution);
	const classificationResolution = readResolution(classificationData?.resolution);
	const channelPolygons = data.channel?.polygons;
	const classificationPolygons = data.classification?.polygons;

	const c2 = polygonsForKeys(channelPolygons, ['second_channel']);
	const c3 = polygonsForKeys(channelPolygons, ['third_channel']);
	const carousel = polygonsForKeys(channelPolygons, ['carousel']);
	const classificationChannel = polygonsForKeys(channelPolygons, ['classification_channel']);
	const feeder = polygonsForKeys(channelPolygons, [
		'second_channel',
		'third_channel',
		'carousel',
		'classification_channel'
	]);
	const classificationTop = polygonsForKeys(classificationPolygons, ['top']);
	const classificationBottom = polygonsForKeys(classificationPolygons, ['bottom']);

	const c2Resolution = resolutionForPolygonKey(channelData, 'second_channel', channelResolution);
	const c3Resolution = resolutionForPolygonKey(channelData, 'third_channel', channelResolution);
	const carouselResolution = resolutionForPolygonKey(channelData, 'carousel', channelResolution);
	const classificationChannelResolution = resolutionForPolygonKey(
		channelData,
		'classification_channel',
		channelResolution
	);
	const classificationTopResolution = resolutionForPolygonKey(
		classificationData,
		'top',
		classificationResolution
	);
	const classificationBottomResolution = resolutionForPolygonKey(
		classificationData,
		'bottom',
		classificationResolution
	);

	return {
		feeder: buildCrop('feeder', feeder, channelResolution.width, channelResolution.height),
		c_channel_2: buildCrop('c_channel_2', c2, c2Resolution.width, c2Resolution.height),
		c_channel_3: buildCrop('c_channel_3', c3, c3Resolution.width, c3Resolution.height),
		carousel: buildCrop('carousel', carousel, carouselResolution.width, carouselResolution.height),
		classification_channel: buildCrop(
			'classification_channel',
			classificationChannel,
			classificationChannelResolution.width,
			classificationChannelResolution.height
		),
		classification_top: buildCrop(
			'classification_top',
			classificationTop,
			classificationTopResolution.width,
			classificationTopResolution.height
		),
		classification_bottom: buildCrop(
			'classification_bottom',
			classificationBottom,
			classificationBottomResolution.width,
			classificationBottomResolution.height
		)
	};
}
