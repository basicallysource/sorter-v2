<script lang="ts">
	import { api, type ColorCoverageEntry } from '$lib/api';
	import Spinner from '$lib/components/Spinner.svelte';
	import Alert from '$lib/components/Alert.svelte';
	import Disclosure from '$lib/components/Disclosure.svelte';
	import Panel from '$lib/components/Panel.svelte';
	import ChevronRight from '@lucide/svelte/icons/chevron-right';

	// Palette-coverage view: how well the labeled data covers the BrickLink color
	// palette. Surfaces the gaps — "we have plenty of white, nothing from metallic
	// grey" — so labelers know which colors to hunt for.
	let { machineId = null }: { machineId?: string | null } = $props();

	// Same non-solid finishes the picker down-weights; a labeled example of a plain
	// solid colour is far more valuable, so the gaps list leads with solids.
	const EXOTIC_FINISH =
		/pearl|metallic|chrome|satin|trans|glow|speckle|glitter|glitr|milky|opal|iridescent|holo|copper|bionicle|\bgold\b|\bsilver\b/i;

	let colors = $state<ColorCoverageEntry[]>([]);
	let totalColors = $state(0);
	let coveredColors = $state(0);
	let loading = $state(true);
	let error = $state<string | null>(null);
	let open = $state(false);
	let showAll = $state(true);

	function isExotic(c: ColorCoverageEntry): boolean {
		return c.is_trans || EXOTIC_FINISH.test(c.name);
	}

	// hex → HSL, for clustering visually-similar colors in the palette grid.
	function hsl(hex: string | null): [number, number, number] {
		if (!hex) return [0, 0, 0];
		const m = hex.replace('#', '');
		if (m.length < 6) return [0, 0, 0];
		const r = parseInt(m.slice(0, 2), 16) / 255;
		const g = parseInt(m.slice(2, 4), 16) / 255;
		const b = parseInt(m.slice(4, 6), 16) / 255;
		if ([r, g, b].some(Number.isNaN)) return [0, 0, 0];
		const max = Math.max(r, g, b);
		const min = Math.min(r, g, b);
		const l = (max + min) / 2;
		const d = max - min;
		let h = 0;
		const s = d === 0 ? 0 : d / (1 - Math.abs(2 * l - 1));
		if (d !== 0) {
			if (max === r) h = ((g - b) / d) % 6;
			else if (max === g) h = (b - r) / d + 2;
			else h = (r - g) / d + 4;
			h *= 60;
			if (h < 0) h += 360;
		}
		return [h, s, l];
	}

	// Grays (low saturation) sort as one block by lightness; the rest sort by hue,
	// so a run of empty greys/metallics sits together and reads as a gap.
	const sortedByHue = $derived.by(() => {
		return [...colors].sort((a, b) => {
			const [ha, sa, la] = hsl(a.rgb);
			const [hb, sb, lb] = hsl(b.rgb);
			const ga = sa < 0.15;
			const gb = sb < 0.15;
			if (ga !== gb) return ga ? -1 : 1;
			if (ga && gb) return la - lb;
			if (Math.abs(ha - hb) > 1) return ha - hb;
			return la - lb;
		});
	});

	// Actionable gap list: uncovered colors, solids first, then by name. Exotics
	// still appear but after every solid gap.
	const gaps = $derived.by(() =>
		colors
			.filter((c) => c.pieces === 0)
			.sort((a, b) => {
				const ea = isExotic(a) ? 1 : 0;
				const eb = isExotic(b) ? 1 : 0;
				if (ea !== eb) return ea - eb;
				return a.name.localeCompare(b.name);
			})
	);
	const solidGapCount = $derived(gaps.filter((c) => !isExotic(c)).length);

	async function load() {
		loading = true;
		error = null;
		try {
			const res = await api.colorCoverage({ machineId });
			colors = res.colors;
			totalColors = res.total_colors;
			coveredColors = res.covered_colors;
		} catch {
			error = 'Failed to load coverage';
		} finally {
			loading = false;
		}
	}

	$effect(() => {
		void machineId;
		void load();
	});
</script>

<Panel flush>
	<Disclosure
		title="Palette coverage"
		help={loading ? undefined : `${coveredColors} of ${totalColors} colors have labeled pieces${gaps.length > 0 ? `; ${gaps.length} have none` : ''}`}
		bind:open
	>
		<div class="flex flex-col gap-4 px-(--pad-panel) pb-2">
			{#if loading}
				<div class="flex justify-center py-8"><Spinner size={32} /></div>
			{:else if error}
				<Alert tone="danger">{error}</Alert>
			{:else}
				<div>
					<div class="mb-1.5 flex h-2 overflow-hidden rounded-item bg-track">
						<div class="bg-success" style={`width:${totalColors ? (coveredColors / totalColors) * 100 : 0}%`} title={`${coveredColors} covered`}></div>
					</div>
					<p class="text-sm text-ink-muted">
						<span class="num text-ink">{Math.round((coveredColors / Math.max(1, totalColors)) * 100)}%</span> of the palette has at least one
						labeled piece.
					</p>
				</div>

				<div>
					<button
						type="button"
						class="label mb-2 flex items-center gap-1 hover:text-ink"
						aria-expanded={showAll}
						onclick={() => (showAll = !showAll)}
					>
						<ChevronRight size={16} class="transition-transform {showAll ? 'rotate-90' : ''}" />
						The whole palette, {totalColors}
					</button>
					{#if showAll}
						<div class="flex flex-wrap gap-1">
							{#each sortedByHue as c (c.id)}
								<span
									class="num flex size-9 flex-col items-center justify-center rounded-item text-xs leading-none {c.pieces === 0
										? 'bg-well text-ink-muted'
										: 'text-ink'}"
									style={c.pieces > 0 ? `background:#${c.rgb ?? '000'}22` : ''}
									title={`${c.name} (${c.id}): ${c.pieces} piece${c.pieces === 1 ? '' : 's'}, ${c.labels} label${c.labels === 1 ? '' : 's'}`}
								>
									<span class="mb-0.5 size-3.5 rounded-check border border-line {c.is_trans ? 'opacity-70' : ''}" style={`background:#${c.rgb ?? '000'}`}></span>
									{c.pieces}
								</span>
							{/each}
						</div>
					{/if}
				</div>

				{#if gaps.length > 0}
					<div>
						<div class="mb-2 flex flex-wrap items-baseline gap-x-2">
							<span class="label">Gaps</span>
							<span class="num text-sm text-ink-muted">no labeled pieces yet, {solidGapCount} of them solid</span>
						</div>
						<div class="flex flex-wrap gap-1.5">
							{#each gaps as c (c.id)}
								<span class="flex items-center gap-1.5 rounded-item bg-well py-0.5 pr-2 pl-0.5" title={`${c.name} (${c.id}): no labeled pieces`}>
									<span class="size-4 shrink-0 rounded-check border border-line {c.is_trans ? 'opacity-70' : ''}" style={`background:#${c.rgb ?? '000'}`}></span>
									<span class="max-w-36 truncate text-sm text-ink-muted">{c.name}</span>
								</span>
							{/each}
						</div>
					</div>
				{:else}
					<p class="text-sm text-ink-muted">Every palette color has at least one labeled piece.</p>
				{/if}
			{/if}
		</div>
	</Disclosure>
</Panel>
