import fs from 'node:fs';
import path from 'node:path';

const START_MARKER = '__SORTEROS_CFG_START__';
const END_MARKER = '__SORTEROS_CFG_END__';
const SEARCH_CHUNK_BYTES = 8 * 1024 * 1024;

function indexOfBuffer(haystack, needle) {
    return haystack.indexOf(needle);
}

async function findMarkerRegion(file_path) {
    const handle = await fs.promises.open(file_path, 'r');
    const start_bytes = Buffer.from(START_MARKER, 'utf8');
    const end_bytes = Buffer.from(END_MARKER, 'utf8');
    const overlap = Math.max(start_bytes.length, end_bytes.length) - 1;
    const size = (await handle.stat()).size;
    let start = -1;
    let offset = 0;

    try {
        while (offset < size) {
            const len = Math.min(SEARCH_CHUNK_BYTES, size - offset);
            const chunk = Buffer.alloc(len);
            await handle.read(chunk, 0, len, offset);
            const local_start = indexOfBuffer(chunk, start_bytes);

            if (local_start >= 0) {
                start = offset + local_start;
                break;
            }

            if (offset + SEARCH_CHUNK_BYTES >= size) {
                break;
            }

            offset += SEARCH_CHUNK_BYTES - overlap;
        }

        if (start < 0) {
            throw new Error('start marker not found');
        }

        let end_offset = start + start_bytes.length;
        while (end_offset < size) {
            const len = Math.min(SEARCH_CHUNK_BYTES, size - end_offset);
            const chunk = Buffer.alloc(len);
            await handle.read(chunk, 0, len, end_offset);
            const local_end = indexOfBuffer(chunk, end_bytes);

            if (local_end >= 0) {
                return {
                    start: start + start_bytes.length,
                    end: end_offset + local_end
                };
            }

            if (end_offset + SEARCH_CHUNK_BYTES >= size) {
                break;
            }

            end_offset += SEARCH_CHUNK_BYTES - overlap;
        }

        throw new Error('end marker not found');
    } finally {
        await handle.close();
    }
}

async function readRegionText(file_path, start, end) {
    const handle = await fs.promises.open(file_path, 'r');
    try {
        const len = end - start;
        const chunk = Buffer.alloc(len);
        await handle.read(chunk, 0, len, start);
        return chunk.toString('utf8').replace(/\n+$/u, '');
    } finally {
        await handle.close();
    }
}

async function main() {
    const input_path =
        process.argv[2] ||
        path.resolve(process.cwd(), 'tmp', 'sorteros-test-customized.img');

    const region = await findMarkerRegion(input_path);
    const body = await readRegionText(input_path, region.start, region.end);

    console.log(`file=${input_path}`);
    console.log(`start=${region.start}`);
    console.log(`end=${region.end}`);
    console.log('config:');
    console.log(body || '(empty)');
}

await main();
