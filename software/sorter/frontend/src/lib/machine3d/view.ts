// The machine in 3D: the 3D page's three.js scene. It draws a frame only when
// something changed (the camera moved, the machine's state changed, or an
// animation is still running), never on a timer, and nothing while the tab is
// hidden. Everything the page asks of it goes through the methods below.
//
// The model (see model.ts) is fetched once per visit and kept for the next; its
// fixed parts are a few merged meshes and instanced repeats, and the bins are
// instanced from the machine's own layout, so a frame is about a hundred draw
// calls however many bins there are. Bin labels are one instanced quad per bin
// reading from one texture, so they cost no DOM and hide behind what is in
// front of them like any other surface.
import {
	Box3,
	BufferGeometry,
	CanvasTexture,
	Color,
	DirectionalLight,
	Euler,
	HemisphereLight,
	InstancedBufferAttribute,
	InstancedMesh,
	Material,
	Matrix4,
	Mesh,
	MeshBasicMaterial,
	MOUSE,
	MeshStandardMaterial,
	Object3D,
	PerspectiveCamera,
	PlaneGeometry,
	Quaternion,
	Raycaster,
	Scene,
	SRGBColorSpace,
	Vector2,
	Vector3,
	WebGLRenderer
} from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { MeshoptDecoder } from 'three/addons/libs/meshopt_decoder.module.js';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { MODEL, type Manifest } from './model';
import type { BinPlace } from './layout';

// Each bin kind's mesh, and the transform its node gives it.
type BinKinds = Map<string, { geometry: BufferGeometry; local: Matrix4 }>;
type Loaded = { scene: Object3D; manifest: Manifest; kinds: BinKinds };
let loading: Promise<Loaded> | null = null;

/** The model, fetched and parsed once, then kept for the next visit. The bin
 *  kinds come out of the scene; the view instances them. */
export function loadModel(): Promise<Loaded> {
	loading ??= new GLTFLoader()
		.setMeshoptDecoder(MeshoptDecoder)
		.loadAsync(MODEL.url)
		.then((gltf) => {
			const kinds: BinKinds = new Map();
			const holder = gltf.scene.getObjectByName('bin-kinds');
			for (const child of holder?.children ?? [])
				if (child instanceof Mesh) {
					child.updateMatrix();
					kinds.set(child.name.replace(/^bin-/, ''), {
						geometry: child.geometry,
						local: child.matrix.clone()
					});
				}
			holder?.removeFromParent();
			return {
				scene: gltf.scene,
				manifest: gltf.parser.json.asset.extras.machine as Manifest,
				kinds
			};
		})
		.catch((err) => {
			loading = null;
			throw err;
		});
	return loading;
}

export type Theme = {
	canvas: string;
	surface: string;
	ink: string;
	primary: string;
	success: string;
	info: string;
	dark: boolean;
};

export type DoorState = { open: number; calibrated: boolean };

// How far a flap swings between closed and open, and how fast things move
// when the backend does not say.
const FLAP_SWING = (40 * Math.PI) / 180;
const FLAP_SPEED = 3; // swings a second
const CHUTE_SPEED = 180; // degrees a second
const GLOW_FADE = 1.2; // seconds for a bin's light to fade
// A label's texture cell, in pixels, and how many to a row of the atlas.
const CELL = { w: 256, h: 64 };
const ATLAS_COLUMNS = 16;

// A kind's bins, and (seeing inside) the ones that are lit, drawn solid over the ghosts.
type BinBatch = { mesh: InstancedMesh; lit: InstancedMesh; places: BinPlace[] };

export class MachineView {
	private renderer: WebGLRenderer;
	private scene = new Scene();
	private camera = new PerspectiveCamera(30, 1, 0.05, 30);
	private controls: OrbitControls;
	private resizeObserver: ResizeObserver;
	private manifest: Manifest;
	private root: Object3D;
	private chute: Object3D;
	private flaps: { node: Object3D; axis: Vector3; rest: Quaternion }[] = [];
	private servos: Mesh[][] = [];
	private motors = new Map<string, Mesh[]>();
	private kinds: BinKinds;
	private batches: BinBatch[] = [];
	private byKey = new Map<string, { batch: BinBatch; index: number }>();
	// Each surface's own material, to go back to when it stops being lit.
	private own = new Map<Mesh, Material>();
	private labels: InstancedMesh | null = null;
	private atlas: CanvasTexture | null = null;
	private raycaster = new Raycaster();
	private frame = 0;
	private last = 0;
	private disposed = false;

	// What the machine is doing, and what is drawn of it now.
	private chuteShown = 0;
	private chuteTarget = 0;
	private chuteSpeed = CHUTE_SPEED;
	private doorShown: number[] = [];
	private doorTarget: number[] = [];
	private glow = new Map<string, number>();
	private aimedKey: string | null = null;
	private selectedKey: string | null = null;
	private hoverKey: string | null = null;
	private seeInside = false;
	private azimuthOf: (angle: number) => number = (a) => -a;

	private theme: Theme | null = null;
	private colors = {
		bin: new Color(),
		off: new Color(),
		primary: new Color(),
		success: new Color(),
		info: new Color(),
		hover: new Color()
	};
	private outer = {
		body: new MeshStandardMaterial({ roughness: 0.85 }),
		dark: new MeshStandardMaterial({ roughness: 0.7 }),
		bin: new MeshStandardMaterial({ roughness: 0.9 })
	};
	private ghost = {
		body: ghostMaterial(),
		dark: ghostMaterial(),
		bin: ghostMaterial()
	};
	// The look of every surface that becomes a ghost seeing inside, and each
	// surface's material otherwise.
	private outerLook = new Map<Mesh, 'body' | 'dark' | 'bin'>();
	private normal = new Map<Mesh, Material>();
	private depthOnly = new MeshBasicMaterial({ colorWrite: false });
	private twins: Mesh[] = [];
	private inner = {
		body: new MeshStandardMaterial({ roughness: 0.85 }),
		dark: new MeshStandardMaterial({ roughness: 0.7 }),
		active: new MeshStandardMaterial({ roughness: 0.6 })
	};
	private labelMaterial = new MeshBasicMaterial({ transparent: true });
	private hemisphere = new HemisphereLight(0xffffff, 0x444444, 1.1);
	private key = new DirectionalLight(0xffffff, 2.2);

	constructor(canvas: HTMLCanvasElement, loaded: Loaded) {
		this.manifest = loaded.manifest;
		this.kinds = loaded.kinds;
		this.renderer = new WebGLRenderer({
			canvas,
			antialias: true,
			powerPreference: 'high-performance'
		});
		this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
		this.renderer.outputColorSpace = SRGBColorSpace;

		// The key light rides with the camera, up and to the left, so the side
		// being looked at is always lit the same way.
		this.key.position.set(-1, 1.2, 1);
		this.camera.add(this.key);
		this.scene.add(this.camera, this.hemisphere);

		this.root = loaded.scene;
		this.scene.add(this.root);
		this.chute = this.root.getObjectByName('chute')!;
		this.adoptModel();

		this.controls = new OrbitControls(this.camera, canvas);
		this.controls.enableDamping = true;
		this.controls.dampingFactor = 0.12;
		// The right button is the bins' menu; pan with shift or two fingers.
		this.controls.mouseButtons = { LEFT: MOUSE.ROTATE, MIDDLE: MOUSE.DOLLY, RIGHT: null };
		this.controls.addEventListener('change', () => this.invalidate());

		this.resizeObserver = new ResizeObserver(() => this.resize());
		this.resizeObserver.observe(canvas);
		this.resize();
		this.frameMachine();
		void this.warm();
	}

	/** Compiles, in the background, the shaders that seeing inside needs, so
	 *  the first switch does not stall a frame. */
	private async warm() {
		const on = this.seeInside;
		for (const t of this.twins) t.visible = true;
		for (const [mesh, look] of this.outerLook) mesh.material = this.ghost[look];
		try {
			await this.renderer.compileAsync(this.scene, this.camera);
		} catch {
			// compiled on first use instead
		}
		if (this.disposed) return;
		this.setSeeInside(on);
	}

	// ------------------------------------------------------------ the model
	private adoptModel() {
		// Every surface takes one of the view's materials, by the look the model
		// gave it. Seeing inside, the doors and their servos stay solid and
		// everything else, the chute's body too, becomes a ghost.
		const solid = new Set<Object3D>();
		for (let i = 0; i < this.manifest.levels.length; i++)
			for (const name of [`flap-${i}`, `servo-${i}`]) {
				const node = this.chute.getObjectByName(name);
				if (node) solid.add(node);
			}
		this.root.traverse((o) => {
			if (!(o instanceof Mesh)) return;
			const look = (o.material as Material).name as 'body' | 'dark' | 'bin';
			let inChute = false;
			let isSolid = false;
			for (let p: Object3D | null = o; p; p = p.parent) {
				if (p === this.chute) inChute = true;
				if (solid.has(p)) isSolid = true;
			}
			o.material = inChute
				? look === 'dark'
					? this.inner.dark
					: this.inner.body
				: this.outer[look];
			this.own.set(o, o.material as Material);
			this.normal.set(o, o.material as Material);
			if (isSolid) o.renderOrder = -1;
			else this.outerLook.set(o, look);
		});
		for (const mesh of this.outerLook.keys()) this.twin(mesh);
		for (const [i, level] of this.manifest.levels.entries()) {
			const node = this.chute.getObjectByName(`flap-${i}`);
			if (!node || !level.flap) continue;
			this.flaps.push({
				node,
				axis: new Vector3(...level.flap.axis).normalize(),
				rest: node.quaternion.clone()
			});
			const servo: Mesh[] = [];
			this.chute.getObjectByName(`servo-${i}`)?.traverse((o) => o instanceof Mesh && servo.push(o));
			this.servos.push(servo);
		}
		this.doorShown = this.flaps.map(() => 0);
		this.doorTarget = this.flaps.map(() => 0);
		for (const name of this.manifest.motors) {
			const meshes: Mesh[] = [];
			this.root
				.getObjectByName(`motor-${name}`)
				?.traverse((o) => o instanceof Mesh && meshes.push(o));
			this.motors.set(name, meshes);
		}
		this.root.updateMatrixWorld(true);
	}

	private frameMachine() {
		const [lo, hi] = this.manifest.box;
		const box = new Box3(new Vector3(...lo), new Vector3(...hi));
		const centre = box.getCenter(new Vector3());
		const size = box.getSize(new Vector3());
		const radius = size.length() / 2;
		// Far enough that the machine's height, and its width, fit with a margin.
		const tan = Math.tan((this.camera.fov * Math.PI) / 360);
		const distance =
			Math.max(
				size.y / 2 / tan,
				Math.max(size.x, size.z) / 2 / (tan * Math.max(this.camera.aspect, 0.5))
			) * 1.25;
		const az = (35 * Math.PI) / 180;
		const el = (18 * Math.PI) / 180;
		this.camera.position.set(
			centre.x + distance * Math.cos(el) * Math.cos(az),
			centre.y + distance * Math.sin(el),
			centre.z - distance * Math.cos(el) * Math.sin(az)
		);
		this.controls.target.copy(centre);
		this.controls.minDistance = radius * 0.4;
		this.controls.maxDistance = distance * 2;
		this.controls.maxPolarAngle = Math.PI * 0.62;
		this.controls.update();
	}

	// ------------------------------------------------------------ what the page sets
	setTheme(theme: Theme) {
		this.theme = theme;
		const canvas = new Color(theme.canvas);
		const ink = new Color(theme.ink);
		const mix = (t: number) => canvas.clone().lerp(ink, t);
		// The view is a panel's content, so it sits on the surface.
		this.scene.background = new Color(theme.surface);
		// The bins are what the page is about, so they carry the most contrast;
		// the frame steps back.
		const body = mix(theme.dark ? 0.3 : 0.2);
		const dark = mix(theme.dark ? 0.14 : 0.66);
		this.colors.bin = mix(theme.dark ? 0.55 : 0.46);
		this.colors.off = mix(theme.dark ? 0.2 : 0.16);
		this.colors.primary = new Color(theme.primary);
		this.colors.success = new Color(theme.success);
		this.colors.info = new Color(theme.info);
		this.colors.hover = this.colors.bin.clone().lerp(this.colors.primary, 0.3);
		this.outer.body.color.copy(body);
		this.outer.dark.color.copy(dark);
		this.ghost.body.color.copy(body);
		this.ghost.dark.color.copy(dark);
		this.ghost.bin.color.set(0xffffff);
		this.outer.bin.color.set(0xffffff);
		this.inner.body.color.copy(body);
		this.inner.dark.color.copy(dark);
		this.inner.active.color.copy(this.colors.success);
		this.hemisphere.groundColor.copy(canvas.clone().lerp(new Color(0), 0.5));
		this.paintBins();
		this.drawLabels();
		this.invalidate();
	}

	private labelText: string[] = [];

	/** The bins, placed from the machine's layout, and each one's label. */
	setBins(places: BinPlace[], labels: string[]) {
		for (const b of this.batches) {
			b.mesh.removeFromParent();
			b.mesh.dispose();
			b.lit.removeFromParent();
			b.lit.dispose();
			this.twins = this.twins.filter((t) => t.parent !== b.mesh);
		}
		this.batches = [];
		this.byKey.clear();
		const byKind = new Map<string, BinPlace[]>();
		for (const p of places)
			if (this.kinds.has(p.kind)) byKind.set(p.kind, [...(byKind.get(p.kind) ?? []), p]);
		const m = new Matrix4();
		for (const [kind, list] of byKind) {
			const { geometry, local } = this.kinds.get(kind)!;
			const mesh = new InstancedMesh(
				geometry,
				this.seeInside ? this.ghost.bin : this.outer.bin,
				list.length
			);
			mesh.name = `bins ${kind}`;
			const lit = new InstancedMesh(geometry, this.outer.bin, list.length);
			lit.count = 0;
			lit.visible = this.seeInside;
			lit.renderOrder = -1;
			lit.frustumCulled = false;
			lit.matrixAutoUpdate = false;
			lit.raycast = () => {};
			this.root.add(lit);
			const batch = { mesh, lit, places: list };
			list.forEach((p, i) => {
				mesh.setMatrixAt(i, this.binMatrix(p, m).multiply(local));
				this.byKey.set(p.key, { batch, index: i });
			});
			mesh.computeBoundingSphere();
			mesh.matrixAutoUpdate = false;
			this.root.add(mesh);
			this.twin(mesh);
			this.batches.push(batch);
		}
		this.labelText = [];
		this.buildLabels(places, labels);
		this.paintBins();
		this.invalidate();
	}

	/** A copy of a surface that only writes depth, for seeing inside. */
	private twin(mesh: Mesh) {
		let twin: Mesh;
		if (mesh instanceof InstancedMesh) {
			const copy = new InstancedMesh(mesh.geometry, this.depthOnly, mesh.count);
			copy.instanceMatrix = mesh.instanceMatrix;
			twin = copy;
		} else twin = new Mesh(mesh.geometry, this.depthOnly);
		twin.visible = this.seeInside;
		twin.raycast = () => {};
		mesh.add(twin);
		this.twins.push(twin);
	}

	private binMatrix(p: BinPlace, into: Matrix4) {
		const level = this.manifest.levels[p.level];
		const face = new Matrix4().makeRotationY((p.faceAzimuth * Math.PI) / 180);
		const along = new Matrix4()
			.makeTranslation(0, 0, p.along)
			.multiply(new Matrix4().makeScale(1, 1, p.widthScale));
		return into.makeTranslation(0, level.base, 0).multiply(face).multiply(along);
	}

	/** The chute's position in the backend's degrees, and how fast it gets there. */
	setChute(angle: number, opts: { jump?: boolean; durationMs?: number } = {}) {
		this.chuteTarget = angle;
		if (opts.jump) this.chuteShown = angle;
		const delta = Math.abs(angle - this.chuteShown);
		this.chuteSpeed = opts.durationMs && delta > 0 ? delta / (opts.durationMs / 1000) : CHUTE_SPEED;
		this.invalidate();
	}

	/** How the backend's chute degrees turn into the model's azimuths (layout.ts). */
	setChuteFrame(azimuthOf: (angle: number) => number) {
		this.azimuthOf = azimuthOf;
		this.invalidate();
	}

	/** Each layer's door, from the top: 0 closed (catching), 1 open (passing). */
	setDoors(doors: DoorState[], opts: { jump?: boolean } = {}) {
		doors.forEach((d, i) => {
			if (i >= this.doorTarget.length) return;
			this.doorTarget[i] = d.open;
			if (opts.jump) this.doorShown[i] = d.open;
		});
		this.invalidate();
	}

	/** Light a bin for a piece on its way to it; it fades once the piece is in. */
	lightBin(key: string, on: boolean) {
		if (on) this.glow.set(key, 1);
		else if (this.glow.has(key)) this.glow.set(key, Math.min(this.glow.get(key)!, 0.999));
		this.paintBins();
		this.invalidate();
	}

	setAimed(key: string | null) {
		if (key === this.aimedKey) return;
		this.aimedKey = key;
		this.paintBins();
		this.invalidate();
	}

	select(key: string | null) {
		this.selectedKey = key;
		this.paintBins();
		this.invalidate();
	}

	hover(key: string | null) {
		if (key === this.hoverKey) return;
		this.hoverKey = key;
		this.paintBins();
		this.invalidate();
	}

	/** See through the frame and the bins, to the chute and its doors. */
	setSeeInside(on: boolean) {
		this.seeInside = on;
		// The frame and the bins become faint, unlit ghosts. Each has a twin that
		// only writes depth, drawn after the chute and before the ghosts, so only
		// the nearest ghost surface is blended over the chute: several layers of
		// translucency over every pixel cost four times a normal frame.
		for (const [mesh, look] of this.outerLook) {
			const m = on ? this.ghost[look] : this.normal.get(mesh)!;
			this.own.set(mesh, m);
			mesh.material = m;
		}
		for (const b of this.batches) {
			b.mesh.material = on ? this.ghost.bin : this.outer.bin;
			b.lit.visible = on;
		}
		for (const t of this.twins) t.visible = on;
		this.paintBins();
		if (this.labels) this.labels.visible = !on;
		this.invalidate();
	}

	/** The bin under a point on the canvas, if any. */
	pick(clientX: number, clientY: number): BinPlace | null {
		const rect = this.renderer.domElement.getBoundingClientRect();
		const ndc = new Vector2(
			((clientX - rect.left) / rect.width) * 2 - 1,
			-((clientY - rect.top) / rect.height) * 2 + 1
		);
		this.raycaster.setFromCamera(ndc, this.camera);
		const hit = this.raycaster.intersectObjects(
			this.batches.map((b) => b.mesh),
			false
		)[0];
		if (!hit || hit.instanceId === undefined) return null;
		const batch = this.batches.find((b) => b.mesh === hit.object);
		return batch?.places[hit.instanceId] ?? null;
	}

	// ------------------------------------------------------------ labels
	private buildLabels(places: BinPlace[], labels: string[]) {
		this.labels?.removeFromParent();
		this.labels?.dispose();
		this.labels = null;
		if (!places.length) return;
		const count = places.length;
		const rows = Math.ceil(count / ATLAS_COLUMNS);
		const quad = new PlaneGeometry(1, 1);
		const cells = new Float32Array(count * 2);
		const mesh = new InstancedMesh(quad, this.labelMaterial, count);
		const m = new Matrix4();
		const q = new Quaternion().setFromEuler(new Euler(0, Math.PI / 2, 0));
		places.forEach((p, i) => {
			cells[i * 2] = (i % ATLAS_COLUMNS) / ATLAS_COLUMNS;
			cells[i * 2 + 1] = 1 - (Math.floor(i / ATLAS_COLUMNS) + 1) / rows;
			// On the bin's outer face, a little in front of it, across its lower half.
			const kind = this.manifest.binKinds[p.kind];
			const width = (kind.max[2] - kind.min[2]) * p.widthScale * 0.86;
			const height = width * (CELL.h / CELL.w);
			const local = new Vector3(
				kind.max[0] + 0.002,
				kind.min[1] + (kind.max[1] - kind.min[1]) * 0.32,
				(kind.min[2] + kind.max[2]) / 2
			);
			const level = this.manifest.levels[p.level];
			const face = new Matrix4().makeRotationY((p.faceAzimuth * Math.PI) / 180);
			const at = local
				.clone()
				.add(new Vector3(0, 0, p.along))
				.applyMatrix4(face)
				.add(new Vector3(0, level.base, 0));
			const turn = new Quaternion().setFromRotationMatrix(face).multiply(q);
			mesh.setMatrixAt(i, m.compose(at, turn, new Vector3(width, height, 1)));
		});
		quad.setAttribute('cellOffset', new InstancedBufferAttribute(cells, 2));
		const cellSize = { value: new Vector2(1 / ATLAS_COLUMNS, 1 / rows) };
		this.labelMaterial.onBeforeCompile = (shader) => {
			shader.uniforms.cellSize = cellSize;
			shader.vertexShader = shader.vertexShader
				.replace(
					'#include <common>',
					'#include <common>\nattribute vec2 cellOffset;\nuniform vec2 cellSize;'
				)
				.replace(
					'#include <uv_vertex>',
					'#include <uv_vertex>\n#ifdef USE_MAP\nvMapUv = cellOffset + uv * cellSize;\n#endif'
				);
		};
		this.labelMaterial.customProgramCacheKey = () => 'machine3d-label';
		this.labelMaterial.needsUpdate = true;
		mesh.matrixAutoUpdate = false;
		mesh.visible = !this.seeInside;
		this.labels = mesh;
		this.labelText = labels;
		this.root.add(mesh);
		this.drawLabels();
	}

	private drawLabels() {
		if (!this.labels || !this.theme) return;
		const count = this.labelText.length;
		const rows = Math.ceil(count / ATLAS_COLUMNS);
		const canvas = document.createElement('canvas');
		canvas.width = CELL.w * ATLAS_COLUMNS;
		canvas.height = CELL.h * rows;
		const g = canvas.getContext('2d')!;
		const font = getComputedStyle(document.body).fontFamily || 'sans-serif';
		g.font = `500 21px ${font}`;
		g.textBaseline = 'middle';
		this.labelText.forEach((text, i) => {
			const x = (i % ATLAS_COLUMNS) * CELL.w;
			const y = Math.floor(i / ATLAS_COLUMNS) * CELL.h;
			if (!text) return;
			g.fillStyle = this.theme!.surface;
			g.fillRect(x, y, CELL.w, CELL.h);
			g.fillStyle = this.theme!.ink;
			const lines = wrap(g, text, CELL.w - 20, 2);
			lines.forEach((line, n) =>
				g.fillText(line, x + 10, y + CELL.h / 2 + (n - (lines.length - 1) / 2) * 25)
			);
		});
		this.atlas?.dispose();
		this.atlas = new CanvasTexture(canvas);
		this.atlas.colorSpace = SRGBColorSpace;
		this.atlas.anisotropy = Math.min(8, this.renderer.capabilities.getMaxAnisotropy());
		this.labelMaterial.map = this.atlas;
		this.labelMaterial.needsUpdate = true;
		this.invalidate();
	}

	// ------------------------------------------------------------ drawing
	private paintBins() {
		const c = new Color();
		const m = new Matrix4();
		for (const { mesh, lit, places } of this.batches) {
			let n = 0;
			places.forEach((p, i) => {
				c.copy(p.enabled && p.reachable ? this.colors.bin : this.colors.off);
				const glow = this.glow.get(p.key) ?? 0;
				const aimed = p.key === this.aimedKey;
				const chosen = p.key === this.selectedKey || p.key === this.hoverKey;
				if (aimed) c.lerp(this.colors.info, 0.35);
				if (glow > 0) c.lerp(this.colors.success, 0.75 * glow);
				if (p.key === this.hoverKey) c.lerp(this.colors.primary, 0.3);
				if (p.key === this.selectedKey) c.copy(this.colors.primary);
				mesh.setColorAt(i, c);
				if (this.seeInside && (aimed || glow > 0 || chosen)) {
					mesh.getMatrixAt(i, m);
					lit.setMatrixAt(n, m);
					lit.setColorAt(n, c);
					n++;
				}
			});
			if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true;
			lit.count = n;
			lit.instanceMatrix.needsUpdate = true;
			if (lit.instanceColor) lit.instanceColor.needsUpdate = true;
		}
	}

	/** Moves what is moving toward where it is going; true while anything still moves. */
	private step(dt: number): boolean {
		let moving = false;
		const d = this.chuteTarget - this.chuteShown;
		if (Math.abs(d) > 0.01) {
			const s = Math.sign(d) * Math.min(Math.abs(d), this.chuteSpeed * dt);
			this.chuteShown += s;
			moving = true;
		} else this.chuteShown = this.chuteTarget;
		this.chute.rotation.y = (this.azimuthOf(this.chuteShown) * Math.PI) / 180;
		this.setMotor('chute', Math.abs(d) > 0.01);

		const q = new Quaternion();
		this.flaps.forEach((f, i) => {
			const e = this.doorTarget[i] - this.doorShown[i];
			const swinging = Math.abs(e) > 0.001;
			if (swinging) this.doorShown[i] += Math.sign(e) * Math.min(Math.abs(e), FLAP_SPEED * dt);
			// The CAD has every flap open, flat against its outlet; a closed flap is
			// swung across the chute to turn the piece out into the bin.
			f.node.quaternion
				.copy(f.rest)
				.premultiply(q.setFromAxisAngle(f.axis, (1 - this.doorShown[i]) * FLAP_SWING));
			for (const m of this.servos[i] ?? []) this.light(m, swinging);
			moving ||= swinging;
		});

		let fading = false;
		for (const [key, v] of this.glow) {
			if (v >= 1) continue;
			const next = v - dt / GLOW_FADE;
			if (next <= 0) this.glow.delete(key);
			else this.glow.set(key, next);
			fading = true;
		}
		if (fading) this.paintBins();
		return moving || fading;
	}

	private setMotor(name: string, on: boolean) {
		for (const m of this.motors.get(name) ?? []) this.light(m, on);
	}

	private light(mesh: Mesh, on: boolean) {
		mesh.material = on ? this.inner.active : (this.own.get(mesh) ?? mesh.material);
	}

	invalidate() {
		if (!this.frame && !this.disposed) this.frame = requestAnimationFrame(this.draw);
	}

	private draw = (now: number) => {
		this.frame = 0;
		const dt = this.last ? Math.min(0.1, (now - this.last) / 1000) : 0;
		this.last = now;
		const moving = this.step(dt);
		this.controls.update();
		this.renderer.render(this.scene, this.camera);
		if (moving) this.invalidate();
		else this.last = 0;
	};

	private resize() {
		const canvas = this.renderer.domElement;
		const w = canvas.clientWidth;
		const h = canvas.clientHeight;
		if (!w || !h) return;
		this.renderer.setSize(w, h, false);
		this.camera.aspect = w / h;
		this.camera.updateProjectionMatrix();
		this.invalidate();
	}

	/** Times `frames` frames drawn back to back, waiting for the GPU each time. */
	bench(frames = 30): { ms: number; calls: number; triangles: number } {
		const gl = this.renderer.getContext();
		const px = new Uint8Array(4);
		// A few frames first, so a shader compiled on first use is not counted.
		for (let i = 0; i < 5; i++) {
			this.renderer.render(this.scene, this.camera);
			gl.readPixels(0, 0, 1, 1, gl.RGBA, gl.UNSIGNED_BYTE, px);
		}
		const t0 = performance.now();
		for (let i = 0; i < frames; i++) {
			this.camera.position.applyAxisAngle(new Vector3(0, 1, 0), 0.02);
			this.camera.lookAt(this.controls.target);
			this.renderer.render(this.scene, this.camera);
			gl.readPixels(0, 0, 1, 1, gl.RGBA, gl.UNSIGNED_BYTE, px);
		}
		const ms = (performance.now() - t0) / frames;
		const info = this.renderer.info.render;
		return { ms, calls: info.calls, triangles: info.triangles };
	}

	dispose() {
		this.disposed = true;
		cancelAnimationFrame(this.frame);
		this.resizeObserver.disconnect();
		this.controls.dispose();
		for (const b of this.batches) {
			b.mesh.removeFromParent();
			b.mesh.dispose();
			b.lit.removeFromParent();
			b.lit.dispose();
		}
		this.labels?.removeFromParent();
		this.labels?.geometry.dispose();
		this.atlas?.dispose();
		// The parsed model stays for the next visit, as it came; the GPU copy
		// goes with the context.
		for (const t of this.twins) t.removeFromParent();
		this.root.removeFromParent();
		this.renderer.dispose();
		this.renderer.forceContextLoss();
	}
}

function ghostMaterial() {
	return new MeshBasicMaterial({ transparent: true, opacity: 0.24, depthWrite: false });
}

function wrap(
	g: CanvasRenderingContext2D,
	text: string,
	width: number,
	maxLines: number
): string[] {
	const words = text.split(/\s+/);
	const lines: string[] = [];
	let line = '';
	for (const word of words) {
		const next = line ? `${line} ${word}` : word;
		if (g.measureText(next).width <= width || !line) line = next;
		else {
			lines.push(line);
			line = word;
		}
	}
	if (line) lines.push(line);
	if (lines.length > maxLines) {
		lines.length = maxLines;
		let last = lines[maxLines - 1];
		while (last.length > 1 && g.measureText(`${last}…`).width > width) last = last.slice(0, -1);
		lines[maxLines - 1] = `${last}…`;
	}
	return lines.map((l) => {
		let s = l;
		while (s.length > 1 && g.measureText(s).width > width) s = s.slice(0, -1);
		return s;
	});
}
