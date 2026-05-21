import path from 'node:path';
import { openAsBlob } from 'node:fs';
import { locateMarkerRegionInFile, patchImageFile } from '../src/lib/img-patch.ts';

const DEFAULT_IMAGE_PATH = path.resolve(
    process.cwd(),
    '../build/out/sorteros-v3-2026-05-17.img'
);

async function main() {
    const image_path = process.argv[2] || DEFAULT_IMAGE_PATH;
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
