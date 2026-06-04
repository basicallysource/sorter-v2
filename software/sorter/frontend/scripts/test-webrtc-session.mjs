import assert from 'node:assert/strict';
import { createServer } from 'vite';

const server = await createServer({
	appType: 'custom',
	logLevel: 'error',
	server: { middlewareMode: true }
});

function makeSubscriber() {
	const states = [];
	const metadata = [];
	return {
		states,
		metadata,
		subscriber: {
			onState(state) {
				states.push(state);
			},
			onMetadata(payload) {
				metadata.push(payload);
			}
		}
	};
}

function wait(ms = 0) {
	return new Promise((resolve) => setTimeout(resolve, ms));
}

async function waitUntil(predicate, label, details = () => '') {
	const deadline = Date.now() + 1000;
	while (Date.now() < deadline) {
		if (predicate()) return;
		await wait(5);
	}
	const extra = details();
	throw new Error(`Timed out waiting for ${label}${extra ? `: ${extra}` : ''}`);
}

function sessionsResponse(payload) {
	return new Response(JSON.stringify(payload), {
		status: 200,
		headers: { 'content-type': 'application/json' }
	});
}

class FakeRTCDataChannel {
	constructor(label, options) {
		this.label = label;
		this.options = options;
		this.readyState = 'open';
		this.onmessage = null;
	}

	close() {
		this.readyState = 'closed';
	}
}

try {
	const mod = await server.ssrLoadModule(`/src/lib/camera/webrtc-session.ts?unit=${Date.now()}`);
	const {
		acquireCameraWebrtcSession,
		__cameraWebrtcSessionDebug,
		__resetCameraWebrtcSessionsForTests
	} = mod;
	const policy = await server.ssrLoadModule(`/src/lib/camera/transport-policy.ts?unit=${Date.now()}`);
	const renderPolicy = await server.ssrLoadModule(
		`/src/lib/camera/render-policy.ts?unit=${Date.now()}`
	);
	const metadataSync = await server.ssrLoadModule(
		`/src/lib/camera/metadata-sync.ts?unit=${Date.now()}`
	);

	testLegacyMjpegFallbackPolicy(policy.legacyMjpegFallbackAllowed);
	testWebrtcTransportCandidatePolicy(policy.webrtcTransportCandidate);
	testCameraFeedRenderPolicy(renderPolicy.cameraFeedRenderPolicy);
	testCameraFeedMetadataSyncPolicy(metadataSync.decideCameraFeedMetadataUpdate);
	await testAliasRolesShareOnePhysicalSession({
		acquireCameraWebrtcSession,
		__cameraWebrtcSessionDebug,
		__resetCameraWebrtcSessionsForTests
	});
	await testDifferentPhysicalSourcesCreateDifferentSessions({
		acquireCameraWebrtcSession,
		__cameraWebrtcSessionDebug,
		__resetCameraWebrtcSessionsForTests
	});
	await testAliasRolesShareOneTargetReadyPeerConnection({
		acquireCameraWebrtcSession,
		__cameraWebrtcSessionDebug,
		__resetCameraWebrtcSessionsForTests
	});
	await testTargetReadyDoesNotFallbackWithoutRtcPeerConnection({
		acquireCameraWebrtcSession,
		__cameraWebrtcSessionDebug,
		__resetCameraWebrtcSessionsForTests
	});

	console.log('webrtc-session tests passed');
} finally {
	await server.close();
}

async function testAliasRolesShareOnePhysicalSession({
	acquireCameraWebrtcSession,
	__cameraWebrtcSessionDebug,
	__resetCameraWebrtcSessionsForTests
}) {
	__resetCameraWebrtcSessionsForTests();
	const oldFetch = globalThis.fetch;
	const calls = [];
	globalThis.fetch = async (input) => {
		calls.push(String(input));
		return sessionsResponse({
			ok: true,
			target_ready: false,
			blockers: ['unit hardware unavailable'],
			sessions: [
				{
					physical_source: 'video:5',
					roles: ['c_channel_2', 'feeder']
				}
			],
			control_plane: {
				metadata_data_channel: {
					label: 'camera-metadata',
					ordered: false,
					max_retransmits: 0
				}
			}
		});
	};
	try {
		const first = makeSubscriber();
		const second = makeSubscriber();
		const firstLease = acquireCameraWebrtcSession(
			{ baseUrl: 'http://unit/', camera: 'c_channel_2', streamEpoch: 42 },
			first.subscriber
		);
		const secondLease = acquireCameraWebrtcSession(
			{ baseUrl: 'http://unit', camera: 'feeder', streamEpoch: 42 },
			second.subscriber
		);

		await waitUntil(
			() =>
				first.states.some((state) => state.status === 'unavailable') &&
				second.states.some((state) => state.status === 'unavailable'),
			'alias subscribers to reach unavailable state'
		);

		assert.equal(calls.length, 1);
		const debug = __cameraWebrtcSessionDebug();
		assert.equal(debug.sessionCount, 1);
		assert.deepEqual(debug.sessionKeys, ['http://unit|physical:video:5|42']);
		assert.equal(debug.sessionSubscriberCounts['http://unit|physical:video:5|42'], 2);
		assert.equal(debug.sessionStatuses['http://unit|physical:video:5|42'], 'unavailable');
		assert.equal(debug.directoryRequestCount, 0);

		firstLease.release();
		secondLease.release();
		await wait();
		assert.equal(__cameraWebrtcSessionDebug().sessionCount, 0);
	} finally {
		globalThis.fetch = oldFetch;
		__resetCameraWebrtcSessionsForTests();
	}
}

function testCameraFeedRenderPolicy(cameraFeedRenderPolicy) {
	assert.deepEqual(
		cameraFeedRenderPolicy({
			direct: false,
			annotated: true,
			cropped: true,
			zones: true,
			usingWebrtc: true
		}),
		{
			browserMetadataCandidate: true,
			browserOverlayCandidate: true,
			browserCropCandidate: true,
			metadataWebsocketCandidate: false,
			serverAnnotated: false,
			serverShowRegions: false,
			serverDashboard: false
		}
	);
	assert.deepEqual(
		cameraFeedRenderPolicy({
			direct: false,
			annotated: true,
			cropped: true,
			zones: true,
			usingWebrtc: false
		}),
		{
			browserMetadataCandidate: true,
			browserOverlayCandidate: true,
			browserCropCandidate: true,
			metadataWebsocketCandidate: true,
			serverAnnotated: false,
			serverShowRegions: false,
			serverDashboard: false
		}
	);
	assert.deepEqual(
		cameraFeedRenderPolicy({
			direct: true,
			annotated: true,
			cropped: true,
			zones: true,
			usingWebrtc: false
		}),
		{
			browserMetadataCandidate: false,
			browserOverlayCandidate: false,
			browserCropCandidate: false,
			metadataWebsocketCandidate: false,
			serverAnnotated: true,
			serverShowRegions: true,
			serverDashboard: true
		}
	);
	assert.deepEqual(
		cameraFeedRenderPolicy({
			direct: false,
			annotated: false,
			cropped: false,
			zones: true,
			usingWebrtc: true
		}),
		{
			browserMetadataCandidate: true,
			browserOverlayCandidate: true,
			browserCropCandidate: false,
			metadataWebsocketCandidate: false,
			serverAnnotated: false,
			serverShowRegions: false,
			serverDashboard: false
		}
	);
	assert.deepEqual(
		cameraFeedRenderPolicy({
			direct: false,
			annotated: false,
			cropped: false,
			zones: true,
			usingWebrtc: false
		}),
		{
			browserMetadataCandidate: true,
			browserOverlayCandidate: true,
			browserCropCandidate: false,
			metadataWebsocketCandidate: true,
			serverAnnotated: false,
			serverShowRegions: false,
			serverDashboard: false
		}
	);
	assert.deepEqual(
		cameraFeedRenderPolicy({
			direct: true,
			annotated: false,
			cropped: false,
			zones: true,
			usingWebrtc: false
		}),
		{
			browserMetadataCandidate: false,
			browserOverlayCandidate: false,
			browserCropCandidate: false,
			metadataWebsocketCandidate: false,
			serverAnnotated: false,
			serverShowRegions: true,
			serverDashboard: false
		}
	);
	for (const annotated of [false, true]) {
		for (const cropped of [false, true]) {
			for (const zones of [false, true]) {
				const policy = cameraFeedRenderPolicy({
					direct: false,
					annotated,
					cropped,
					zones,
					usingWebrtc: true
				});
				assert.equal(policy.serverAnnotated, false);
				assert.equal(policy.serverShowRegions, false);
				assert.equal(policy.serverDashboard, false);
				assert.equal(policy.metadataWebsocketCandidate, false);
			}
		}
	}
}

function testCameraFeedMetadataSyncPolicy(decideCameraFeedMetadataUpdate) {
	const accepted = decideCameraFeedMetadataUpdate(
		{
			ok: true,
			message_type: 'camera.feed_metadata',
			frame: { timestamp: 10, width: 12, height: 8 },
			overlays: []
		},
		null
	);
	assert.equal(accepted.action, 'accept');
	assert.equal(accepted.timestamp, 10);

	const stale = decideCameraFeedMetadataUpdate(
		{
			ok: true,
			message_type: 'camera.feed_metadata',
			frame: { timestamp: 9.5, width: 12, height: 8 },
			overlays: []
		},
		10
	);
	assert.equal(stale.action, 'ignore');

	const wrongType = decideCameraFeedMetadataUpdate(
		{
			ok: true,
			message_type: 'other.message',
			frame: { timestamp: 11, width: 12, height: 8 },
			overlays: []
		},
		10
	);
	assert.equal(wrongType.action, 'ignore');

	const clear = decideCameraFeedMetadataUpdate({ ok: false }, 10);
	assert.equal(clear.action, 'clear');
}

function testWebrtcTransportCandidatePolicy(webrtcTransportCandidate) {
	assert.equal(
		webrtcTransportCandidate({
			preferWebrtc: true,
			isConfigured: true
		}),
		true
	);
	assert.equal(
		webrtcTransportCandidate({
			preferWebrtc: false,
			isConfigured: true
		}),
		false
	);
	assert.equal(
		webrtcTransportCandidate({
			preferWebrtc: true,
			isConfigured: false
		}),
		false
	);
}

function testLegacyMjpegFallbackPolicy(legacyMjpegFallbackAllowed) {
	assert.equal(
		legacyMjpegFallbackAllowed({
			webrtcCandidate: false,
			webrtcTargetReady: false,
			webrtcStatus: 'idle'
		}),
		true
	);
	assert.equal(
		legacyMjpegFallbackAllowed({
			webrtcCandidate: true,
			webrtcTargetReady: false,
			webrtcStatus: 'unavailable'
		}),
		true
	);
	assert.equal(
		legacyMjpegFallbackAllowed({
			webrtcCandidate: true,
			webrtcTargetReady: false,
			webrtcStatus: 'error'
		}),
		false
	);
	assert.equal(
		legacyMjpegFallbackAllowed({
			webrtcCandidate: true,
			webrtcTargetReady: true,
			webrtcStatus: 'error'
		}),
		false
	);
	assert.equal(
		legacyMjpegFallbackAllowed({
			webrtcCandidate: true,
			webrtcTargetReady: true,
			webrtcStatus: 'unavailable'
		}),
		false
	);
	assert.equal(
		legacyMjpegFallbackAllowed({
			webrtcCandidate: true,
			webrtcTargetReady: true,
			webrtcStatus: 'connecting'
		}),
		false
	);
}

async function testDifferentPhysicalSourcesCreateDifferentSessions({
	acquireCameraWebrtcSession,
	__cameraWebrtcSessionDebug,
	__resetCameraWebrtcSessionsForTests
}) {
	__resetCameraWebrtcSessionsForTests();
	const oldFetch = globalThis.fetch;
	globalThis.fetch = async () =>
		sessionsResponse({
			ok: true,
			target_ready: false,
			blockers: [],
			sessions: [
				{ physical_source: 'video:5', roles: ['c_channel_2'] },
				{ physical_source: 'video:7', roles: ['c_channel_3'] }
			]
		});
	try {
		const first = makeSubscriber();
		const second = makeSubscriber();
		const firstLease = acquireCameraWebrtcSession(
			{ baseUrl: 'http://unit', camera: 'c_channel_2', streamEpoch: 7 },
			first.subscriber
		);
		const secondLease = acquireCameraWebrtcSession(
			{ baseUrl: 'http://unit', camera: 'c_channel_3', streamEpoch: 7 },
			second.subscriber
		);

		await waitUntil(
			() =>
				first.states.some((state) => state.status === 'unavailable') &&
				second.states.some((state) => state.status === 'unavailable'),
			'different physical-source subscribers to reach unavailable state'
		);

		assert.deepEqual(__cameraWebrtcSessionDebug().sessionKeys, [
			'http://unit|physical:video:5|7',
			'http://unit|physical:video:7|7'
		]);
		firstLease.release();
		secondLease.release();
		await wait();
		assert.equal(__cameraWebrtcSessionDebug().sessionCount, 0);
	} finally {
		globalThis.fetch = oldFetch;
		__resetCameraWebrtcSessionsForTests();
	}
}

async function testTargetReadyDoesNotFallbackWithoutRtcPeerConnection({
	acquireCameraWebrtcSession,
	__resetCameraWebrtcSessionsForTests
}) {
	__resetCameraWebrtcSessionsForTests();
	const oldFetch = globalThis.fetch;
	const oldPeerConnection = globalThis.RTCPeerConnection;
	const calls = [];
	delete globalThis.RTCPeerConnection;
	globalThis.fetch = async (input) => {
		calls.push(String(input));
		return sessionsResponse({
			ok: true,
			target_ready: true,
			blockers: [],
			sessions: [{ physical_source: 'video:5', roles: ['c_channel_2'] }]
		});
	};
	try {
		const consumer = makeSubscriber();
		const lease = acquireCameraWebrtcSession(
			{ baseUrl: 'http://unit', camera: 'c_channel_2', streamEpoch: 99 },
			consumer.subscriber
		);
		await waitUntil(
			() => consumer.states.some((state) => state.status === 'error'),
			'target-ready session to reject missing RTCPeerConnection'
		);
		assert.equal(calls.length, 1);
		assert(
			consumer.states.some((state) =>
				state.blockers.includes('Browser RTCPeerConnection is unavailable.')
			)
		);
		lease.release();
	} finally {
		if (oldPeerConnection === undefined) {
			delete globalThis.RTCPeerConnection;
		} else {
			globalThis.RTCPeerConnection = oldPeerConnection;
		}
		globalThis.fetch = oldFetch;
		__resetCameraWebrtcSessionsForTests();
	}
}

async function testAliasRolesShareOneTargetReadyPeerConnection({
	acquireCameraWebrtcSession,
	__cameraWebrtcSessionDebug,
	__resetCameraWebrtcSessionsForTests
}) {
	__resetCameraWebrtcSessionsForTests();
	const oldFetch = globalThis.fetch;
	const oldPeerConnection = globalThis.RTCPeerConnection;
	const calls = [];
	const peers = [];
	globalThis.RTCPeerConnection = class FakeRTCPeerConnection {
		constructor() {
			this.iceGatheringState = 'complete';
			this.connectionState = 'new';
			this.iceConnectionState = 'new';
			this.localDescription = null;
			this.remoteDescription = null;
			this.ondatachannel = null;
			this.ontrack = null;
			this.onconnectionstatechange = null;
			this.oniceconnectionstatechange = null;
			this.closed = false;
			peers.push(this);
		}

		addTransceiver(kind, options) {
			this.transceiver = { kind, options };
			return this.transceiver;
		}

		createDataChannel(label, options) {
			this.dataChannel = new FakeRTCDataChannel(label, options);
			return this.dataChannel;
		}

		async createOffer() {
			return { type: 'offer', sdp: 'v=0\r\nm=video 9 UDP/TLS/RTP/SAVPF 102\r\n' };
		}

		async setLocalDescription(description) {
			this.localDescription = description;
		}

		async setRemoteDescription(description) {
			this.remoteDescription = description;
			this.ontrack?.({
				track: { kind: 'video', stop() {} },
				streams: [
					{
						id: 'shared-stream-video-5',
						getTracks() {
							return [{ stop() {} }];
						}
					}
				]
			});
		}

		addEventListener() {}
		removeEventListener() {}

		close() {
			this.closed = true;
			this.connectionState = 'closed';
		}
	};
	globalThis.fetch = async (input, init = {}) => {
		const url = String(input);
		calls.push({ url, method: init.method || 'GET' });
		if (url.includes('/api/cameras/webrtc/sessions')) {
			return sessionsResponse({
				ok: true,
				target_ready: true,
				blockers: [],
				sessions: [
					{
						physical_source: 'video:5',
						roles: ['c_channel_2', 'feeder']
					}
				],
				control_plane: {
					metadata_data_channel: {
						label: 'camera-metadata',
						ordered: false,
						max_retransmits: 0
					}
				}
			});
		}
		if (url.includes('/api/cameras/webrtc/offer/')) {
			return sessionsResponse({
				type: 'answer',
				sdp: 'v=0\r\nm=video 9 UDP/TLS/RTP/SAVPF 102\r\na=rtpmap:102 H264/90000\r\n'
			});
		}
		throw new Error(`Unexpected fetch: ${url}`);
	};
	try {
		const first = makeSubscriber();
		const second = makeSubscriber();
		const firstLease = acquireCameraWebrtcSession(
			{ baseUrl: 'http://unit', camera: 'c_channel_2', streamEpoch: 'ready' },
			first.subscriber
		);
		const secondLease = acquireCameraWebrtcSession(
			{ baseUrl: 'http://unit', camera: 'feeder', streamEpoch: 'ready' },
			second.subscriber
		);

		await waitUntil(
			() =>
				first.states.some((state) => state.status === 'connected') &&
				second.states.some((state) => state.status === 'connected'),
			'alias target-ready subscribers to share connected state',
			() =>
				JSON.stringify({
					calls,
					peers: peers.length,
					first: first.states.map((state) => ({ status: state.status, blockers: state.blockers })),
					second: second.states.map((state) => ({ status: state.status, blockers: state.blockers }))
				})
		);

		const sessionsCalls = calls.filter((call) => call.url.includes('/api/cameras/webrtc/sessions'));
		const offerCalls = calls.filter((call) => call.url.includes('/api/cameras/webrtc/offer/'));
		assert.equal(sessionsCalls.length, 1);
		assert.equal(offerCalls.length, 1);
		assert.equal(peers.length, 1);
		assert.deepEqual(__cameraWebrtcSessionDebug().sessionKeys, [
			'http://unit|physical:video:5|ready'
		]);
		assert.equal(
			__cameraWebrtcSessionDebug().sessionSubscriberCounts['http://unit|physical:video:5|ready'],
			2
		);
		assert.equal(first.states.at(-1).stream.id, 'shared-stream-video-5');
		assert.equal(second.states.at(-1).stream.id, 'shared-stream-video-5');
		peers[0].dataChannel.onmessage?.({
			data: JSON.stringify({
				ok: true,
				message_type: 'camera.feed_metadata',
				frame: { timestamp: 123.5, width: 12, height: 8 },
				overlays: []
			})
		});
		assert.equal(first.metadata.length, 1);
		assert.equal(second.metadata.length, 1);
		assert.equal(first.metadata[0].frame.timestamp, 123.5);
		assert.equal(second.metadata[0].frame.timestamp, 123.5);
		peers[0].dataChannel.onmessage?.({
			data: JSON.stringify({
				ok: true,
				message_type: 'camera.feed_metadata',
				frame: { timestamp: 122.5, width: 12, height: 8 },
				overlays: []
			})
		});
		assert.equal(first.metadata.length, 1);
		assert.equal(second.metadata.length, 1);
		peers[0].dataChannel.onmessage?.({
			data: JSON.stringify({
				ok: false,
				message_type: 'camera.feed_metadata'
			})
		});
		assert.equal(first.metadata.length, 2);
		assert.equal(second.metadata.length, 2);
		assert.equal(first.metadata[1], null);
		assert.equal(second.metadata[1], null);
		peers[0].dataChannel.onmessage?.({
			data: JSON.stringify({
				ok: true,
				message_type: 'camera.feed_metadata',
				frame: { timestamp: 123, width: 12, height: 8 },
				overlays: []
			})
		});
		assert.equal(first.metadata.length, 3);
		assert.equal(second.metadata.length, 3);
		assert.equal(first.metadata[2].frame.timestamp, 123);

		firstLease.release();
		assert.equal(__cameraWebrtcSessionDebug().sessionCount, 1);
		assert.equal(
			__cameraWebrtcSessionDebug().sessionSubscriberCounts['http://unit|physical:video:5|ready'],
			1
		);
		assert.equal(peers[0].closed, false);
		peers[0].dataChannel.onmessage?.({
			data: JSON.stringify({
				ok: true,
				message_type: 'camera.feed_metadata',
				frame: { timestamp: 124.5, width: 12, height: 8 },
				overlays: []
			})
		});
		assert.equal(first.metadata.length, 3);
		assert.equal(second.metadata.length, 4);
		assert.equal(second.metadata[3].frame.timestamp, 124.5);
		secondLease.release();
		await wait();
		assert.equal(__cameraWebrtcSessionDebug().sessionCount, 0);
		assert.equal(peers[0].closed, true);
	} finally {
		if (oldPeerConnection === undefined) {
			delete globalThis.RTCPeerConnection;
		} else {
			globalThis.RTCPeerConnection = oldPeerConnection;
		}
		globalThis.fetch = oldFetch;
		__resetCameraWebrtcSessionsForTests();
	}
}
