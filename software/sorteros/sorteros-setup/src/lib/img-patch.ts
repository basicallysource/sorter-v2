// Byte-pattern search and in-place patch of the sorteros-config.toml
// placeholder inside a .img file. Runs entirely in the browser on a
// File / ArrayBuffer; nothing is uploaded.
//
// Contract: the marker lines AND the TOML key layout (hostname,
// [wifi].ssid/.password, [ssh].authorized_key) match the placeholder that the
// SorterOS v3 builder wrote into /etc/sorteros-config.toml (tag sorteros/v3.4.7)
// and the v3 firstboot that reads it.
//
// The markers are matched as whole comment lines, "# " included. The bare
// marker text also appears inside a compiled .pyc in the image (CPython folds
// the split string constant back together), about 1 GB before the real
// placeholder, with 2 bytes between its two markers. Matching the "# " prefix
// skips it, and MIN_CAPACITY skips any other stray pair.

const START_MARKER = '# __SORTEROS_CFG_START__';
const END_MARKER = '# __SORTEROS_CFG_END__';
const MIN_CAPACITY = 1024;
const SEARCH_CHUNK_BYTES = 8 * 1024 * 1024;

export interface SorterosConfig {
    hostname?: string;
    wifi?: { ssid: string; password: string };
    ssh_authorized_key?: string;
    tailscale_auth_key?: string;
}

function indexOfBytes(haystack: Uint8Array, needle: Uint8Array, from = 0): number {
    outer: for (let i = from; i <= haystack.length - needle.length; i++) {
        for (let j = 0; j < needle.length; j++) {
            if (haystack[i + j] !== needle[j]) continue outer;
        }
        return i;
    }
    return -1;
}

interface MarkerRegion {
    start: number;
    end: number;
}

export function patchImage(buf: ArrayBuffer, cfg: SorterosConfig): ArrayBuffer {
    const bytes = new Uint8Array(buf);
    const enc = new TextEncoder();
    const startBytes = enc.encode(START_MARKER);
    const endBytes = enc.encode(END_MARKER);

    const region = findMarkerRegion(bytes, startBytes, endBytes);
    const paddedToml = buildPaddedToml(region.end - region.start, cfg, enc);
    bytes.set(paddedToml, region.start);

    return bytes.buffer;
}

export async function patchImageFile(file: Blob, cfg: SorterosConfig): Promise<Blob> {
    const enc = new TextEncoder();
    const region = await locateMarkerRegionInFile(file);
    const paddedToml = buildPaddedToml(region.end - region.start, cfg, enc);

    // Slice paddedToml to a fresh ArrayBuffer to satisfy BlobPart's
    // strict ArrayBuffer (not ArrayBufferLike) typing under SvelteKit's
    // tsconfig.
    const tomlBuffer = paddedToml.buffer.slice(
        paddedToml.byteOffset,
        paddedToml.byteOffset + paddedToml.byteLength
    ) as ArrayBuffer;
    return new Blob([
        file.slice(0, region.start),
        tomlBuffer,
        file.slice(region.end)
    ], { type: 'application/octet-stream' });
}

export async function locateMarkerRegionInFile(
    file: Blob,
    onProgress?: (fraction: number) => void
): Promise<MarkerRegion> {
    const enc = new TextEncoder();
    return findMarkerRegionInFile(file, enc.encode(START_MARKER), enc.encode(END_MARKER), onProgress);
}

export async function patchImageFileHandleInPlace(
    handle: FileSystemFileHandle,
    cfg: SorterosConfig,
    onProgress?: (fraction: number) => void
): Promise<void> {
    const file = await handle.getFile();
    const enc = new TextEncoder();
    const region = await locateMarkerRegionInFile(file, onProgress);
    const paddedToml = buildPaddedToml(region.end - region.start, cfg, enc);
    const writable = await handle.createWritable({ keepExistingData: true });

    try {
        await writable.seek(region.start);
        await writable.write(paddedToml);
    } finally {
        await writable.close();
    }
}

function findMarkerRegion(
    bytes: Uint8Array,
    startBytes: Uint8Array,
    endBytes: Uint8Array
): MarkerRegion {
    let start = indexOfBytes(bytes, startBytes);
    while (start >= 0) {
        const end = indexOfBytes(bytes, endBytes, start + startBytes.length);
        if (end < 0) throw new Error('end marker not found. This image looks incomplete.');
        if (end - (start + startBytes.length) >= MIN_CAPACITY) {
            return { start: start + startBytes.length, end };
        }
        start = indexOfBytes(bytes, startBytes, end + endBytes.length);
    }
    throw new Error(NOT_SUPPORTED);
}

const NOT_SUPPORTED =
    'No settings placeholder found in this file. Use the .img from a SorterOS release, ' +
    'unzipped first.';

async function findMarkerRegionInFile(
    file: Blob,
    startBytes: Uint8Array,
    endBytes: Uint8Array,
    onProgress?: (fraction: number) => void
): Promise<MarkerRegion> {
    let from = 0;
    while (from < file.size) {
        const region = await findNextMarkerRegionInFile(file, startBytes, endBytes, from, onProgress);
        if (region.end - region.start >= MIN_CAPACITY) return region;
        from = region.end + endBytes.length;
    }
    throw new Error(NOT_SUPPORTED);
}

async function findNextMarkerRegionInFile(
    file: Blob,
    startBytes: Uint8Array,
    endBytes: Uint8Array,
    from: number,
    onProgress?: (fraction: number) => void
): Promise<MarkerRegion> {
    const overlap = Math.max(startBytes.length, endBytes.length) - 1;
    let start = -1;
    let offset = from;

    while (offset < file.size) {
        onProgress?.(offset / file.size);
        const slice = file.slice(offset, Math.min(file.size, offset + SEARCH_CHUNK_BYTES));
        const bytes = new Uint8Array(await slice.arrayBuffer());
        const localStart = indexOfBytes(bytes, startBytes);

        if (localStart >= 0) {
            start = offset + localStart;
            break;
        }

        if (offset + SEARCH_CHUNK_BYTES >= file.size) {
            break;
        }

        offset += SEARCH_CHUNK_BYTES - overlap;
    }

    if (start < 0) {
        throw new Error(NOT_SUPPORTED);
    }

    const end_search_offset = start + startBytes.length;
    let end_offset = end_search_offset;

    while (end_offset < file.size) {
        const slice = file.slice(end_offset, Math.min(file.size, end_offset + SEARCH_CHUNK_BYTES));
        const bytes = new Uint8Array(await slice.arrayBuffer());
        const localEnd = indexOfBytes(bytes, endBytes);

        if (localEnd >= 0) {
            return {
                start: start + startBytes.length,
                end: end_offset + localEnd
            };
        }

        if (end_offset + SEARCH_CHUNK_BYTES >= file.size) {
            break;
        }

        end_offset += SEARCH_CHUNK_BYTES - overlap;
    }

    throw new Error('end marker not found. This image looks incomplete.');
}

function buildPaddedToml(
    capacity: number,
    cfg: SorterosConfig,
    enc: TextEncoder
): Uint8Array {
    const toml = buildToml(cfg);
    const tomlBytes = enc.encode(toml);
    if (tomlBytes.length > capacity) {
        throw new Error(
            `config too large: ${tomlBytes.length} bytes, capacity ${capacity}`
        );
    }

    const padded = new Uint8Array(capacity);
    padded.fill(0x0a);
    padded.set(tomlBytes);
    return padded;
}

function buildToml(cfg: SorterosConfig): string {
    const lines: string[] = ['# written by sorteros-setup'];
    if (cfg.hostname) lines.push(`hostname = ${JSON.stringify(cfg.hostname)}`);
    if (cfg.wifi) {
        lines.push('', '[wifi]');
        lines.push(`ssid = ${JSON.stringify(cfg.wifi.ssid)}`);
        lines.push(`password = ${JSON.stringify(cfg.wifi.password)}`);
    }
    if (cfg.ssh_authorized_key) {
        lines.push('', '[ssh]');
        lines.push(`authorized_key = ${JSON.stringify(cfg.ssh_authorized_key)}`);
    }
    if (cfg.tailscale_auth_key) {
        lines.push('', '[tailscale]');
        lines.push(`auth_key = ${JSON.stringify(cfg.tailscale_auth_key)}`);
        lines.push('tags = "tag:sorter"');
    }
    return lines.join('\n') + '\n';
}
