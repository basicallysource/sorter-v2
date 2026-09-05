// Materialize each superseded assembly version's snapshot from git itself,
// at build time. Never committed: `static/versions/` is gitignored and
// derived fresh by `npm run build` (Cloudflare Pages) and `npm run dev`.
//
// Flipping the site to an old version must show the site as it was — and the
// site of that day already exists, verbatim, in git: the generated catalog
// committed alongside the change. This subsets that data per version:
//
//     static/versions/<assembly>-v<version>.json
//
// Contents: the era's own records — every assembly, printed part and hardware
// item reachable from the flipped assembly's subtree, exactly as the
// generated data of that commit had them. Names, descriptions, renders,
// grams, colors, photos, connections, params, the plain STL and the
// uid-engraved downloads: all the era's, all at permanent content-addressed
// URLs.
//
// Which commit is a version's moment? The last one of its reign: the parent
// of the commit that superseded it (the NEXT entry's commit). An entry may
// override with "snapshot_at": "<commit>" — the feeder's v4 does, because it
// was stamped as a deliberate lock of its own moment.
//
// A stamped version whose commit cannot be read is a build error, not a
// silent downgrade: on a shallow clone the script deepens it first.
import { execFileSync } from 'node:child_process';
import { mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const PC = dirname(dirname(fileURLToPath(import.meta.url)));
const OUT_DIR = join(PC, 'static', 'versions');
const GENERATED = 'parts-calculator/src/lib/data/catalog.generated.json';

function git(...args) {
	return execFileSync('git', ['-C', PC, ...args], { maxBuffer: 64 * 1024 * 1024 });
}

let deepened = false;
function generatedAt(ref) {
	for (;;) {
		try {
			return JSON.parse(git('show', `${ref}:${GENERATED}`).toString('utf8'));
		} catch (e) {
			if (!deepened) {
				// Pages may hand us a shallow clone; the history is one fetch away.
				deepened = true;
				try {
					git('fetch', '--unshallow', '--quiet');
					continue;
				} catch {
					/* not shallow, or offline — fall through to null */
				}
			}
			return null;
		}
	}
}

/** The era records reachable from `root` in the era's own data: assemblies
 *  walked by their lines (param defaults and args included), parts and
 *  hardware picked up as line members, `via` fasteners and `requires`. */
function subtreeSubset(gen, root) {
	const asms = new Map((gen.assemblies ?? []).map((a) => [a.id, a]));
	const parts = new Map((gen.parts ?? []).map((p) => [p.id, p]));
	const hardware = new Map((gen.hardware ?? []).map((h) => [h.id, h]));
	if (!asms.has(root)) return null;

	const keepA = {};
	const ids = new Set();
	const todo = [root];
	while (todo.length) {
		const aid = todo.shift();
		const a = asms.get(aid);
		if (!a || keepA[aid]) continue;
		keepA[aid] = a;
		for (const spec of Object.values(a.params ?? {})) if (spec?.default) ids.add(spec.default);
		for (const line of a.lines ?? []) {
			for (const v of Object.values(line.args ?? {}))
				if (typeof v === 'string' && !v.startsWith('$')) ids.add(v);
			const ref = line.part ?? line.assembly;
			if (!ref) continue;
			if (asms.has(ref)) todo.push(ref);
			else ids.add(ref);
		}
		for (const c of a.connections ?? []) if (c.via) ids.add(c.via);
	}

	const keepP = {};
	const keepH = {};
	for (const id of ids) {
		if (parts.has(id)) {
			keepP[id] = parts.get(id);
			for (const req of parts.get(id).requires ?? [])
				if (hardware.has(req.part)) keepH[req.part] = hardware.get(req.part);
		}
		if (hardware.has(id)) keepH[id] = hardware.get(id);
	}
	return { assemblies: keepA, parts: keepP, hardware: keepH };
}

const manifest = JSON.parse(readFileSync(join(PC, 'catalog', 'parts.json'), 'utf8'));
rmSync(OUT_DIR, { recursive: true, force: true });
mkdirSync(OUT_DIR, { recursive: true });

const genCache = new Map();
let wrote = 0;
const flat = [];
const broken = [];
for (const a of manifest.assemblies ?? []) {
	const versions = a.versions ?? [];
	for (let k = 0; k < versions.length - 1; k++) {
		const v = versions[k];
		const succ = versions[k + 1].commit;
		const ref = v.snapshot_at ?? (succ ? `${succ}~` : null);
		if (!ref) {
			// pre-stamp-era entry with no known superseding commit; the app
			// falls back to its flat lines snapshot
			flat.push(`${a.id} v${v.version}`);
			continue;
		}
		if (!genCache.has(ref)) genCache.set(ref, generatedAt(ref));
		const gen = genCache.get(ref);
		const subset = gen ? subtreeSubset(gen, a.id) : null;
		if (!subset) {
			broken.push(`${a.id} v${v.version}: cannot read ${GENERATED} at ${ref}`);
			continue;
		}
		writeFileSync(
			join(OUT_DIR, `${a.id}-v${v.version}.json`),
			JSON.stringify({ commit: ref, ...subset }) + '\n'
		);
		wrote++;
	}
}

console.log(
	`version snapshots: ${wrote} written${flat.length ? `, ${flat.length} pre-stamp-era left flat (${flat.join(', ')})` : ''}`
);
if (broken.length) {
	console.error('version snapshots FAILED for stamped entries:');
	for (const b of broken) console.error(`  ${b}`);
	process.exit(1);
}
