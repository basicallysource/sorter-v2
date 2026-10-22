<script lang="ts">
	// The Build options box: colors, which housing, and the layers with their bin
	// sizes. One implementation for the 3D printed parts tab and the Machine
	// assembly tab; everything it edits lives in a shared store (layers, colors,
	// alternatives). Print bins is the one page-owned setting, so a page that
	// has it passes `printBins`, and a page that does not leaves it out and the
	// toggle is not shown.
	import { PARTS, COLOR_ROLES, machineHeight, feetInches, LAYER_PITCH_MM } from '$lib/filament';
	import { getBambuColor } from '$lib/bambu-colors';
	import { layerStore, addLayer as addLayerStore, removeLayerAt, setSize, setSizes } from '$lib/layers.svelte';
	import { colorStore, resetRoleColors } from '$lib/colors.svelte';
	import { Popover, tip } from '$lib/popover';
	import { Plus, X, RotateCcw } from 'lucide-svelte';
	import ColorPicker from '$lib/components/ColorPicker.svelte';
	import Disclosure from '$lib/components/Disclosure.svelte';
	import AlternativeSwitch from '$lib/components/AlternativeSwitch.svelte';
	import { resetAlternatives } from '$lib/alternatives.svelte';

	let {
		printBins = $bindable(undefined),
		open = $bindable(false),
		onreset
	}: {
		printBins?: boolean;
		open?: boolean;
		/** What "Reset to default" does on this page, when it resets more than the shared settings. */
		onreset?: () => void;
	} = $props();

	const funnelSizes = $derived(layerStore.sizes);
	const layers = $derived(funnelSizes.length);
	const height = $derived(machineHeight(layers));
	const roleColors = $derived(colorStore.roles);
	const partsById = new Map(PARTS.map((p) => [p.id, p]));
	const render = (id: string) => partsById.get(id)?.render ?? '';

	// per-layer size 'half' = 12 bins, 'third' = 18 bins
	const sizePreview = {
		half: { count: 12, bins: ['bin-half-left', 'bin-half-right'], funnel: 'funnel-half' },
		third: { count: 18, bins: ['bin-third-left', 'bin-third-center', 'bin-third-rightback'], funnel: 'funnel-third' }
	} as const;

	const buildSummary = $derived(
		[
			`${layers} layer${layers === 1 ? '' : 's'}`,
			`${funnelSizes.map((sz) => (sz === 'half' ? '12' : '18')).join('/')} bins`,
			`${(height.bucket / 1000).toFixed(2)} m tall`,
			...(printBins === undefined ? [] : [printBins ? 'bins included' : 'bins not printed']),
			COLOR_ROLES.map((r) => getBambuColor(roleColors[r.id])?.name ?? roleColors[r.id]).join(', ')
		].join('  ·  ')
	);

	function reset() {
		if (onreset) onreset();
		else {
			setSizes(['third', 'third', 'half']);
			resetRoleColors();
		}
		resetAlternatives();
	}
</script>

<Disclosure title="Build options" summary={buildSummary} bind:open flush>
	{#snippet actions()}
		<button
			class="inline-flex items-center gap-1.5 text-sm text-text-muted hover:text-text"
			onclick={reset}
			use:tip={'Reset all build options to defaults'}
		>
			<RotateCcw size={14} /> Reset to default
		</button>
	{/snippet}

	<!-- colors -->
	<div class="p-4">
		<div class="mb-3 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wider text-text-muted">
			Colors
			<Popover width="18rem" label="About the color options">
				Each color picker sets every part in that group. Parts whose color does a job are marked
				<b class="text-text">Must be</b> and keep their color: the lamp reflector and its hooks print
				white, and the rotors and stators the cameras look at print gray.
				<span class="mt-2 block border-t border-border pt-2">
					Names are Bambu Lab PLA Matte. The grey line under a color is the LEGO color it matches,
					in BrickLink naming, so Ash Gray is light bluish gray. Only colors with a genuinely close
					LEGO counterpart show one.
				</span>
			</Popover>
		</div>
		<div class="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-5">
			{#each COLOR_ROLES as role (role.id)}
				<ColorPicker bind:value={colorStore.roles[role.id]} label={role.name} />
			{/each}
		</div>
	</div>

	<!-- whole-assembly alternatives -->
	<div class="border-t border-border p-4">
		<AlternativeSwitch />
	</div>

	<!-- layer configuration -->
	<div class="border-t border-border p-4">
		<div class="mb-3 flex flex-wrap items-center justify-between gap-3">
			<span class="text-xs font-semibold uppercase tracking-wider text-text-muted">
				Layers <span class="font-normal normal-case text-text-muted">· {layers} layer{layers === 1 ? '' : 's'}, bins per layer</span>
			</span>
			{#if printBins !== undefined}
				<label class="flex cursor-pointer items-center gap-2 text-sm">
					<input class="setup-toggle h-4 w-4" type="checkbox" bind:checked={printBins} />
					<span class="font-medium text-text">Print bins</span>
					<span class="text-xs text-text-muted">— include bins (size/qty per layer below)</span>
				</label>
			{/if}
		</div>
		<p class="mb-3 flex items-center gap-1.5 text-sm text-text-muted">
			<span><b class="text-text">{height.bucket} mm</b> ({feetInches(height.bucket)}) tall to the top of the bulk bucket, {height.plate} mm ({feetInches(height.plate)}) to the top plate.</span>
			<Popover width="18rem" label="About the machine height">
				Floor to the top, standing on its casters. Each layer adds {LAYER_PITCH_MM} mm ({(LAYER_PITCH_MM / 25.4).toFixed(1)} in).
				<span class="mt-2 block border-t border-border pt-2">
					The bulk bucket is the highest point and it is where you pour the LEGO in, so measure your
					space against that figure, and check you can reach into it.
				</span>
			</Popover>
		</p>
		<div class="flex flex-col gap-2">
			{#each funnelSizes as size, i (i)}
				{@const pv = sizePreview[size]}
				<div class="group setup-card-shell flex flex-wrap items-center gap-3 border px-3 py-2">
					<span class="w-16 shrink-0 text-sm font-medium text-text">Layer {i + 1}</span>
					<div class="flex">
						<button class="setup-button-secondary h-9 px-3 text-sm {size === 'half' ? 'setup-button-primary' : ''}" onclick={() => setSize(i, 'half')}>12 bins</button>
						<button class="setup-button-secondary h-9 border-l-0 px-3 text-sm {size === 'third' ? 'setup-button-primary' : ''}" onclick={() => setSize(i, 'third')}>18 bins</button>
					</div>
					<div class="ml-auto flex items-center gap-1.5">
						{#each pv.bins as b (b)}
							<img src={render(b)} alt={b} class="h-9 w-9 border border-border bg-[var(--color-bg)] object-contain {printBins === false ? 'opacity-30' : ''}" use:tip={partsById.get(b)?.name} />
						{/each}
						<span class="px-1 text-text-muted">+</span>
						<img src={render(pv.funnel)} alt="funnel" class="h-9 w-9 border border-primary/40 bg-[var(--color-bg)] object-contain" use:tip={`${size} funnel`} />
					</div>
					{#if layers > 1}
						<button
							class="flex h-7 w-7 shrink-0 items-center justify-center text-text-muted opacity-0 transition-opacity hover:text-danger group-hover:opacity-100"
							onclick={() => removeLayerAt(i)}
							aria-label="Remove layer {i + 1}"
							use:tip={'Remove layer'}
						>
							<X size={16} />
						</button>
					{/if}
				</div>
			{/each}
			<button
				class="setup-button-secondary flex h-10 w-full items-center justify-center gap-1.5 text-sm font-medium"
				onclick={() => addLayerStore()}
			>
				<Plus size={16} /> Add layer
			</button>
		</div>
	</div>
</Disclosure>
