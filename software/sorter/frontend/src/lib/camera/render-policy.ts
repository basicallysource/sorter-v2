export type CameraFeedRenderPolicyInput = {
	direct: boolean;
	annotated: boolean;
	cropped: boolean;
	zones: boolean;
	usingWebrtc: boolean;
};

export type CameraFeedRenderPolicy = {
	browserMetadataCandidate: boolean;
	browserOverlayCandidate: boolean;
	browserCropCandidate: boolean;
	metadataWebsocketCandidate: boolean;
	serverAnnotated: boolean;
	serverShowRegions: boolean;
	serverDashboard: boolean;
};

export function cameraFeedRenderPolicy({
	direct,
	annotated,
	cropped,
	zones,
	usingWebrtc
}: CameraFeedRenderPolicyInput): CameraFeedRenderPolicy {
	const browserMetadataCandidate = !direct && (annotated || cropped || zones);
	const browserOverlayCandidate = (annotated || zones) && !direct;
	const browserCropCandidate = cropped && !direct;
	return {
		browserMetadataCandidate,
		browserOverlayCandidate,
		browserCropCandidate,
		metadataWebsocketCandidate: browserMetadataCandidate && !usingWebrtc,
		serverAnnotated: annotated && !browserOverlayCandidate,
		serverShowRegions: zones && !browserOverlayCandidate,
		serverDashboard: cropped && direct
	};
}
