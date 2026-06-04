import type { CameraWebrtcStatus } from './webrtc-session';

export function webrtcTransportCandidate({
	preferWebrtc,
	isConfigured
}: {
	preferWebrtc: boolean;
	isConfigured: boolean;
}): boolean {
	return preferWebrtc && isConfigured;
}

export function legacyMjpegFallbackAllowed({
	webrtcCandidate,
	webrtcTargetReady,
	webrtcStatus
}: {
	webrtcCandidate: boolean;
	webrtcTargetReady: boolean;
	webrtcStatus: CameraWebrtcStatus;
}): boolean {
	if (!webrtcCandidate) return true;
	return !webrtcTargetReady && webrtcStatus === 'unavailable';
}
