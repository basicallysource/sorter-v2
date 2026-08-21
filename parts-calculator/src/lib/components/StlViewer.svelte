<script lang="ts">
	import { onMount } from 'svelte';
	import * as THREE from 'three';
	import { STLLoader } from 'three/examples/jsm/loaders/STLLoader.js';
	import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';

	let { url, color = '#0055bf' }: { url: string; color?: string } = $props();

	let host: HTMLDivElement;
	let status = $state<'loading' | 'ready' | 'error'>('loading');
	let material: THREE.MeshPhysicalMaterial | undefined;

	// Literal black absorbs all diffuse light in a physically based shader, which
	// makes recesses and curved faces disappear. Preserve the selected hue while
	// giving near-black colors a small display-only luminance floor.
	function legibleViewerColor(value: string): THREE.Color {
		const result = new THREE.Color(value);
		const hsl = { h: 0, s: 0, l: 0 };
		result.getHSL(hsl);
		if (hsl.l < 0.075) result.setHSL(hsl.h, hsl.s, 0.075);
		return result;
	}

	// re-tint live when the color prop changes. Read `color` unconditionally first:
	// on the initial run `material` is still undefined (the STL loads async), so a
	// `material?.…` expression would short-circuit before ever reading `color`,
	// leaving it untracked — the effect would then never re-run on a colour change.
	$effect(() => {
		const next = color;
		material?.color.copy(legibleViewerColor(next));
	});

	onMount(() => {
		const el = host;
		const scene = new THREE.Scene();
		scene.background = null;

		const camera = new THREE.PerspectiveCamera(45, 1, 0.1, 5000);
		const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
		renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
		renderer.toneMapping = THREE.ACESFilmicToneMapping;
		renderer.toneMappingExposure = 1.15;
		// buffer is sized via setSize(…, false); pin the element to its box via CSS
		renderer.domElement.style.display = 'block';
		renderer.domElement.style.width = '100%';
		renderer.domElement.style.height = '100%';
		el.appendChild(renderer.domElement);

		scene.add(new THREE.HemisphereLight(0xffffff, 0x708099, 1.35));
		const key = new THREE.DirectionalLight(0xffffff, 2.2);
		key.position.set(1, 1.4, 1.2);
		scene.add(key);
		const fill = new THREE.DirectionalLight(0xbfd7ff, 1.1);
		fill.position.set(-1.2, 0.35, 0.8);
		scene.add(fill);
		const rim = new THREE.DirectionalLight(0xffffff, 1.8);
		rim.position.set(-0.4, 1.1, -1.5);
		scene.add(rim);
		// The model is freely rotatable, so it cannot rely on a conventional
		// unlit "floor" side. A broad, cool fill from below keeps undersides and
		// recessed bottom features readable without flattening the key light.
		const underside = new THREE.DirectionalLight(0xcad8ee, 1.45);
		underside.position.set(0.35, -1.5, -0.45);
		scene.add(underside);

		const controls = new OrbitControls(camera, renderer.domElement);
		controls.enableDamping = true;

		function resize() {
			const w = el.clientWidth || 1;
			const h = el.clientHeight || 1;
			renderer.setSize(w, h, false);
			camera.aspect = w / h;
			camera.updateProjectionMatrix();
		}

		let mesh: THREE.Mesh | undefined;
		new STLLoader().load(
			url,
			(geo) => {
				geo.computeVertexNormals();
				geo.center();
				material = new THREE.MeshPhysicalMaterial({
					color: legibleViewerColor(color),
					metalness: 0.0,
					roughness: 0.58,
					clearcoat: 0.3,
					clearcoatRoughness: 0.45,
					flatShading: false
				});
				mesh = new THREE.Mesh(geo, material);
				// STL is Z-up; rotate to Y-up for a natural view
				mesh.rotation.x = -Math.PI / 2;
				scene.add(mesh);

				const box = new THREE.Box3().setFromObject(mesh);
				const size = box.getSize(new THREE.Vector3());
				const center = box.getCenter(new THREE.Vector3());
				mesh.position.sub(center);
				const radius = Math.max(size.x, size.y, size.z);
				camera.position.set(radius * 1.1, radius * 0.9, radius * 1.4);
				controls.target.set(0, 0, 0);
				controls.update();
				status = 'ready';
			},
			undefined,
			() => (status = 'error')
		);

		resize();
		const ro = new ResizeObserver(resize);
		ro.observe(el);

		let raf = 0;
		function loop() {
			controls.update();
			renderer.render(scene, camera);
			raf = requestAnimationFrame(loop);
		}
		loop();

		return () => {
			cancelAnimationFrame(raf);
			ro.disconnect();
			controls.dispose();
			renderer.dispose();
			mesh?.geometry.dispose();
			renderer.domElement.remove();
		};
	});
</script>

<div class="relative h-[48vh] w-full bg-[var(--color-bg)]">
	<div bind:this={host} class="h-full w-full"></div>
	{#if status !== 'ready'}
		<div class="absolute inset-0 flex items-center justify-center text-sm text-text-muted">
			{status === 'error' ? 'Could not load model.' : 'Loading 3D model…'}
		</div>
	{/if}
	<div class="pointer-events-none absolute bottom-2 left-3 text-xs text-text-muted">
		drag to rotate · scroll to zoom
	</div>
</div>
