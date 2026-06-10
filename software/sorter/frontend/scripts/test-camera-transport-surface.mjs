import assert from 'node:assert/strict';
import { readdir, readFile } from 'node:fs/promises';
import { join, relative } from 'node:path';

const root = new URL('..', import.meta.url).pathname;
const srcRoot = join(root, 'src');

async function* walk(dir) {
	for (const entry of await readdir(dir, { withFileTypes: true })) {
		const path = join(dir, entry.name);
		if (entry.isDirectory()) {
			yield* walk(path);
		} else if (/\.(svelte|ts)$/.test(entry.name)) {
			yield path;
		}
	}
}

async function read(relativePath) {
	return await readFile(join(root, relativePath), 'utf8');
}

function assertIncludes(text, needle, label) {
	assert.ok(text.includes(needle), `${label} must include ${needle}`);
}

function assertNotMatches(text, pattern, label) {
	assert.ok(!pattern.test(text), `${label} must not match ${pattern}`);
}

const directFeedReferences = [];
for await (const path of walk(srcRoot)) {
	const text = await readFile(path, 'utf8');
	if (text.includes('/api/cameras/feed')) {
		directFeedReferences.push(relative(root, path));
	}
}

assert.deepEqual(directFeedReferences.sort(), [
	'src/lib/components/CameraFeed.svelte',
	'src/lib/components/settings/ZoneSection.svelte',
	'src/lib/components/setup/SetupPictureSettingsModal.svelte'
]);

const transportPreview = await read('src/lib/components/CameraTransportPreview.svelte');
assertIncludes(transportPreview, 'acquireCameraWebrtcSession', 'CameraTransportPreview');
assertIncludes(transportPreview, 'webrtcTransportCandidate', 'CameraTransportPreview');
assertIncludes(transportPreview, 'legacyMjpegFallbackAllowed', 'CameraTransportPreview');
assertIncludes(transportPreview, '<video', 'CameraTransportPreview');
assertIncludes(transportPreview, '<img', 'CameraTransportPreview');
assertIncludes(transportPreview, 'mjpegSrc', 'CameraTransportPreview');

const cameraFeed = await read('src/lib/components/CameraFeed.svelte');
assertIncludes(cameraFeed, 'webrtcTransportCandidate({', 'CameraFeed');
assertIncludes(cameraFeed, 'legacyMjpegFallbackAllowed({', 'CameraFeed');
assertIncludes(cameraFeed, "import { cameraFeedRenderPolicy }", 'CameraFeed');
assertIncludes(cameraFeed, 'cameraFeedRenderPolicy({', 'CameraFeed');
assertIncludes(cameraFeed, 'if (!annotated) continue;', 'CameraFeed detection overlay toggle');
assertIncludes(cameraFeed, "show_regions: serverShowRegions ? '1' : '0'", 'CameraFeed server regions');
assertIncludes(cameraFeed, "dashboard: serverDashboard ? '1' : '0'", 'CameraFeed server crop');
assertNotMatches(cameraFeed, /preferWebrtc\s*&&\s*!direct/, 'CameraFeed WebRTC candidate');
assertNotMatches(cameraFeed, /const serverAnnotated = \$derived\(annotated && !browserOverlayCandidate\)/, 'CameraFeed render policy');
assertNotMatches(cameraFeed, /dashboard:\s*cropped\s*\?/, 'CameraFeed server crop');

const setupPicture = await read('src/lib/components/setup/SetupPictureSettingsModal.svelte');
assertIncludes(setupPicture, "import CameraTransportPreview", 'SetupPictureSettingsModal');
assertIncludes(setupPicture, '<CameraTransportPreview', 'SetupPictureSettingsModal');
assert.ok(
	setupPicture.includes('mjpegSrc={mjpegSrc}') || setupPicture.includes('{mjpegSrc}'),
	'SetupPictureSettingsModal must pass mjpegSrc to CameraTransportPreview'
);
assertNotMatches(setupPicture, /<img[\s\S]{0,240}src=\{mjpegSrc\}/, 'SetupPictureSettingsModal');

const zoneSection = await read('src/lib/components/settings/ZoneSection.svelte');
assertIncludes(zoneSection, "import CameraTransportPreview", 'ZoneSection');
assertIncludes(zoneSection, '<CameraTransportPreview', 'ZoneSection');
assertIncludes(zoneSection, 'mjpegSrc={streamSrc(currentChannel)}', 'ZoneSection');
assertNotMatches(zoneSection, /<img[\s\S]{0,240}src=\{streamSrc\(currentChannel\)\}/, 'ZoneSection');

console.log('camera transport surface tests passed');
