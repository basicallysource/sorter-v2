<script lang="ts">
	import { onMount } from 'svelte';

	// The 3D preview of a printed part, the same one the parts calculator shows
	// (parts-calculator/src/lib/components/StlViewer.svelte), trimmed to what a
	// docs reader needs: orbit, zoom, two looks, no id-stamp controls or version
	// flipping. Lit the way CAD lights a part (flat ambient plus one headlight
	// riding on the camera, no tone mapping), so a face is brighter the more it
	// faces you and that is all the shading there is.
	//
	// three is imported dynamically on mount, never at module scope: this
	// component is reachable from every assembly page, and a reader who never
	// opens a part must not pay for the library. Vite splits it into its own
	// chunk, fetched the first time a modal opens.
	let {
		url,
		poster,
		color = '#9B9EA0'
	}: {
		url: string;
		/** The catalog render, shown behind the canvas until the mesh is up. */
		poster?: string;
		color?: string;
	} = $props();

	let host: HTMLDivElement;
	let status = $state<'loading' | 'ready' | 'error'>('loading');
	// "cad" draws the feature edges (every crease over 25 degrees) over the
	// shading and sits the part on a grey gradient, which is what makes a white
	// part on a pale page readable at all; "shaded" is the bare lit surface.
	let mode = $state<'cad' | 'shaded'>('cad');

	let setEdgesVisible: ((visible: boolean) => void) | undefined;
	let resetView: (() => void) | undefined = $state();
	$effect(() => setEdgesVisible?.(mode === 'cad'));

	onMount(() => {
		let disposed = false;
		let teardown: (() => void) | undefined;

		(async () => {
			const THREE = await import('three');
			const { STLLoader } = await import('three/examples/jsm/loaders/STLLoader.js');
			const { OrbitControls } = await import('three/examples/jsm/controls/OrbitControls.js');
			if (disposed) return;

			const el = host;
			const scene = new THREE.Scene();
			scene.background = null;

			const camera = new THREE.PerspectiveCamera(40, 1, 0.1, 5000);
			const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
			renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
			renderer.toneMapping = THREE.NoToneMapping;
			renderer.domElement.style.display = 'block';
			renderer.domElement.style.width = '100%';
			renderer.domElement.style.height = '100%';
			el.appendChild(renderer.domElement);

			scene.add(new THREE.AmbientLight(0xffffff, 1.1));
			const headlight = new THREE.DirectionalLight(0xffffff, 1.9);
			headlight.position.set(0.25, 0.45, 1);
			camera.add(headlight);
			scene.add(camera);

			// Literal black absorbs everything under any lighting model, so recesses
			// vanish. Keep the hue, floor the luminance for display only.
			const shown = new THREE.Color(color);
			const hsl = { h: 0, s: 0, l: 0 };
			shown.getHSL(hsl);
			if (hsl.l < 0.1) shown.setHSL(hsl.h, hsl.s, 0.1);

			// polygon offset pushes the surface back a hair so the edges sit on it
			const material = new THREE.MeshStandardMaterial({
				color: shown,
				metalness: 0,
				roughness: 0.9,
				polygonOffset: true,
				polygonOffsetFactor: 1,
				polygonOffsetUnits: 1
			});

			const controls = new OrbitControls(camera, renderer.domElement);
			controls.enableDamping = true;

			let mesh: InstanceType<typeof THREE.Mesh> | undefined;
			let edges: InstanceType<typeof THREE.LineSegments> | undefined;
			let radius = 1;
			const homePose = () =>
				new THREE.Vector3(0.9, 0.65, 1.25).normalize().multiplyScalar(radius * 3.1);

			setEdgesVisible = (visible) => {
				if (edges) edges.visible = visible;
			};
			resetView = () => {
				camera.position.copy(homePose());
				controls.target.set(0, 0, 0);
				controls.update();
			};

			new STLLoader().load(
				url,
				(geo) => {
					if (disposed) return;
					geo.computeVertexNormals();
					geo.center();
					mesh = new THREE.Mesh(geo, material);
					mesh.rotation.x = -Math.PI / 2; // STL is Z-up; the scene is Y-up
					scene.add(mesh);

					// feature edges ride on the mesh so they follow its transform
					edges = new THREE.LineSegments(
						new THREE.EdgesGeometry(geo, 25),
						new THREE.LineBasicMaterial({ color: 0x1f2328, transparent: true, opacity: 0.6 })
					);
					edges.visible = mode === 'cad';
					mesh.add(edges);

					geo.computeBoundingSphere();
					radius = geo.boundingSphere?.radius || 1;
					resetView?.();
					status = 'ready';
				},
				undefined,
				() => (status = 'error')
			);

			function resize() {
				const w = el.clientWidth || 1;
				const h = el.clientHeight || 1;
				renderer.setSize(w, h, false);
				camera.aspect = w / h;
				camera.updateProjectionMatrix();
			}
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

			teardown = () => {
				cancelAnimationFrame(raf);
				ro.disconnect();
				controls.dispose();
				renderer.dispose();
				mesh?.geometry.dispose();
				edges?.geometry.dispose();
				material.dispose();
				renderer.domElement.remove();
			};
		})().catch(() => (status = 'error'));

		return () => {
			disposed = true;
			teardown?.();
		};
	});
</script>

<div class="stl-viewer" class:stl-viewer--cad={mode === 'cad'}>
	{#if poster && status !== 'ready'}
		<img class="stl-poster" src={poster} alt="" aria-hidden="true" />
	{/if}
	<div class="stl-canvas" bind:this={host}></div>
	{#if status === 'error'}
		<p class="stl-status">Could not load the 3D model.</p>
	{:else if status === 'loading'}
		<p class="stl-status">Loading 3D model…</p>
	{:else}
		<p class="stl-hint">drag to rotate · scroll to zoom</p>
		<div class="stl-controls" role="group" aria-label="View style">
			<button
				type="button"
				class:stl-mode--on={mode === 'cad'}
				onclick={() => (mode = 'cad')}
				title="Shaded with feature edges, on a grey ground">CAD</button
			>
			<button
				type="button"
				class:stl-mode--on={mode === 'shaded'}
				onclick={() => (mode = 'shaded')}
				title="Bare shaded surface">Shaded</button
			>
			<button type="button" onclick={() => resetView?.()} title="Frame the whole part again"
				>Reset</button
			>
		</div>
	{/if}
</div>
