import fs from 'node:fs';
import path from 'node:path';

const START_MARKER = '__SORTEROS_CFG_START__';
const END_MARKER = '__SORTEROS_CFG_END__';
const PLACEHOLDER_BYTES = 4096;
const DEFAULT_SIZE_MIB = 64;

function parseArgs(argv) {
    const args = {
        out_path: '',
        size_mib: DEFAULT_SIZE_MIB
    };

    for (let i = 0; i < argv.length; i += 1) {
        const arg = argv[i];
        if (arg === '--out') {
            args.out_path = argv[i + 1] ?? '';
            i += 1;
            continue;
        }
        if (arg === '--size-mib') {
            args.size_mib = Number(argv[i + 1] ?? DEFAULT_SIZE_MIB);
            i += 1;
            continue;
        }
    }

    return args;
}

function buildPlaceholder() {
    const prefix = Buffer.from(START_MARKER, 'utf8');
    const suffix = Buffer.from(END_MARKER, 'utf8');
    const filler_len = PLACEHOLDER_BYTES - prefix.length - suffix.length;

    if (filler_len <= 0) {
        throw new Error('placeholder is too small for the markers');
    }

    return Buffer.concat([
        prefix,
        Buffer.alloc(filler_len, 0x0a),
        suffix
    ]);
}

function main() {
    const args = parseArgs(process.argv.slice(2));
    const out_path =
        args.out_path ||
        path.resolve(process.cwd(), 'tmp', 'sorteros-test.img');
    const size_bytes = Math.max(1, Math.floor(args.size_mib)) * 1024 * 1024;
    const placeholder = buildPlaceholder();
    const prefix = Buffer.alloc(2 * 1024 * 1024, 0);
    const suffix_size = size_bytes - prefix.length - placeholder.length;

    if (suffix_size < 0) {
        throw new Error('requested image size is too small');
    }

    fs.mkdirSync(path.dirname(out_path), { recursive: true });

    const fd = fs.openSync(out_path, 'w');
    try {
        fs.writeFileSync(fd, prefix);
        fs.writeFileSync(fd, placeholder);
        if (suffix_size > 0) {
            fs.writeFileSync(fd, Buffer.alloc(suffix_size, 0));
        }
    } finally {
        fs.closeSync(fd);
    }

    console.log(`wrote ${out_path}`);
    console.log(`size_mib=${Math.floor(size_bytes / (1024 * 1024))}`);
    console.log(`marker_offset=${prefix.length}`);
    console.log(`placeholder_bytes=${placeholder.length}`);
}

main();
