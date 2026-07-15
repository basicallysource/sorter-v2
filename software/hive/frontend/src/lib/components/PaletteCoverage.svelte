<script lang="ts">
	import { api, type ColorCoverageEntry } from '$lib/api';
	import Spinner from '$lib/components/Spinner.svelte';
	import ChevronDown from 'lucide-svelte/icons/chevron-down';
	import ChevronRight from 'lucide-svelte/icons/chevron-right';

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

<div class="mb-6 border border-border bg-surface">
	<button
		type="button"
		class="flex w-full items-center gap-2 px-4 py-2.5 text-left hover:bg-bg"
		onclick={() => (open = !open)}
	>
		{#if open}<ChevronDown size={16} class="shrink-0 text-text-muted" />{:else}<ChevronRight
				size={16}
				class="shrink-0 text-text-muted"
			/>{/if}
		<span class="text-sm font-semibold text-text">Palette coverage</span>
		{#if !loading}
			<span class="text-xs text-text-muted">
				{coveredColors} of {totalColors} colors have labeled pieces
				{#if gaps.length > 0}· <span class="text-warning">{gaps.length} with none</span>{/if}
			</span>
		{/if}
	</button>

	{#if open}
		<div class="border-t border-border p-4">
			{#if loading}
				<div class="flex justify-center py-8"><Spinner /></div>
			{:else if error}
				<div class="bg-primary/8 p-3 text-sm text-primary">{error}</div>
			{:else}
				<!-- Coverage bar -->
				<div class="mb-4">
					<div class="mb-1 flex h-2 w-full overflow-hidden border border-border">
						<div
							class="bg-success"
							style={`width:${totalColors ? (coveredColors / totalColors) * 100 : 0}%`}
							title={`${coveredColors} covered`}
						></div>
						<div class="flex-1 bg-border" title={`${gaps.length} uncovered`}></div>
					</div>
					<div class="text-xs text-text-muted">
						<span class="text-text tabular-nums">{Math.round((coveredColors / Math.max(1, totalColors)) * 100)}%</span>
						of the palette has at least one labeled piece.
					</div>
				</div>

				<!-- Full palette, clustered by hue (open by default) -->
				<button
					type="button"
					class="mb-2 flex items-center gap-1 text-xs font-semibold uppercase tracking-wider text-text-muted hover:text-text"
					onclick={() => (showAll = !showAll)}
				>
					{#if showAll}<ChevronDown size={13} />{:else}<ChevronRight size={13} />{/if}
					Full palette ({totalColors})
				</button>
				{#if showAll}
					<div class="mb-4 flex flex-wrap gap-1">
						{#each sortedByHue as c (c.id)}
							<span
								class="flex h-9 w-9 flex-col items-center justify-center border text-[10px] leading-none tabular-nums {c.pieces ===
								0
									? 'border-dashed border-border text-text-muted'
									: 'border-border text-text'}"
								style={c.pieces > 0 ? `background:#${c.rgb ?? '000'}22` : ''}
								title={`${c.name} (${c.id}) — ${c.pieces} piece${c.pieces === 1 ? '' : 's'}, ${c.labels} label${c.labels === 1 ? '' : 's'}`}
							>
								<span
									class="mb-0.5 h-3.5 w-3.5 border border-border {c.is_trans ? 'opacity-70' : ''}"
									style={`background:#${c.rgb ?? '000'}`}
								></span>
								{c.pieces}
							</span>
						{/each}
					</div>
				{/if}

				<!-- Gaps: what we're missing -->
				{#if gaps.length > 0}
					<div class="mb-1.5 flex items-baseline gap-2">
						<span class="text-xs font-semibold uppercase tracking-wider text-text-muted">Coverage gaps</span>
						<span class="text-xs text-text-muted">
							no labeled pieces yet · {solidGapCount} solid
						</span>
					</div>
					<div class="flex flex-wrap gap-1.5">
						{#each gaps as c (c.id)}
							<span
								class="flex items-center gap-1.5 border border-dashed border-border bg-bg py-0.5 pl-0.5 pr-1.5"
								title={`${c.name} (${c.id}) — no labeled pieces`}
							>
								<span
									class="h-4 w-4 shrink-0 border border-border {c.is_trans ? 'opacity-70' : ''}"
									style={`background:#${c.rgb ?? '000'}`}
								></span>
								<span class="max-w-[9rem] truncate text-xs text-text-muted">{c.name}</span>
							</span>
						{/each}
					</div>
				{:else}
					<p class="text-sm text-text-muted">Every palette color has at least one labeled piece.</p>
				{/if}
			{/if}
		</div>
	{/if}
</div>
