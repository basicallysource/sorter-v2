// Patch a SorterOS .img in place with the same code the setup site runs in
// the browser. For testing an image before release (and for anyone who'd
// rather not use the site):
//   node --experimental-strip-types scripts/patch_image.ts <sorteros.img> '<json>'
// where <json> is a SorterosConfig, e.g.
//   '{"hostname":"bin-3","wifi":{"ssid":"HomeNet","password":"secret123"},
//     "ssh_authorized_key":"ssh-ed25519 AAAA...","tailscale_auth_key":"tskey-..."}'
//
// Reads the file with plain fs calls: Node's openAsBlob reports a file over
// 4 GiB with its size wrapped at 32 bits, so it never reaches the placeholder.
import { openSync, fstatSync, readSync, writeSync, closeSync } from 'node:fs';
import { locateMarkerRegionInFile, patchImage, type SorterosConfig } from '../src/lib/img-patch.ts';

const [imagePath, json] = process.argv.slice(2);
if (!imagePath || !json) {
    console.error("usage: patch_image.ts <sorteros.img> '<config json>'");
    process.exit(2);
}
const cfg = JSON.parse(json) as SorterosConfig;
const fd = openSync(imagePath, 'r+');
try {
    const size = fstatSync(fd).size;
    const read = (start: number, end: number): Buffer => {
        const length = Math.max(0, Math.min(end, size) - start);
        const buf = Buffer.alloc(length);
        readSync(fd, buf, 0, length, start);
        return buf;
    };
    // Just the part of Blob the scanner uses.
    const file = {
        size,
        slice: (start: number, end: number) => ({
            arrayBuffer: async () => {
                const b = read(start, end);
                return b.buffer.slice(b.byteOffset, b.byteOffset + b.length);
            }
        })
    } as unknown as Blob;
    const region = await locateMarkerRegionInFile(file);
    // Patch a window around the placeholder with the site's in-memory patcher
    // and write it back.
    const from = region.start - 64;
    const window = read(from, region.end + 64);
    const patched = new Uint8Array(patchImage(window.buffer.slice(window.byteOffset, window.byteOffset + window.length), cfg));
    writeSync(fd, patched, 0, patched.length, from);
    console.log(`patched ${region.end - region.start} bytes at offset ${region.start}`);
} finally {
    closeSync(fd);
}
