export type CameraFeedMetadataFrame = {
	width?: number;
	height?: number;
	timestamp?: number;
	fps?: number;
	fourcc?: string;
};

export type CameraFeedMetadataFrameTransform = {
	kind?: string;
	source_rect?: CameraFeedMetadataViewport | null;
	output_frame?: CameraFeedMetadataFrame | null;
};

export type CameraFeedMetadataCoordinateSpace = {
	name?: string;
	units?: string;
	origin?: string;
	width?: number;
	height?: number;
	frame?: string;
	overlays?: string;
	crop?: string;
	transport?: CameraFeedMetadataFrameTransform | null;
	inference?: CameraFeedMetadataFrameTransform | null;
};

export type CameraFeedMetadataOverlay = {
	type?: string;
	category?: string;
	label?: string;
	bbox?: unknown;
	polygon?: unknown;
	poly_key?: string;
};

export type CameraFeedMetadataViewport = {
	x?: number;
	y?: number;
	width?: number;
	height?: number;
	bbox?: unknown;
};

export type CameraFeedMetadataCrop = {
	available?: boolean;
	kind?: string;
	viewport?: CameraFeedMetadataViewport | null;
	input_frame?: CameraFeedMetadataFrame | null;
	output_frame?: CameraFeedMetadataFrame | null;
	rotation_deg?: number;
};

export type CameraFeedMetadata = {
	message_type?: string;
	schema_version?: number;
	ok?: boolean;
	role?: string;
	requested_role?: string;
	config_role?: string;
	physical_source?: string;
	frame?: CameraFeedMetadataFrame | null;
	coordinate_space?: CameraFeedMetadataCoordinateSpace | null;
	transport_frame?: CameraFeedMetadataFrame | null;
	inference_frame?: CameraFeedMetadataFrame | null;
	crop?: CameraFeedMetadataCrop | null;
	overlays?: CameraFeedMetadataOverlay[];
};

export type CameraFeedMetadataDecision =
	| {
			action: 'accept';
			metadata: CameraFeedMetadata;
			timestamp: number | null;
	  }
	| {
			action: 'clear';
			reason: string;
	  }
	| {
			action: 'ignore';
			reason: string;
	  };

function finiteTimestamp(value: unknown): number | null {
	return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

export function cameraFeedMetadataTimestamp(payload: CameraFeedMetadata | null): number | null {
	return finiteTimestamp(payload?.frame?.timestamp);
}

export function decideCameraFeedMetadataUpdate(
	payload: unknown,
	currentTimestamp: number | null
): CameraFeedMetadataDecision {
	if (payload === null || typeof payload !== 'object') {
		return { action: 'clear', reason: 'metadata payload is not an object' };
	}
	const parsed = payload as CameraFeedMetadata;
	if (!parsed?.ok) {
		return { action: 'clear', reason: 'metadata payload is not ok' };
	}
	if (
		'message_type' in parsed &&
		parsed.message_type !== undefined &&
		parsed.message_type !== 'camera.feed_metadata'
	) {
		return { action: 'ignore', reason: 'metadata message type does not match camera.feed_metadata' };
	}

	const timestamp = cameraFeedMetadataTimestamp(parsed);
	if (timestamp !== null && currentTimestamp !== null && timestamp < currentTimestamp) {
		return { action: 'ignore', reason: 'metadata frame timestamp is older than current frame' };
	}
	return { action: 'accept', metadata: parsed, timestamp };
}
