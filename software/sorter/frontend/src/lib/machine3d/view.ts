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
// are.
//
// The cards on the bins are the page's own elements, laid out in a layer
// behind the canvas and turned in CSS to sit on each bin's front, so they are
// the app's components, sharp at any distance. Where a card is the nearest
// thing, the canvas draws a transparent hole (one instanced quad per bin), so
// the card shows through and whatever is in front of it covers it. Only the
// layer's camera transform changes as the view turns: one style a frame.
import {
	Box3,
	BufferGeometry,
	Color,
	DirectionalLight,
	Euler,
	HemisphereLight,
	InstancedMesh,
	type Material,
	Matrix4,
	Mesh,
	MeshBasicMaterial,
	MeshStandardMaterial,
	MOUSE,
	CustomBlending,
	Object3D,
	PerspectiveCamera,
	PlaneGeometry,
	Quaternion,
	ShaderMaterial,
	SrcAlphaFactor,
	Raycaster,
	Scene,
	SRGBColorSpace,
	Vector2,
	Vector3,
	WebGLRenderer,
	ZeroFactor
} from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { MeshoptDecoder } from 'three/addons/libs/meshopt_decoder.module.js';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { MODEL, type Manifest } from './model';
import { CARD_SIZE, type BinPlace } from './layout';

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

export type Theme = {
	canvas: string;
	surface: string;
	ink: string;
	primary: string;
	success: string;
	dark: boolean;
};

// A card's width as a share of the narrowest front, its centre as a share of the
// bin's height from its base, and how far in front of the bin it sits (m).
const CARD_FILL = 0.9;
const CARD_LIFT = 0.36;
const CARD_OFFSET = 0.0005;
// The zooms a card is drawn at: half, its layout size, and twice.
const CARD_ZOOMS = [0.5, 1, 2];

/** The zoom step for a card that looks `onScreen` times its layout size:
 *  the step just above it, with a margin, so a view resting on a step does
 *  not flip between two. */
function cardZoomFor(onScreen: number, now: number) {
	const want = CARD_ZOOMS.find((z) => z >= onScreen) ?? CARD_ZOOMS[CARD_ZOOMS.length - 1];
	if (want > now) return onScreen > now * 1.1 ? want : now;
	if (want < now) return onScreen < want * 0.9 ? want : now;
	return now;
}

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
	// The cards: the page's layer and its camera element, each bin's element
	// and where it goes, the holes, and what the layer was last given.
	private cardLayer: { root: HTMLElement; camera: HTMLElement } | null = null;
	private cardEls = new Map<string, HTMLElement>();
	private cardAt = new Map<string, { pose: Matrix4; at: Vector3; out: Vector3 }>();
	private cardFacing = new Map<string, boolean>();
	// Every card's width on its bin (m), and the zoom the cards are drawn at.
	private cardWidth = 0;
	private cardZoom = 1;
	private holes: InstancedMesh | null = null;
	private cardStyleShown = { perspective: '', camera: '' };
	private size = { w: 0, h: 0 };
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

	private colors = {
		bin: new Color(),
		off: new Color(),
		primary: new Color(),
		success: new Color()
	};
	private mats = {
		body: new MeshStandardMaterial({ roughness: 0.85 }),
		dark: new MeshStandardMaterial({ roughness: 0.7 }),
		// White, so each bin's instance colour is its colour.
		bin: new MeshStandardMaterial({ roughness: 0.9 })
	};
	private ghost = { body: ghostMaterial(), dark: ghostMaterial(), bin: ghostMaterial() };
	private active = new MeshStandardMaterial({ roughness: 0.6 });
	private depthOnly = new MeshBasicMaterial({ colorWrite: false });
	private holeMaterial = holeMaterial();
	private hemisphere = new HemisphereLight(0xffffff, 0x444444, 1.1);
	private key = new DirectionalLight(0xffffff, 2.2);

	constructor(canvas: HTMLCanvasElement, loaded: Loaded) {
		this.manifest = loaded.manifest;
		this.kinds = loaded.kinds;
		this.modules = loaded.modules;
		this.renderer = new WebGLRenderer({
			canvas,
			antialias: true,
			// For the holes the cards show through.
			alpha: true,
			powerPreference: 'high-performance'
		});
		this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
		this.renderer.outputColorSpace = SRGBColorSpace;

		// The key light rides with the camera, up and to the left, so the side
		// being looked at is always lit the same way.
		this.key.position.set(-1, 1.2, 1);
		this.camera.add(this.key);
		this.scene.add(this.camera, this.hemisphere);

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
		// Zoom toward what is under the pointer, as CAD viewers do, so scrolling
		// over a bin comes to that bin.
		this.controls.zoomToCursor = true;
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
	}

	private materialFor(o: Mesh): Material {
		const surface = o.userData.surface as Surface;
		if (o.userData.lit) return this.active;
		if (this.seeInside && !o.userData.solid) return this.ghost[surface];
		return this.mats[surface];
	}

	/** Every surface's material again, after seeing inside changed. */
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
		if (this.holes) this.holes.visible = !this.seeInside;
		if (this.cardLayer) this.cardLayer.root.style.visibility = this.seeInside ? 'hidden' : '';
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

	private forget(obj: Object3D) {
		const inside = (t: Object3D) => {
			for (let p: Object3D | null = t; p; p = p.parent) if (p === obj) return true;
			return false;
		};
		this.twins = this.twins.filter((t) => !inside(t));
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
		const canvas = new Color(theme.canvas);
		const ink = new Color(theme.ink);
		const mix = (t: number) => canvas.clone().lerp(ink, t);
		// The view is a panel's content, so it sits on the surface.
		this.scene.background = new Color(theme.surface);
		// The bins are what the page is about, so they carry the most contrast;
		// the frame steps back.
		const body = mix(theme.dark ? 0.3 : 0.2);
		const dark = mix(theme.dark ? 0.14 : 0.66);
		this.mats.body.color.copy(body);
		this.mats.dark.color.copy(dark);
		this.ghost.body.color.copy(body);
		this.ghost.dark.color.copy(dark);
		this.colors.bin.copy(mix(theme.dark ? 0.55 : 0.46));
		this.colors.off.copy(mix(theme.dark ? 0.2 : 0.16));
		this.colors.primary.set(theme.primary);
		this.colors.success.set(theme.success);
		this.active.color.copy(this.colors.success);
		this.hemisphere.groundColor.copy(canvas.clone().lerp(new Color(0), 0.5));
		this.repaint();
	}

	/** The bins, placed from the machine's layout. */
	setBins(places: BinPlace[]) {
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
			// The bins take their colour per instance, not from their material.
			mesh.material = this.seeInside ? this.ghost.bin : this.mats.bin;
			this.batches.push({ mesh, lit, places: list });
		}
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
	/** The page's layer for the cards: `root` the size of the canvas, behind
	 *  it, and `camera` inside it, holding each bin's card element. */
	setCardLayer(root: HTMLElement, camera: HTMLElement) {
		this.cardLayer = { root, camera };
		this.cardStyleShown = { perspective: '', camera: '' };
		camera.style.setProperty('--card-zoom', String(this.cardZoom));
		root.style.visibility = this.seeInside ? 'hidden' : '';
		this.resize();
		this.invalidate();
	}

	/** Puts a bin's card element on that bin's front; call the result to take
	 *  it off. The element is a direct child of the camera; the view sizes it,
	 *  and the card inside it takes `zoom: var(--card-zoom)`. */
	card(el: HTMLElement, key: string): () => void {
		this.cardEls.set(key, el);
		// Drawn once and kept as the view moves: without this, Chrome draws
		// each card again at every change of its size on screen (every frame
		// of a turn), and the cards and their pictures flash while it does.
		el.style.willChange = 'transform';
		this.fitCard(el, key);
		this.cardFacing.delete(key);
		this.invalidate();
		return () => {
			if (this.cardEls.get(key) === el) this.cardEls.delete(key);
		};
	}

	/** A card element's size and place, at the zoom it is drawn at. */
	private fitCard(el: HTMLElement, key: string) {
		const zoom = this.cardZoom;
		el.style.width = `${CARD_SIZE.width * zoom}px`;
		el.style.height = `${CARD_SIZE.height * zoom}px`;
		const card = this.cardAt.get(key);
		if (!card) {
			el.style.transform = 'scale(0)';
			return;
		}
		// Metres per CSS pixel of the card as drawn.
		const s = this.cardWidth / (CARD_SIZE.width * zoom);
		el.style.transform = objectCss(new Matrix4().copy(card.pose).scale(new Vector3(s, s, s)));
	}

	/** Where each bin's card goes: one size for every bin, the narrowest
	 *  front's, centred on each bin's front. */
	private placeCards() {
		this.holes?.removeFromParent();
		this.holes?.geometry.dispose();
		this.holes?.dispose();
		this.holes = null;
		this.cardAt.clear();
		const places = this.places.filter((p) => this.manifest.binKinds[p.kind]);
		if (places.length) {
			let front = Infinity;
			let height = Infinity;
			for (const p of places) {
				const k = this.manifest.binKinds[p.kind];
				front = Math.min(front, (k.max[2] - k.min[2]) * p.widthScale);
				height = Math.min(height, k.max[1] - k.min[1]);
			}
			const perPixel = Math.min(
				(front * CARD_FILL) / CARD_SIZE.width,
				(height * 0.6) / CARD_SIZE.height
			);
			this.cardWidth = CARD_SIZE.width * perPixel;
			const size = new Vector3(this.cardWidth, CARD_SIZE.height * perPixel, 1);
			const holes = new InstancedMesh(new PlaneGeometry(1, 1), this.holeMaterial, places.length);
			// A plane faces +z; a bin's front faces +x in its face's frame.
			const outward = new Quaternion().setFromEuler(new Euler(0, Math.PI / 2, 0));
			const one = new Vector3(1, 1, 1);
			const m = new Matrix4();
			this.root.updateMatrixWorld(true);
			places.forEach((p, i) => {
				const k = this.manifest.binKinds[p.kind];
				const face = new Matrix4().makeRotationY((p.faceAzimuth * Math.PI) / 180);
				const at = new Vector3(
					k.max[0] + CARD_OFFSET,
					k.min[1] + (k.max[1] - k.min[1]) * CARD_LIFT,
					((k.min[2] + k.max[2]) / 2) * p.widthScale + p.along
				)
					.applyMatrix4(face)
					.add(new Vector3(0, this.levelBase(p.level), 0));
				const turn = new Quaternion().setFromRotationMatrix(face).multiply(outward);
				holes.setMatrixAt(i, m.compose(at, turn, size));
				this.cardAt.set(p.key, {
					pose: new Matrix4().compose(at, turn, one).premultiply(this.root.matrixWorld),
					at: at.clone().applyMatrix4(this.root.matrixWorld),
					out: new Vector3(0, 0, 1).applyQuaternion(turn).transformDirection(this.root.matrixWorld)
				});
			});
			holes.matrixAutoUpdate = false;
			holes.visible = !this.seeInside;
			holes.raycast = () => {};
			holes.computeBoundingSphere();
			this.holes = holes;
			this.root.add(holes);
		}
		for (const [key, el] of this.cardEls) this.fitCard(el, key);
		this.cardFacing.clear();
	}

	/** The card layer's camera, after a frame: only what changed is written. */
	private syncCards() {
		const layer = this.cardLayer;
		if (!layer || this.seeInside || !this.size.h) return;
		const halfW = this.size.w / 2;
		const halfH = this.size.h / 2;
		const fov = this.camera.projectionMatrix.elements[5] * halfH;
		const perspective = `${fov}px`;
		if (perspective !== this.cardStyleShown.perspective) {
			layer.root.style.perspective = perspective;
			this.cardStyleShown.perspective = perspective;
		}
		const camera = `translateZ(${fov}px)${cameraCss(this.camera.matrixWorldInverse)}translate(${halfW}px,${halfH}px)`;
		if (camera !== this.cardStyleShown.camera) {
			layer.camera.style.transform = camera;
			this.cardStyleShown.camera = camera;
		}
		// The browser keeps its picture of each card however large the card
		// looks, so the cards are drawn at the zoom step just above their size
		// on screen: never shrunk more than twice (which would break up the
		// text), and drawn again only when the view crosses a step.
		const distance = this.camera.position.distanceTo(this.controls.target);
		const onScreen = (this.cardWidth * fov) / Math.max(distance, 1e-6) / CARD_SIZE.width;
		const zoom = cardZoomFor(onScreen, this.cardZoom);
		if (zoom !== this.cardZoom) {
			this.cardZoom = zoom;
			layer.camera.style.setProperty('--card-zoom', String(zoom));
			for (const [key, el] of this.cardEls) this.fitCard(el, key);
		}
		// A card turned away is hidden here, not with backface-visibility, which
		// some browsers do not honour in a layer like this one; its hole has
		// faded it into its bin by then. Written only when it turns.
		const eye = this.camera.position;
		const to = new Vector3();
		for (const [key, el] of this.cardEls) {
			const card = this.cardAt.get(key);
			if (!card) continue;
			const facing = to.subVectors(eye, card.at).normalize().dot(card.out) > 0.15;
			if (this.cardFacing.get(key) === facing) continue;
			el.style.visibility = facing ? '' : 'hidden';
			this.cardFacing.set(key, facing);
		}
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
				if (aimed) c.lerp(this.colors.success, 0.35);
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
		this.syncCards();
		if (moving) this.invalidate();
		else this.last = 0;
	};

	private resize() {
		const canvas = this.renderer.domElement;
		const w = canvas.clientWidth;
		const h = canvas.clientHeight;
		if (!w || !h) return;
		this.renderer.setSize(w, h, false);
		this.size = { w, h };
		if (this.cardLayer) {
			this.cardLayer.camera.style.width = `${w}px`;
			this.cardLayer.camera.style.height = `${h}px`;
		}
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
			b.mesh.dispose();
			b.lit.dispose();
		}
		this.holes?.geometry.dispose();
		this.holes?.dispose();
		for (const m of [
			...Object.values(this.mats),
			...Object.values(this.ghost),
			this.active,
			this.depthOnly,
			this.holeMaterial
		])
			m.dispose();
		// This view's copy of the model goes; the parsed model stays for the
		// next visit, and the GPU's copy goes with the context.
		this.renderer.dispose();
		this.renderer.forceContextLoss();
	}
}

// A matrix as CSS, where y points down, as three.js's CSS3DRenderer writes
// them: the card layer is laid out the way that renderer lays out its own.
const num = (v: number) => (Math.abs(v) < 1e-10 ? 0 : v);

function objectCss(m: Matrix4) {
	const e = m.elements;
	const flip = [e[0], e[1], e[2], e[3], -e[4], -e[5], -e[6], -e[7], ...e.slice(8)];
	return `translate(-50%,-50%) matrix3d(${flip.map(num).join(',')})`;
}

function cameraCss(m: Matrix4) {
	const e = m.elements;
	const flip = e.map((v, i) => (i % 4 === 1 ? -v : v));
	return `matrix3d(${flip.map(num).join(',')})`;
}

/** Clears the canvas to transparent where a card is the nearest thing, drawn
 *  after everything solid so whatever is in front of it covers it. A card
 *  turned away fades into its bin (it keeps that share of what is drawn
 *  there), since a card seen edge on is only noise. */
function holeMaterial() {
	return new ShaderMaterial({
		vertexShader: `
			varying float facing;
			void main() {
				mat4 m = modelMatrix;
				#ifdef USE_INSTANCING
					m = m * instanceMatrix;
				#endif
				vec4 world = m * vec4(position, 1.0);
				facing = dot(normalize(mat3(m) * vec3(0.0, 0.0, 1.0)), normalize(cameraPosition - world.xyz));
				gl_Position = projectionMatrix * viewMatrix * world;
			}`,
		fragmentShader: `
			varying float facing;
			void main() {
				gl_FragColor = vec4(0.0, 0.0, 0.0, 1.0 - smoothstep(0.2, 0.45, facing));
			}`,
		transparent: true,
		depthWrite: false,
		blending: CustomBlending,
		blendSrc: ZeroFactor,
		blendDst: SrcAlphaFactor,
		blendSrcAlpha: ZeroFactor,
		blendDstAlpha: SrcAlphaFactor
	});
}

function ghostMaterial() {
	return new MeshBasicMaterial({ transparent: true, opacity: 0.24, depthWrite: false });
}
