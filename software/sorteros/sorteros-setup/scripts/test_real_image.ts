import path from 'node:path';
import { openAsBlob, readdirSync, statSync } from 'node:fs';
import { locateMarkerRegionInFile, patchImageFile } from '../src/lib/img-patch.ts';

const OUT_DIR = path.resolve(process.cwd(), '../build/out');

// The newest sorteros-v<version>-<date>.img in build/out.
function newestImage(): string {
    const images = readdirSync(OUT_DIR)
        .filter((name) => name.startsWith('sorteros-v') && name.endsWith('.img'))
        .map((name) => path.join(OUT_DIR, name))
        .sort((a, b) => statSync(b).mtimeMs - statSync(a).mtimeMs);
    if (images.length === 0) {
        throw new Error(`no sorteros-v*.img in ${OUT_DIR}; pass an image path as the argument`);
    }
    return images[0];
}

async function main() {
    const image_path = process.argv[2] || newestImage();
    const blob = await openAsBlob(image_path);
    const region = await locateMarkerRegionInFile(blob);

    const out = await patchImageFile(blob, {
        hostname: 'sorter-test',
        wifi: {
            ssid: 'Test WiFi',
            password: 'secret123'
        },
        ssh_authorized_key: 'ssh-ed25519 AAAATESTKEY'
    });
    const body = Buffer.from(
        await out.slice(region.start, region.end).arrayBuffer()
    ).toString('utf8').replace(/\n+$/u, '');
    const suffix = Buffer.from(
        await out.slice(region.end, region.end + 64).arrayBuffer()
    ).toString('utf8');

    console.log(`input_size=${blob.size}`);
    console.log(`output_size=${out.size}`);
    console.log(`start=${region.start}`);
    console.log(`end=${region.end}`);
    console.log('config:');
    console.log(body);
    console.log(`suffix_has_end_marker=${suffix.includes('__SORTEROS_CFG_END__')}`);
}

await main();
