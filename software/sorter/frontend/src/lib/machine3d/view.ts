// The machine in 3D: the 3D page's three.js scene. It draws a frame only when
// something changed (the camera moved, the machine's state changed, or an
// animation is still running), never on a timer, and nothing while the tab is
// hidden. Everything the page asks of it goes through the methods below.
//
// The model (see model.ts) is fetched once per visit and kept for the next;
// each view draws its own copy of it, sharing the geometry. Its fixed parts are
// a few merged meshes and instanced repeats; the tower (each layer's frame and
// posts) and the bins are instanced from the machine's own layers and layout,
// so a frame is about a hundred draw calls however many layers and bins there
// are. The cards on the bins are one instanced quad per bin reading one
// texture, so they cost no DOM and hide behind what is in front of them.
import {
	Box3,
	BufferAttribute,
	BufferGeometry,
	CanvasTexture,
	Color,
	DirectionalLight,
	EdgesGeometry,
	Euler,
	HemisphereLight,
	InstancedBufferAttribute,
	InstancedMesh,
	LineSegments,
	type Material,
	Matrix4,
	Mesh,
	MeshBasicMaterial,
	MeshStandardMaterial,
	MOUSE,
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
import { LOOKS, makeLook, type LookMaterials, type LookName } from './looks';
import { CARD_STYLES, drawCards, type CardData, type CardStyle, type CardTheme } from './cards';

// Each bin kind's mesh, and the transform its node gives it.
type BinKinds = Map<string, { geometry: BufferGeometry; local: Matrix4 }>;
// The parts the view stacks for the machine's layers: one layer's frame, its
// posts, and one chute layer of each kind.
type Modules = { layer: Object3D; posts: Object3D; chute: Record<string, Object3D> };
type Loaded = { scene: Object3D; manifest: Manifest; kinds: BinKinds; modules: Modules };
type Surface = 'body' | 'dark' | 'bin';
let loading: Promise<Loaded> | null = null;

/** The model, fetched and parsed once, then kept for the next visit. The bin
 *  kinds and the stacked parts come out of the scene; the view instances them. */
export function loadModel(): Promise<Loaded> {
	loading ??= new GLTFLoader()
		.setMeshoptDecoder(MeshoptDecoder)
		.loadAsync(MODEL.url)
		.then((gltf) => {
			const scene = gltf.scene;
			// Each surface remembers its kind, since the view gives it its own material.
			scene.traverse((o) => {
				if (o instanceof Mesh) o.userData.surface = (o.material as Material).name || 'body';
			});
			const take = (name: string) => {
				const o = scene.getObjectByName(name);
				if (!o) throw new Error(`the model has no ${name}`);
				o.removeFromParent();
				o.updateMatrixWorld(true);
				return o;
			};
			const kinds: BinKinds = new Map();
			for (const child of take('bin-kinds').children)
				if (child instanceof Mesh)
					kinds.set(child.name.replace(/^bin-/, ''), {
						geometry: child.geometry,
						local: child.matrix.clone()
					});
			const modules: Modules = {
				layer: take('layer'),
				posts: take('layer-posts'),
				chute: { third: take('chute-third'), half: take('chute-half') }
			};
			const manifest = gltf.parser.json.asset.extras.machine as Manifest;
			return { scene, manifest, kinds, modules };
		})
		.catch((err) => {
			loading = null;
			throw err;
		});
	return loading;
}

export type Theme = CardTheme & {
	canvas: string;
	success: string;
	info: string;
	dark: boolean;
};

export type DoorState = { open: number; calibrated: boolean };

/** Where the camera looks from: degrees around and above, and how far away as
 *  a share of the distance that fits the whole machine. `target` is a point to
 *  look at instead of the machine's centre. */
export type CameraView = {
	azimuth: number;
	elevation: number;
	distance?: number;
	target?: Vector3;
};

// How far a flap swings between closed and open, and how fast things move
// when the backend does not say.
const FLAP_SWING = (40 * Math.PI) / 180;
const FLAP_SPEED = 3; // swings a second
const CHUTE_SPEED = 180; // degrees a second
const GLOW_FADE = 1.2; // seconds for a bin's light to fade
// Creases sharper than this get a line in the looks that draw lines.
const CREASE = 35;

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
	private modules: Modules;
	private kinds: BinKinds;
	// What was built for the machine's layers, and for how many of which kind.
	private tower: Object3D | null = null;
	private chuteLayers: Object3D[] = [];
	private layersKey = '';
	private framed = false;
	private view: CameraView = { azimuth: 35, elevation: 18 };
	private flaps: { node: Object3D; axis: Vector3; rest: Quaternion }[] = [];
	private servos: Mesh[][] = [];
	private motors = new Map<string, Mesh[]>();
	private batches: BinBatch[] = [];
	private places: BinPlace[] = [];
	private twins: Mesh[] = [];
	private lines: LineSegments[] = [];
	private cards: InstancedMesh | null = null;
	private atlas: CanvasTexture | null = null;
	private cardData: CardData[] = [];
	private cardStyle: CardStyle = 'paper';
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
	private look: LookName = 'lit';
	private colors = {
		body: new Color(),
		dark: new Color(),
		bin: new Color(),
		off: new Color(),
		line: new Color(),
		primary: new Color(),
		success: new Color(),
		info: new Color()
	};
	private mats: LookMaterials;
	private ghost = { body: ghostMaterial(), dark: ghostMaterial(), bin: ghostMaterial() };
	private active = new MeshStandardMaterial({ roughness: 0.6 });
	private depthOnly = new MeshBasicMaterial({ colorWrite: false });
	private cardMaterial = new MeshBasicMaterial({ transparent: true });
	private hemisphere = new HemisphereLight(0xffffff, 0x444444, 1.1);
	private key = new DirectionalLight(0xffffff, 2.2);

	constructor(canvas: HTMLCanvasElement, loaded: Loaded) {
		this.manifest = loaded.manifest;
		this.kinds = loaded.kinds;
		this.modules = loaded.modules;
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

		this.mats = makeLook(this.look, this.colors);
		this.root = loaded.scene.clone();
		this.scene.add(this.root);
		this.chute = this.root.getObjectByName('chute')!;
		this.adopt(this.root);
		for (const name of this.manifest.motors) {
			const meshes: Mesh[] = [];
			this.root
				.getObjectByName(`motor-${name}`)
				?.traverse((o) => o instanceof Mesh && meshes.push(o));
			this.motors.set(name, meshes);
		}

		this.controls = new OrbitControls(this.camera, canvas);
		this.controls.enableDamping = true;
		this.controls.dampingFactor = 0.12;
		// The right button is the bins' menu; pan with shift or two fingers.
		this.controls.mouseButtons = { LEFT: MOUSE.ROTATE, MIDDLE: MOUSE.DOLLY, RIGHT: null };
		this.controls.addEventListener('change', () => this.invalidate());

		this.resizeObserver = new ResizeObserver(() => this.resize());
		this.resizeObserver.observe(canvas);
		this.resize();
		void this.warm();
	}

	/** Compiles, in the background, the shaders that seeing inside needs, so
	 *  the first switch does not stall a frame. */
	private async warm() {
		const on = this.seeInside;
		this.seeInside = true;
		this.repaint();
		try {
			await this.renderer.compileAsync(this.scene, this.camera);
		} catch {
			// compiled on first use instead
		}
		if (this.disposed) return;
		this.seeInside = on;
		this.repaint();
	}

	// ------------------------------------------------------------ materials
	/** Marks every surface under `obj` with what decides its material, and
	 *  gives each one that becomes a ghost seeing inside its depth twin. The
	 *  doors and their servos stay solid seeing inside; everything else, the
	 *  chute's body too, becomes a ghost. */
	private adopt(obj: Object3D) {
		const ghosts: Mesh[] = [];
		obj.traverse((o) => {
			if (!(o instanceof Mesh) || o.userData.twin) return;
			let solid = false;
			for (let p: Object3D | null = o; p; p = p.parent)
				if (/^(flap|servo)-/.test(p.name)) solid = true;
			o.userData.solid = solid;
			if (solid) o.renderOrder = -1;
			else ghosts.push(o);
			o.material = this.materialFor(o);
		});
		// After the walk, which would otherwise walk into the twins it makes.
		for (const o of ghosts) this.twin(o);
		if (LOOKS.find((l) => l.name === this.look)?.lines) this.addLines(obj);
	}

	private materialFor(o: Mesh): Material {
		const surface = o.userData.surface as Surface;
		if (o.userData.lit) return this.active;
		if (this.seeInside && !o.userData.solid) return this.ghost[surface];
		return this.mats[surface];
	}

	/** Every surface's material again, after the look or seeing inside changed. */
	private repaint() {
		this.root.traverse((o) => {
			if (o instanceof Mesh && o.userData.surface && !o.userData.twin)
				o.material = this.materialFor(o);
		});
		for (const b of this.batches) {
			b.mesh.material = this.seeInside ? this.ghost.bin : this.mats.bin;
			b.lit.material = this.mats.bin;
			b.lit.visible = this.seeInside;
		}
		for (const t of this.twins) t.visible = this.seeInside;
		for (const l of this.lines) l.visible = !this.seeInside;
		if (this.cards) this.cards.visible = !this.seeInside;
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
		twin.userData.twin = true;
		twin.visible = this.seeInside;
		twin.raycast = () => {};
		mesh.add(twin);
		this.twins.push(twin);
	}

	private edges = new WeakMap<BufferGeometry, Float32Array>();

	/** Lines along the creases of every surface under `obj`: one set of lines
	 *  per mesh, with an instanced mesh's copies merged into it. */
	private addLines(obj: Object3D) {
		const meshes: Mesh[] = [];
		obj.traverse((o) => {
			if (o instanceof Mesh && o.userData.surface && !o.userData.twin) meshes.push(o);
		});
		const m = new Matrix4();
		const v = new Vector3();
		for (const mesh of meshes) {
			let e = this.edges.get(mesh.geometry);
			if (!e) {
				e = new EdgesGeometry(mesh.geometry, CREASE).getAttribute('position').array as Float32Array;
				this.edges.set(mesh.geometry, e);
			}
			const copies = mesh instanceof InstancedMesh ? mesh.count : 1;
			const out = new Float32Array(e.length * copies);
			for (let i = 0; i < copies; i++) {
				if (mesh instanceof InstancedMesh) mesh.getMatrixAt(i, m);
				else m.identity();
				for (let k = 0; k < e.length; k += 3) {
					v.set(e[k], e[k + 1], e[k + 2]).applyMatrix4(m);
					out.set([v.x, v.y, v.z], i * e.length + k);
				}
			}
			const g = new BufferGeometry();
			g.setAttribute('position', new BufferAttribute(out, 3));
			const lines = new LineSegments(g, this.mats.line);
			lines.userData.twin = true;
			lines.raycast = () => {};
			lines.visible = !this.seeInside;
			mesh.add(lines);
			this.lines.push(lines);
		}
	}

	private dropLines() {
		for (const l of this.lines) {
			l.removeFromParent();
			l.geometry.dispose();
		}
		this.lines = [];
	}

	private forget(obj: Object3D) {
		const inside = (t: Object3D) => {
			for (let p: Object3D | null = t; p; p = p.parent) if (p === obj) return true;
			return false;
		};
		this.twins = this.twins.filter((t) => !inside(t));
		this.lines = this.lines.filter((l) => {
			if (!inside(l)) return true;
			l.geometry.dispose();
			return false;
		});
	}

	/** Draws the machine another way (looks.ts). */
	setLook(name: LookName) {
		if (name === this.look) return;
		this.look = name;
		for (const m of Object.values(this.mats)) m.dispose();
		this.mats = makeLook(name, this.colors);
		this.dropLines();
		if (LOOKS.find((l) => l.name === name)?.lines) {
			this.addLines(this.root);
		}
		this.repaint();
	}

	// ------------------------------------------------------------ the tower
	/** Where layer `k` (0 the top) has its ring's base: the top stays where the
	 *  CAD has it and the layers hang under it. */
	levelBase(k: number) {
		return this.manifest.levels[0].base - k * this.manifest.pitch;
	}

	/** Builds the tower for the machine's layers, from the top: each one's bin
	 *  kind ('third' or 'half'), which picks its chute layer. The frame and the
	 *  posts are one instanced mesh per part for every layer, and the base goes
	 *  under the lowest layer. */
	setLayers(kinds: string[]) {
		const n = Math.max(1, kinds.length);
		const key = kinds.join(',') || 'third';
		if (key === this.layersKey) return;
		this.layersKey = key;
		for (const old of [this.tower, ...this.chuteLayers]) {
			if (!old) continue;
			this.forget(old);
			old.removeFromParent();
		}
		this.chuteLayers = [];
		const tower = new Object3D();
		tower.name = 'tower';
		this.stack(tower, this.modules.layer, [...Array(n).keys()]);
		this.stack(tower, this.modules.posts, [...Array(n - 1).keys()]);
		this.root.add(tower);
		this.adopt(tower);
		this.tower = tower;
		const base = this.root.getObjectByName('base');
		if (base) base.position.y = this.levelBase(n - 1);

		this.flaps = [];
		this.servos = [];
		for (let k = 0; k < n; k++) {
			const kind = this.modules.chute[kinds[k]] ? kinds[k] : 'third';
			const layer = this.modules.chute[kind].clone();
			layer.position.y = this.levelBase(k);
			this.chute.add(layer);
			this.adopt(layer);
			this.chuteLayers.push(layer);
			const flap = layer.getObjectByName(`flap-${kind}`);
			const hinge = this.manifest.flaps[kind];
			if (flap && hinge)
				this.flaps.push({
					node: flap,
					axis: new Vector3(...hinge.axis).normalize(),
					rest: flap.quaternion.clone()
				});
			const servo: Mesh[] = [];
			layer.getObjectByName(`servo-${kind}`)?.traverse((o) => o instanceof Mesh && servo.push(o));
			this.servos.push(servo);
		}
		this.doorShown = this.flaps.map((_, i) => this.doorShown[i] ?? 0);
		this.doorTarget = this.flaps.map((_, i) => this.doorTarget[i] ?? 0);
		this.root.updateMatrixWorld(true);
		if (!this.framed) {
			this.framed = true;
			this.setCamera(this.view);
		}
		this.invalidate();
	}

	/** Every mesh of `module`, once for each of the layers, as one instanced mesh. */
	private stack(into: Object3D, module: Object3D, layers: number[]) {
		if (!layers.length) return;
		const at = new Matrix4();
		const inst = new Matrix4();
		const m = new Matrix4();
		module.traverse((o) => {
			if (!(o instanceof Mesh)) return;
			const per = o instanceof InstancedMesh ? o.count : 1;
			const mesh = new InstancedMesh(o.geometry, o.material, per * layers.length);
			mesh.userData.surface = o.userData.surface;
			let i = 0;
			for (const k of layers) {
				at.makeTranslation(0, this.levelBase(k), 0).multiply(o.matrixWorld);
				for (let j = 0; j < per; j++) {
					if (o instanceof InstancedMesh) o.getMatrixAt(j, inst);
					else inst.identity();
					mesh.setMatrixAt(i++, m.multiplyMatrices(at, inst));
				}
			}
			mesh.computeBoundingSphere();
			mesh.matrixAutoUpdate = false;
			into.add(mesh);
		});
	}

	// ------------------------------------------------------------ the camera
	/** Points the camera (see CameraView); the machine is framed to fit. */
	setCamera(view: CameraView) {
		this.view = view;
		const box = new Box3().setFromObject(this.root);
		const centre = view.target ?? box.getCenter(new Vector3());
		const size = box.getSize(new Vector3());
		const radius = size.length() / 2;
		// Far enough that the machine's height, and its width, fit with a margin.
		const tan = Math.tan((this.camera.fov * Math.PI) / 360);
		const fit =
			Math.max(
				size.y / 2 / tan,
				Math.max(size.x, size.z) / 2 / (tan * Math.max(this.camera.aspect, 0.5))
			) * 1.25;
		const distance = fit * (view.distance ?? 1);
		const az = (view.azimuth * Math.PI) / 180;
		const el = (view.elevation * Math.PI) / 180;
		this.camera.position.set(
			centre.x + distance * Math.cos(el) * Math.cos(az),
			centre.y + distance * Math.sin(el),
			centre.z - distance * Math.cos(el) * Math.sin(az)
		);
		this.controls.target.copy(centre);
		this.controls.minDistance = radius * 0.15;
		this.controls.maxDistance = fit * 2;
		this.controls.maxPolarAngle = Math.PI * 0.62;
		this.controls.update();
		this.invalidate();
	}

	/** The middle of a bin's front, for pointing the camera at it. */
	binFront(key: string): Vector3 | null {
		const p = this.places.find((b) => b.key === key);
		if (!p) return null;
		const k = this.manifest.binKinds[p.kind];
		const face = new Matrix4().makeRotationY((p.faceAzimuth * Math.PI) / 180);
		return new Vector3(k.max[0], (k.min[1] + k.max[1]) / 2, (k.min[2] + k.max[2]) / 2 + p.along)
			.applyMatrix4(face)
			.add(new Vector3(0, this.levelBase(p.level), 0));
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
		this.colors.body.copy(mix(theme.dark ? 0.3 : 0.2));
		this.colors.dark.copy(mix(theme.dark ? 0.14 : 0.66));
		this.colors.bin.copy(mix(theme.dark ? 0.55 : 0.46));
		this.colors.off.copy(mix(theme.dark ? 0.2 : 0.16));
		this.colors.line.copy(mix(theme.dark ? 0.62 : 0.72));
		this.colors.primary.set(theme.primary);
		this.colors.success.set(theme.success);
		this.colors.info.set(theme.info);
		// The look's materials take the new colours.
		for (const m of Object.values(this.mats)) m.dispose();
		this.mats = makeLook(this.look, this.colors);
		for (const l of this.lines) l.material = this.mats.line;
		this.ghost.body.color.copy(this.colors.body);
		this.ghost.dark.color.copy(this.colors.dark);
		this.ghost.bin.color.set(0xffffff);
		this.active.color.copy(this.colors.success);
		this.hemisphere.groundColor.copy(canvas.clone().lerp(new Color(0), 0.5));
		this.repaint();
		this.drawCards();
	}

	/** The bins, placed from the machine's layout, and what each one's card says. */
	setBins(places: BinPlace[], cards: CardData[]) {
		for (const b of this.batches) {
			this.forget(b.mesh);
			b.mesh.removeFromParent();
			b.mesh.dispose();
			b.lit.removeFromParent();
			b.lit.dispose();
		}
		this.batches = [];
		this.places = places;
		const byKind = new Map<string, BinPlace[]>();
		for (const p of places)
			if (this.kinds.has(p.kind)) byKind.set(p.kind, [...(byKind.get(p.kind) ?? []), p]);
		const m = new Matrix4();
		for (const [kind, list] of byKind) {
			const { geometry, local } = this.kinds.get(kind)!;
			const mesh = new InstancedMesh(
				geometry,
				this.seeInside ? this.ghost.bin : this.mats.bin,
				list.length
			);
			mesh.name = `bins ${kind}`;
			mesh.userData.surface = 'bin';
			const lit = new InstancedMesh(geometry, this.mats.bin, list.length);
			lit.count = 0;
			lit.visible = this.seeInside;
			lit.renderOrder = -1;
			lit.frustumCulled = false;
			lit.matrixAutoUpdate = false;
			lit.raycast = () => {};
			this.root.add(lit);
			list.forEach((p, i) => mesh.setMatrixAt(i, this.binMatrix(p, m).multiply(local)));
			mesh.computeBoundingSphere();
			mesh.matrixAutoUpdate = false;
			this.root.add(mesh);
			this.twin(mesh);
			if (LOOKS.find((l) => l.name === this.look)?.lines) this.addLines(mesh);
			// The bins take their colour per instance, not from their material.
			mesh.material = this.seeInside ? this.ghost.bin : this.mats.bin;
			this.batches.push({ mesh, lit, places: list });
		}
		this.cardData = cards;
		this.placeCards();
		this.paintBins();
		this.invalidate();
	}

	private binMatrix(p: BinPlace, into: Matrix4) {
		const face = new Matrix4().makeRotationY((p.faceAzimuth * Math.PI) / 180);
		const along = new Matrix4()
			.makeTranslation(0, 0, p.along)
			.multiply(new Matrix4().makeScale(1, 1, p.widthScale));
		return into.makeTranslation(0, this.levelBase(p.level), 0).multiply(face).multiply(along);
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

	/** See through the frame and the bins, to the chute and its doors. The
	 *  frame and the bins become faint, unlit ghosts. Each has a twin that only
	 *  writes depth, drawn after the chute and before the ghosts, so only the
	 *  nearest ghost surface is blended over the chute: several layers of
	 *  translucency over every pixel cost four times a normal frame. */
	setSeeInside(on: boolean) {
		if (on === this.seeInside) return;
		this.seeInside = on;
		this.repaint();
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

	// ------------------------------------------------------------ cards
	/** How each bin's card is drawn (cards.ts). */
	setCardStyle(style: CardStyle) {
		if (style === this.cardStyle) return;
		this.cardStyle = style;
		this.placeCards();
	}

	private placeCards() {
		this.cards?.removeFromParent();
		this.cards?.dispose();
		this.cards = null;
		const places = this.places;
		if (!places.length) return;
		const shape = CARD_STYLES.find((s) => s.name === this.cardStyle)!;
		const quad = new PlaneGeometry(1, 1);
		const mesh = new InstancedMesh(quad, this.cardMaterial, places.length);
		const m = new Matrix4();
		const q = new Quaternion().setFromEuler(new Euler(0, Math.PI / 2, 0));
		places.forEach((p, i) => {
			// On the bin's front, just in front of it.
			const kind = this.manifest.binKinds[p.kind];
			const width = (kind.max[2] - kind.min[2]) * p.widthScale * shape.width;
			const local = new Vector3(
				kind.max[0] + shape.offset,
				kind.min[1] + (kind.max[1] - kind.min[1]) * shape.lift,
				(kind.min[2] + kind.max[2]) / 2 + p.along
			);
			const face = new Matrix4().makeRotationY((p.faceAzimuth * Math.PI) / 180);
			const at = local.applyMatrix4(face).add(new Vector3(0, this.levelBase(p.level), 0));
			const turn = new Quaternion().setFromRotationMatrix(face).multiply(q);
			mesh.setMatrixAt(i, m.compose(at, turn, new Vector3(width, width / shape.aspect, 1)));
		});
		mesh.matrixAutoUpdate = false;
		mesh.visible = !this.seeInside;
		mesh.raycast = () => {};
		this.cards = mesh;
		this.root.add(mesh);
		this.drawCards();
	}

	private drawCards() {
		if (!this.cards || !this.theme) return;
		const shape = CARD_STYLES.find((s) => s.name === this.cardStyle)!;
		const data = this.places.map((_, i) => this.cardData[i] ?? blankCard);
		const b = this.colors.bin.clone().convertLinearToSRGB();
		const onBin = 0.2126 * b.r + 0.7152 * b.g + 0.0722 * b.b > 0.45 ? '#1b1a18' : '#ffffff';
		const atlas = drawCards(shape, data, { ...this.theme, onBin });
		const cells = new Float32Array(data.length * 2);
		data.forEach((_, i) => {
			cells[i * 2] = (i % atlas.columns) / atlas.columns;
			cells[i * 2 + 1] = 1 - (Math.floor(i / atlas.columns) + 1) / atlas.rows;
		});
		this.cards.geometry.setAttribute('cellOffset', new InstancedBufferAttribute(cells, 2));
		const cellSize = { value: new Vector2(1 / atlas.columns, 1 / atlas.rows) };
		this.cardMaterial.onBeforeCompile = (shader) => {
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
		this.cardMaterial.customProgramCacheKey = () => `machine3d-card-${atlas.columns}x${atlas.rows}`;
		this.atlas?.dispose();
		this.atlas = new CanvasTexture(atlas.canvas);
		this.atlas.colorSpace = SRGBColorSpace;
		this.atlas.anisotropy = Math.min(8, this.renderer.capabilities.getMaxAnisotropy());
		this.cardMaterial.map = this.atlas;
		this.cardMaterial.needsUpdate = true;
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
		for (const m of this.motors.get('chute') ?? []) this.light(m, Math.abs(d) > 0.01);

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

	private light(mesh: Mesh, on: boolean) {
		if (!!mesh.userData.lit === on) return;
		mesh.userData.lit = on;
		mesh.material = this.materialFor(mesh);
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
		this.dropLines();
		for (const b of this.batches) {
			b.mesh.dispose();
			b.lit.dispose();
		}
		this.cards?.geometry.dispose();
		this.cards?.dispose();
		this.atlas?.dispose();
		for (const m of [...Object.values(this.mats), ...Object.values(this.ghost), this.active])
			m.dispose();
		// This view's copy of the model goes; the parsed model stays for the
		// next visit, and the GPU's copy goes with the context.
		this.renderer.dispose();
		this.renderer.forceContextLoss();
	}
}

const blankCard: CardData = { name: '', code: '', number: '', colors: [], images: [] };

function ghostMaterial() {
	return new MeshBasicMaterial({ transparent: true, opacity: 0.24, depthWrite: false });
}
