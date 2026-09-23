// Patch a SorterOS .img in place with the same code the setup site runs in
// the browser. For testing an image before release (and for anyone who'd
// rather not use the site):
//   node --experimental-strip-types scripts/patch_image.ts <sorteros.img> '<json>'
// where <json> is a SorterosConfig, e.g.
//   '{"hostname":"bin-3","wifi":{"ssid":"HomeNet","password":"secret123"},
//     "ssh_authorized_key":"ssh-ed25519 AAAA...","tailscale_auth_key":"tskey-..."}'
import { openAsBlob, openSync, writeSync, closeSync } from 'node:fs';
import { locateMarkerRegionInFile, patchImageFile, type SorterosConfig } from '../src/lib/img-patch.ts';

const [imagePath, json] = process.argv.slice(2);
if (!imagePath || !json) {
    console.error("usage: patch_image.ts <sorteros.img> '<config json>'");
    process.exit(2);
}
const cfg = JSON.parse(json) as SorterosConfig;
const blob = await openAsBlob(imagePath);
const region = await locateMarkerRegionInFile(blob);
const patched = await patchImageFile(blob, cfg);
const bytes = new Uint8Array(await patched.slice(region.start, region.end).arrayBuffer());
const fd = openSync(imagePath, 'r+');
try {
    writeSync(fd, bytes, 0, bytes.length, region.start);
} finally {
    closeSync(fd);
}
console.log(`patched ${bytes.length} bytes at offset ${region.start}`);
