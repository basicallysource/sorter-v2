// Uploads a model made by build.mjs to the asset service and pins it in
// src/lib/machine3d/model.json, which the 3D page loads it from.
//
//   ASSET_SERVICE_URL=... ASSET_SERVICE_TOKEN=... node scripts/machine-model/publish.mjs OUT.glb
//
// The asset service names the file after a hash of its bytes, so the URL is
// immutable: a new model is a new URL, and browsers cache each one for good.
import { readFileSync, writeFileSync } from 'node:fs';

const [file] = process.argv.slice(2);
const { ASSET_SERVICE_URL: base, ASSET_SERVICE_TOKEN: token } = process.env;
if (!file || !base || !token) {
	console.error(
		'usage: ASSET_SERVICE_URL=... ASSET_SERVICE_TOKEN=... node scripts/machine-model/publish.mjs OUT.glb'
	);
	process.exit(2);
}
const bytes = readFileSync(file);
const res = await fetch(
	`${base.replace(/\/$/, '')}/v1/assets?namespace=sorter-ui&filename=machine.glb`,
	{
		method: 'POST',
		headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'model/gltf-binary' },
		body: bytes
	}
);
if (!res.ok) throw new Error(`upload failed: HTTP ${res.status} ${await res.text()}`);
const asset = await res.json();
const pin = new URL('../../src/lib/machine3d/model.json', import.meta.url);
writeFileSync(pin, JSON.stringify({ url: asset.url, bytes: bytes.length }, null, '\t') + '\n');
console.log(`${asset.url} (${bytes.length} bytes) pinned in src/lib/machine3d/model.json`);
