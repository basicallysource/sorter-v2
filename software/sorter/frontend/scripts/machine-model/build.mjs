// Builds the 3D machine the UI's 3D page draws, from a glTF export of the
// machine's main CAD assembly.
//
//   node scripts/machine-model/build.mjs EXPORT.gltf OUT.glb
//
// EXPORT.gltf is Onshape's glTF translation of the main assembly: Z up, metres,
// sub-assemblies kept as nodes, the chute stack's axis on Z. See README.md.
//
// OUT.glb is small enough to load on a phone and draw in a few dozen calls:
// - the fixed parts, merged by look ("body", "dark"), with every part used
//   more than once stored once and instanced;
// - the tower in parts the page stacks for the machine's own layer count: the
//   top, one layer's frame and posts, and the base;
// - the chute, which turns about the vertical axis: its top, and one chute
//   layer of each kind with its flap (on its hinge) and servo;
// - each feeder rotor on its own pivot, and each motor on its own, so the page
//   can turn them and light them;
// - one bin of each kind in the frame of the face it sits on, which the page
//   places from the machine's own bin layout.
// asset.extras.machine says where everything is (see src/lib/machine3d/model.ts).
//
// Fasteners, inserts, wiring, parts inside housings and anything smaller than
// MIN_PART are left out, and every surface is simplified as far as it can go
// while staying within SIMPLIFY_ERROR of the CAD's. Creases are kept, so flat
// faces stay flat.

import { Document, NodeIO } from '@gltf-transform/core';
import {
	EXTMeshGPUInstancing,
	EXTMeshoptCompression,
	KHRMeshQuantization
} from '@gltf-transform/extensions';
import { meshopt } from '@gltf-transform/functions';
import { MeshoptEncoder, MeshoptSimplifier } from 'meshoptimizer';
import { writeFileSync } from 'node:fs';

const [src, out] = process.argv.slice(2);
if (!src || !out) {
	console.error('usage: node scripts/machine-model/build.mjs EXPORT.gltf OUT.glb');
	process.exit(2);
}

// Parts left out by name: fasteners and inserts, wiring, and the electronics
// inside the housings (the housings stay).
const DROP = new RegExp(
	[
		'ruthex|\\binsert\\b|screw|\\bnut\\b|washer|\\bbolt\\b|dowel|\\bpin\\b',
		'wires?\\b|servo lead|conductor|ribbon|crimp|receptacle|contact|strain relief|^Route \\d|plug|barrel|cable|inlet lead|harness',
		'R_0603|C_0603|_Metric|\\bJST\\b|IDC|PinHeader|header|envelope|EasyEDA|capacitor|antenna|\\bfan\\b|FAN_|jack|terminal',
		'PCB|Pico|TMC2209|MOS\\d|Buck|OV9732|IMX415|lens|SMD|solder|spring|lever|roller|switch|tab$'
	].join('|'),
	'i'
);
// Kept whatever DROP says: structure whose names mention a screw or a switch.
const KEEP =
	/^(Top plate|limit_switch_(stop|housing)|rib \d|ribbon_cage_housing|cage_bracket_ribbon)/;
const DROP_ASSEMBLIES = /^Machine harness$/;
// Anything whose bounding box diagonal is smaller than this is left out (metres).
const MIN_PART = 0.008;
// How far a simplified surface may stray from the CAD's (metres).
const SIMPLIFY_ERROR = 0.0005;
// Parts of the interface layer that turn with the chute.
const TURNS_WITH_CHUTE = /^(Spur 2M 120T|lazy_susan_inner_ring|limit_switch_stop)/;
const BIN = /^bin_(half|third)_(.+)$/;

await Promise.all([MeshoptEncoder.ready, MeshoptSimplifier.ready]);
const io = new NodeIO()
	.registerExtensions([EXTMeshGPUInstancing, EXTMeshoptCompression, KHRMeshQuantization])
	.registerDependencies({ 'meshopt.encoder': MeshoptEncoder });
const source = await io.read(src);
const main = source.getRoot().listScenes()[0].listChildren()[0];

const clean = (s) => s.replace(/^occurrence of /, '').replace(/ <\d+>$/, '');

// ---------------------------------------------------------------- math
// Matrices are column-major 4x4 arrays, as glTF has them.
function mul(a, b) {
	const o = new Array(16).fill(0);
	for (let c = 0; c < 4; c++)
		for (let r = 0; r < 4; r++)
			for (let k = 0; k < 4; k++) o[c * 4 + r] += a[k * 4 + r] * b[c * 4 + k];
	return o;
}
const translate = (x, y, z) => [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, x, y, z, 1];
function rotateY(deg) {
	const a = (deg * Math.PI) / 180;
	const c = Math.cos(a);
	const s = Math.sin(a);
	return [c, 0, -s, 0, 0, 1, 0, 0, s, 0, c, 0, 0, 0, 0, 1];
}
// The export is Z up; the page (three.js) is Y up: (x, y, z) -> (x, z, -y).
// A CAD azimuth (from +X toward +Y) is then a rotation about +Y.
const ZUP_TO_YUP = [1, 0, 0, 0, 0, 0, -1, 0, 0, 1, 0, 0, 0, 0, 0, 1];
const point = (m, p) =>
	[0, 1, 2].map((r) => m[r] * p[0] + m[4 + r] * p[1] + m[8 + r] * p[2] + m[12 + r]);
const direction = (m, p) => [0, 1, 2].map((r) => m[r] * p[0] + m[4 + r] * p[1] + m[8 + r] * p[2]);
const azimuth = (p) => (Math.atan2(-p[2], p[0]) * 180) / Math.PI;
const round = (v, d = 5) => Number(v.toFixed(d));
function invertRigid(m) {
	const r = [m[0], m[4], m[8], 0, m[1], m[5], m[9], 0, m[2], m[6], m[10], 0, 0, 0, 0, 1];
	const t = point(r, [m[12], m[13], m[14]]);
	r[12] = -t[0];
	r[13] = -t[1];
	r[14] = -t[2];
	return r;
}
function quaternion(m) {
	const [m00, m10, m20, , m01, m11, m21, , m02, m12, m22] = m;
	const tr = m00 + m11 + m22;
	if (tr > 0) {
		const s = Math.sqrt(tr + 1) * 2;
		return [(m21 - m12) / s, (m02 - m20) / s, (m10 - m01) / s, s / 4];
	}
	if (m00 > m11 && m00 > m22) {
		const s = Math.sqrt(1 + m00 - m11 - m22) * 2;
		return [s / 4, (m01 + m10) / s, (m02 + m20) / s, (m21 - m12) / s];
	}
	if (m11 > m22) {
		const s = Math.sqrt(1 + m11 - m00 - m22) * 2;
		return [(m01 + m10) / s, s / 4, (m12 + m21) / s, (m02 - m20) / s];
	}
	const s = Math.sqrt(1 + m22 - m00 - m11) * 2;
	return [(m02 + m20) / s, (m12 + m21) / s, s / 4, (m10 - m01) / s];
}

// ---------------------------------------------------------------- the parts
// Every mesh in the assembly: its name, the assemblies it is in, where it is.
const parts = [];
(function walk(node, path) {
	const here = [...path, node.getName()];
	if (node.getMesh()) {
		const world = mul(ZUP_TO_YUP, node.getWorldMatrix());
		parts.push({
			path: here.map(clean),
			raw: here,
			name: clean(node.getName()),
			mesh: node.getMesh(),
			world
		});
	}
	for (const child of node.listChildren()) walk(child, here);
})(main, []);

function bounds(mesh, m) {
	const lo = [Infinity, Infinity, Infinity];
	const hi = [-Infinity, -Infinity, -Infinity];
	for (const prim of mesh.listPrimitives()) {
		const pos = prim.getAttribute('POSITION');
		const [a, b] = [pos.getMin([]), pos.getMax([])];
		for (const x of [a[0], b[0]])
			for (const y of [a[1], b[1]])
				for (const z of [a[2], b[2]]) {
					const p = point(m, [x, y, z]);
					for (let i = 0; i < 3; i++) {
						lo[i] = Math.min(lo[i], p[i]);
						hi[i] = Math.max(hi[i], p[i]);
					}
				}
	}
	return [lo, hi];
}
const center = ([lo, hi]) => lo.map((v, i) => (v + hi[i]) / 2);
for (const p of parts) p.box = bounds(p.mesh, p.world);

const dropped = new Map();
const kept = parts.filter((p) => {
	const size = Math.hypot(...p.box[1].map((v, i) => v - p.box[0][i]));
	const out =
		DROP_ASSEMBLIES.test(p.path[1]) || (DROP.test(p.name) && !KEEP.test(p.name)) || size < MIN_PART;
	if (out) dropped.set(p.name, (dropped.get(p.name) ?? 0) + 1);
	return !out;
});

// ---------------------------------------------------------------- surfaces
// A part's surfaces, one per look, welded and simplified. The CAD's mesh keeps
// every face apart; welding joins what meets smoothly and leaves each crease
// as a seam the simplifier keeps.
const prepared = new Map();
function surfaces(part) {
	const cacheKey = part.mesh;
	if (prepared.has(cacheKey)) return prepared.get(cacheKey);
	const byLook = new Map();
	for (const prim of part.mesh.listPrimitives()) {
		const l = look(part, prim);
		const list = byLook.get(l) ?? [];
		list.push(prim);
		byLook.set(l, list);
	}
	const result = [];
	for (const [l, prims] of byLook) {
		const pos = [];
		const nor = [];
		const idx = [];
		const seen = new Map();
		for (const prim of prims) {
			const p = prim.getAttribute('POSITION').getArray();
			const n = prim.getAttribute('NORMAL').getArray();
			const remap = [];
			for (let v = 0; v < p.length / 3; v++) {
				const k = [
					Math.round(p[v * 3] * 1e6),
					Math.round(p[v * 3 + 1] * 1e6),
					Math.round(p[v * 3 + 2] * 1e6),
					Math.round(n[v * 3] * 1e3),
					Math.round(n[v * 3 + 1] * 1e3),
					Math.round(n[v * 3 + 2] * 1e3)
				].join(',');
				let i = seen.get(k);
				if (i === undefined) {
					i = pos.length / 3;
					seen.set(k, i);
					pos.push(p[v * 3], p[v * 3 + 1], p[v * 3 + 2]);
					nor.push(n[v * 3], n[v * 3 + 1], n[v * 3 + 2]);
				}
				remap.push(i);
			}
			for (const i of prim.getIndices().getArray()) idx.push(remap[i]);
		}
		const positions = new Float32Array(pos);
		const [kept] = MeshoptSimplifier.simplify(
			new Uint32Array(idx),
			positions,
			3,
			0,
			SIMPLIFY_ERROR,
			['ErrorAbsolute', 'Prune']
		);
		// Keep only the vertices the simplified triangles use.
		const used = new Map();
		const outPos = [];
		const outNor = [];
		const outIdx = new Uint32Array(kept.length);
		for (let k = 0; k < kept.length; k++) {
			let i = used.get(kept[k]);
			if (i === undefined) {
				i = used.size;
				used.set(kept[k], i);
				const v = kept[k];
				outPos.push(pos[v * 3], pos[v * 3 + 1], pos[v * 3 + 2]);
				outNor.push(nor[v * 3], nor[v * 3 + 1], nor[v * 3 + 2]);
			}
			outIdx[k] = i;
		}
		result.push({
			look: l,
			pos: outPos,
			nor: outNor,
			idx: outIdx,
			before: idx.length / 3
		});
	}
	prepared.set(cacheKey, result);
	return result;
}

// The look of a primitive: bins, dark parts (motors, boards, metal) or the body.
function look(part, prim) {
	if (BIN.test(part.name)) return 'bin';
	const c = prim.getMaterial()?.getBaseColorFactor() ?? [0.6, 0.6, 0.6, 1];
	const lum = 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2];
	return lum < 0.2 ? 'dark' : 'body';
}

// ---------------------------------------------------------------- what moves
const inChute = (p) => p.path[1] === '0002_Chute' || TURNS_WITH_CHUTE.test(p.name);
const chuteLayerOf = (p) =>
	p.raw.find((n) =>
		/^occurrence of gen4_chute_assembly <\d+>$|^gen4_chute_assembly <\d+>$/.test(n)
	);

// The chute's layers from the top, told apart by their flap's height.
const flaps = kept
	.filter((p) => p.name === 'gen3_chute_flap_print_side')
	.sort((a, b) => b.box[1][1] - a.box[1][1]);
const layerIndex = new Map(flaps.map((p, i) => [chuteLayerOf(p), i]));

// The flap's hinge, from the revolute mate in the chute layer's assembly: in
// the flap part's own frame, the axis is -X through this point.
const FLAP_HINGE = { origin: [0.055, 0.05228107663889009, 0.15041039995727876], axis: [-1, 0, 0] };

// The feeder's rotors from the top: C1 under the bucket, then C2, C3 and the
// classification channel's (C4). Named as the backend names their steppers.
const ROTOR_NAMES = ['c_channel_1', 'c_channel_2', 'c_channel_3', 'carousel'];
const rotors = kept
	.filter((p) => /^Rotor - /.test(p.name))
	.sort((a, b) => b.box[1][1] - a.box[1][1]);
// Each station's motor is the NEMA 17 nearest its rotor in height.
const feederMotors = kept.filter((p) => p.name === 'NEMA17 42-40');
const motorOf = new Map();
for (const [i, r] of rotors.entries()) {
	const y = center(r.box)[1];
	const near = (p) => Math.abs(center(p.box)[1] - y);
	motorOf.set(
		feederMotors.reduce((a, b) => (near(b) < near(a) ? b : a)),
		ROTOR_NAMES[i]
	);
}

// ---------------------------------------------------------------- bins
// The bin rings from the top. Each ring's base is its bins' lowest point; each
// bin kind is kept once, turned to the face at azimuth 0 and set on y = 0.
const rings = new Map();
for (const b of kept.filter((p) => BIN.test(p.name))) {
	const ring = b.raw[1];
	const r = rings.get(ring) ?? {
		kind: BIN.exec(b.name)[1],
		base: Infinity,
		top: -Infinity,
		bins: []
	};
	r.base = Math.min(r.base, b.box[0][1]);
	r.top = Math.max(r.top, b.box[1][1]);
	r.bins.push(b);
	rings.set(ring, r);
}
const levels = [...rings.values()].sort((a, b) => b.base - a.base);
const templates = new Map();
for (const level of levels)
	for (const b of level.bins) {
		const kind = BIN.exec(b.name).slice(1).join('_');
		const face = Math.round(azimuth(center(b.box)) / 60) * 60;
		if (!templates.has(kind))
			templates.set(kind, {
				part: b,
				local: mul(translate(0, -level.base, 0), mul(rotateY(-face), b.world))
			});
	}

// ---------------------------------------------------------------- output
const doc = new Document();
const buffer = doc.createBuffer();
const scene = doc.createScene('machine');
const materials = {};
for (const name of ['body', 'dark', 'bin'])
	materials[name] = doc
		.createMaterial(name)
		.setBaseColorFactor([0.7, 0.7, 0.7, 1])
		.setRoughnessFactor(0.8);
const instancing = doc.createExtension(EXTMeshGPUInstancing).setRequired(true);
const stats = { unique: 0, drawn: 0, calls: 0 };

// One mesh from parts, each at its matrix: a primitive per look.
function meshFrom(name, items) {
	const byLook = new Map();
	for (const { part, m } of items)
		for (const s of surfaces(part)) {
			const list = byLook.get(s.look) ?? [];
			list.push({ s, m });
			byLook.set(s.look, list);
		}
	if (!byLook.size) return null;
	const mesh = doc.createMesh(name);
	for (const [l, list] of byLook) {
		const vertices = list.reduce((n, { s }) => n + s.pos.length / 3, 0);
		const count = list.reduce((n, { s }) => n + s.idx.length, 0);
		const pos = new Float32Array(vertices * 3);
		const nor = new Float32Array(vertices * 3);
		const idx = new Uint32Array(count);
		let v = 0;
		let i = 0;
		for (const { s, m } of list) {
			for (let k = 0; k < s.pos.length; k += 3) {
				pos.set(point(m, [s.pos[k], s.pos[k + 1], s.pos[k + 2]]), v * 3 + k);
				const d = direction(m, [s.nor[k], s.nor[k + 1], s.nor[k + 2]]);
				const len = Math.hypot(...d) || 1;
				nor.set([d[0] / len, d[1] / len, d[2] / len], v * 3 + k);
			}
			for (let k = 0; k < s.idx.length; k++) idx[i + k] = s.idx[k] + v;
			v += s.pos.length / 3;
			i += s.idx.length;
		}
		stats.unique += count / 3;
		mesh.addPrimitive(
			doc
				.createPrimitive()
				.setMaterial(materials[l])
				.setAttribute(
					'POSITION',
					doc.createAccessor().setType('VEC3').setArray(pos).setBuffer(buffer)
				)
				.setAttribute(
					'NORMAL',
					doc.createAccessor().setType('VEC3').setArray(nor).setBuffer(buffer)
				)
				.setIndices(doc.createAccessor().setType('SCALAR').setArray(idx).setBuffer(buffer))
		);
	}
	return mesh;
}
const triangles = (mesh) =>
	mesh.listPrimitives().reduce((n, p) => n + p.getIndices().getCount() / 3, 0);

// A group of parts under one node at `at`: parts used once are merged, a part
// used more than once is stored once and instanced. `floor` is the height the
// group's frame starts from (a layer's ring base), so the page can set it at
// any height.
function group(name, list, parent, at = [0, 0, 0], floor = 0) {
	const n = doc.createNode(name).setTranslation(at);
	parent.addChild(n);
	const inverse = translate(-at[0], -at[1] - floor, -at[2]);
	const byMesh = new Map();
	for (const p of list) byMesh.set(p.mesh, [...(byMesh.get(p.mesh) ?? []), p]);
	const single = [];
	for (const [, copies] of byMesh) {
		if (copies.length === 1) {
			single.push({ part: copies[0], m: mul(inverse, copies[0].world) });
			continue;
		}
		const first = mul(inverse, copies[0].world);
		const mesh = meshFrom(`${name}: ${copies[0].name}`, [{ part: copies[0], m: first }]);
		if (!mesh) continue;
		const back = invertRigid(first);
		const t = [];
		const r = [];
		for (const p of copies) {
			const rel = mul(mul(inverse, p.world), back);
			t.push(rel[12], rel[13], rel[14]);
			r.push(...quaternion(rel));
		}
		const child = doc.createNode(`${name}: ${copies[0].name}`).setMesh(mesh);
		child.setExtension(
			'EXT_mesh_gpu_instancing',
			instancing
				.createInstancedMesh()
				.setAttribute(
					'TRANSLATION',
					doc.createAccessor().setType('VEC3').setArray(new Float32Array(t)).setBuffer(buffer)
				)
				.setAttribute(
					'ROTATION',
					doc.createAccessor().setType('VEC4').setArray(new Float32Array(r)).setBuffer(buffer)
				)
		);
		n.addChild(child);
		stats.drawn += triangles(mesh) * copies.length;
		stats.calls += mesh.listPrimitives().length;
	}
	// The merged parts go on a child: compression folds a scale and an offset
	// into the node that holds a mesh, and the group's node must stay a clean
	// pivot the page can turn.
	const mesh = meshFrom(name, single);
	if (mesh) {
		n.addChild(doc.createNode(`${name}-mesh`).setMesh(mesh));
		stats.drawn += triangles(mesh);
		stats.calls += mesh.listPrimitives().length;
	}
	return n;
}

// ---------------------------------------------------------------- layers
// The tower repeats every PITCH: the same brackets, retainers and posts at
// every layer, and the same chute layer (one kind with a funnel for three-bin
// layers, one for two-bin layers). The model keeps one of each; the page
// stacks as many as the machine has, under the top (feeder, drive,
// electronics), which stays where it is, and puts the base (legs, casters,
// the chute's bottom mount) under the lowest. The lowest layer stands on the
// base's legs, so the posts are kept apart and left out under it.
const PITCH = 0.16;
const CANON = 1;
const lowest = levels.length - 1;
const NEMA23 = '23HS32-4004S_nema23_stepper';
const bandOf = (p) => {
	const y = center(p.box)[1];
	return levels.findIndex((l) => y >= l.base - 0.03 && y < l.base + 0.13);
};
const isFrame = (p) =>
	!BIN.test(p.name) && !inChute(p) && !rotors.includes(p) && !motorOf.has(p) && p.name !== NEMA23;
const frameBands = new Map();
for (const p of kept.filter(isFrame)) {
	const b = bandOf(p);
	if (b >= 0) frameBands.set(p.name, (frameBands.get(p.name) ?? new Set()).add(b));
}
const repeats = (p) => (frameBands.get(p.name)?.size ?? 0) >= 2;
const isPost = (p) => !frameBands.get(p.name).has(lowest);

// A chute layer is the chute assembly its flap is in; the stack's own parts
// that repeat at every layer (its connectors) go with the nearest flap.
const flapY = flaps.map((f) => center(f.box)[1]);
const stackCount = new Map();
for (const p of kept.filter((p) => inChute(p) && layerIndex.get(chuteLayerOf(p)) === undefined))
	stackCount.set(p.name, (stackCount.get(p.name) ?? 0) + 1);
function chuteLayer(p) {
	const l = layerIndex.get(chuteLayerOf(p));
	if (l !== undefined) return l;
	if ((stackCount.get(p.name) ?? 0) < 2) return -1;
	const y = center(p.box)[1];
	return flapY.reduce(
		(best, fy, i) => (Math.abs(fy - y) < Math.abs(flapY[best] - y) ? i : best),
		0
	);
}
// Each chute kind is kept from a layer of that kind, away from the ends.
const chuteKinds = {};
for (const kind of new Set(levels.map((l) => l.kind))) {
	const inner = levels.findIndex((l, i) => i > 0 && i < lowest && l.kind === kind);
	chuteKinds[kind] = inner >= 0 ? inner : levels.findIndex((l) => l.kind === kind);
}

// Sort the parts into the groups the page places, moves or lights.
const top = [];
const base = [];
const layer = [];
const posts = [];
const chuteTop = [];
const chuteParts = flaps.map(() => ({ body: [], flap: [], servo: [] }));
const rotorParts = rotors.map(() => []);
const motorParts = new Map();
for (const p of kept) {
	if (BIN.test(p.name)) continue;
	if (inChute(p)) {
		const l = chuteLayer(p);
		if (l < 0) chuteTop.push(p);
		else if (p.name === 'gen3_chute_flap_print_side') chuteParts[l].flap.push(p);
		else if (p.name === 'MG995-1') chuteParts[l].servo.push(p);
		else chuteParts[l].body.push(p);
		continue;
	}
	const rotor = rotors.indexOf(p);
	if (rotor >= 0) {
		rotorParts[rotor].push(p);
		continue;
	}
	const motor = motorOf.get(p) ?? (p.name === NEMA23 ? 'chute' : null);
	if (motor) {
		motorParts.set(motor, [...(motorParts.get(motor) ?? []), p]);
		continue;
	}
	const band = bandOf(p);
	if (repeats(p) && band >= 0) {
		// Every layer's copy but one is made again by the page.
		if (band === CANON) (isPost(p) ? posts : layer).push(p);
	} else if (p.path[1] === 'bottom interface') base.push(p);
	else top.push(p);
}

group('top', top, scene);
group('base', base, scene, [0, 0, 0], levels[lowest].base);
group('layer', layer, scene, [0, 0, 0], levels[CANON].base);
group('layer-posts', posts, scene, [0, 0, 0], levels[CANON].base);
const chute = doc.createNode('chute');
scene.addChild(chute);
group('chute-top', chuteTop, chute);
const flapHinges = {};
for (const [kind, i] of Object.entries(chuteKinds)) {
	const floor = levels[i].base;
	const module = group(`chute-${kind}`, chuteParts[i].body, chute, [0, 0, 0], floor);
	const f = chuteParts[i].flap[0];
	const origin = point(f.world, FLAP_HINGE.origin);
	origin[1] -= floor;
	const axis = direction(f.world, FLAP_HINGE.axis);
	flapHinges[kind] = { origin: origin.map((v) => round(v)), axis: axis.map((v) => round(v)) };
	// Names are unique across the file: three.js's loader renames repeats.
	group(`flap-${kind}`, chuteParts[i].flap, module, origin, floor);
	group(`servo-${kind}`, chuteParts[i].servo, module, [0, 0, 0], floor);
}
const rotorPivots = [];
for (const [i, list] of rotorParts.entries()) {
	const c = center(rotors[i].box);
	group(`rotor-${ROTOR_NAMES[i]}`, list, scene, [c[0], 0, c[2]]);
	rotorPivots.push({ name: ROTOR_NAMES[i], at: [round(c[0]), round(c[2])] });
}
for (const [name, list] of motorParts) group(`motor-${name}`, list, scene);

// The bin kinds, which the page takes out of the scene and instances.
const binKinds = {};
const kinds = doc.createNode('bin-kinds');
scene.addChild(kinds);
for (const [kind, { part, local }] of templates) {
	const mesh = meshFrom(`bin-${kind}`, [{ part, m: local }]);
	const [lo, hi] = bounds(part.mesh, local);
	binKinds[kind] = { min: lo.map((v) => round(v)), max: hi.map((v) => round(v)) };
	kinds.addChild(doc.createNode(`bin-${kind}`).setMesh(mesh));
}

// Where the chute points when it is home: the outlet is opposite the stop that
// turns with it, and home is where the stop's leading edge meets the switch's
// roller (the chute comes home turning counterclockwise). Measured from the
// CAD, so the page can tell which face is section 0.
const find = (name) => parts.find((p) => p.name === name);
const outlet = azimuth(center(find('funnel_third').box));
const stop = find('limit_switch_stop');
const stopAz = azimuth(center(stop.box));
const stopRadius = Math.hypot(center(stop.box)[0], center(stop.box)[2]);
const stopHalfWidth =
	(Math.atan2((stop.box[1][2] - stop.box[0][2]) / 2, stopRadius) * 180) / Math.PI;
const rollerAz = azimuth(center(find('Limit roller toward stop').box));
const home = rollerAz - stopHalfWidth - (stopAz - outlet);

const boxes = kept.map((p) => p.box);
const box = [0, 1].map((k) =>
	[0, 1, 2].map((i) => (k ? Math.max : Math.min)(...boxes.map((b) => b[k][i])))
);

doc.getRoot().getAsset().extras = {
	machine: {
		version: 2,
		units: 'm',
		up: 'y',
		box: box.map((p) => p.map((v) => round(v))),
		// The CAD's bin rings from the top (the backend's layer 0 is the top
		// one), and how far apart layers are.
		levels: levels.map((l) => ({ kind: l.kind, base: round(l.base), top: round(l.top) })),
		pitch: PITCH,
		// Each chute kind's flap hinge, in its chute layer's frame.
		flaps: flapHinges,
		faces: [0, 60, 120, 180, 240, 300],
		binKinds,
		homeAzimuth: round((((home % 360) + 540) % 360) - 180, 2),
		rotors: rotorPivots,
		motors: [...motorParts.keys()]
	}
};

await doc.transform(meshopt({ encoder: MeshoptEncoder, level: 'medium' }));
const bytes = await io.writeBinary(doc);
writeFileSync(out, bytes);

const before = [...prepared.values()].flat().reduce((n, s) => n + s.before, 0);
console.log(
	`kept ${kept.length} of ${parts.length} parts; stored ${Math.round(stats.unique)} triangles (${Math.round(before)} before simplifying); ` +
		`drawn ${Math.round(stats.drawn)} in ${stats.calls} calls; ${(bytes.length / 1e6).toFixed(2)} MB`
);
console.log(
	'home azimuth',
	doc.getRoot().getAsset().extras.machine.homeAzimuth,
	'levels',
	levels.map((l) => `${l.kind}@${round(l.base, 3)}`).join(' ')
);
if (process.env.REPORT) {
	const cost = new Map();
	for (const p of kept) {
		const k = `${p.path[1]} :: ${p.name}`;
		const t = surfaces(p).reduce((n, s) => n + s.idx.length / 3, 0);
		const e = cost.get(k) ?? { n: 0, t };
		e.n++;
		cost.set(k, e);
	}
	const rows = [...cost].sort((a, b) => b[1].n * b[1].t - a[1].n * a[1].t);
	console.log(
		rows
			.slice(0, +process.env.REPORT)
			.map(([k, e]) => `${Math.round((e.n * e.t) / 1000)}k ${e.n}x${Math.round(e.t)} ${k}`)
			.join('\n')
	);
	console.log(
		'left out:',
		[...dropped]
			.sort((a, b) => b[1] - a[1])
			.map(([n, c]) => `${c}x ${n}`)
			.join(', ')
	);
}
