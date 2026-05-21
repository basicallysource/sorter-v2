<script lang="ts">
	import { onMount } from 'svelte';
	import { api, type SampleDetail, type TeacherModelInfo } from '$lib/api';

	interface Props {
		sampleId: string;
		// Called with the freshly-rerun sample so the parent can swap its local state.
		// Returning false will not block the click but signals the panel to keep its
		// error state visible (currently unused — kept for future hooks).
		onResult: (sample: SampleDetail) => void;
		// Highlight a model as "last used" so eye-tracking picks it up first on repeat
		// reviews. Optional — default to no highlight.
		preferredModelId?: string | null;
		// Compact two-column grid (Review sidebar) vs comfortable rows (Sample-detail).
		dense?: boolean;
	}

	let { sampleId, onResult, preferredModelId = null, dense = false }: Props = $props();

	// Per-model cost-per-call estimate (USD) for the typical detection payload — roughly
	// 2k input tokens (instruction + image) and 150 output tokens (the bbox list). Rates
	// from each provider's public pricing page; refresh when a model moves out of preview.
	// Right-aligned next to each button so admins can pick a cheap-vs-pricey model at a
	// glance without leaving the page. The real billed cost comes back from the API.
	const PRICE_PER_CALL_USD: Record<string, number> = {
		// Gemini 3 Flash (preview): $0.075/M in, $0.30/M out
		'google/gemini-3-flash-preview': (2000 * 0.075 + 150 * 0.30) / 1_000_000,
		// Gemini 3.1 Pro (preview): $2/M in, $12/M out
		'google/gemini-3.1-pro-preview': (2000 * 2.0 + 150 * 12.0) / 1_000_000,
		// Gemini 3.5 Flash: $1.50/M in, $9/M out
		'google/gemini-3.5-flash': (2000 * 1.5 + 150 * 9.0) / 1_000_000,
		// Perceptron Mk1: $0.15/M in, $1.50/M out (docs.perceptron.inc/models)
		'perceptron/perceptron-mk1': (2000 * 0.15 + 150 * 1.5) / 1_000_000
	};

	function formatPrice(modelId: string): string {
		const price = PRICE_PER_CALL_USD[modelId];
		if (price === undefined) return '';
		// Show two significant figures so $0.000245 → "$0.00025" but $0.0076 → "$0.0076".
		// `toPrecision` already does that for non-integer mantissas; toString cleans up
		// trailing zeros.
		return '$' + Number(price.toPrecision(2)).toString();
	}

	let models = $state<TeacherModelInfo[]>([]);
	let modelsError = $state<string | null>(null);
	// Track which model is currently in-flight so only that button shows a spinner.
	// String[] (not single string) so future multi-fire stays trivial if we want it.
	let runningIds = $state<Set<string>>(new Set());
	let lastError = $state<{ modelId: string; message: string } | null>(null);
	let lastSuccess = $state<{ modelId: string; count: number } | null>(null);

	onMount(() => {
		void loadModels();
	});

	async function loadModels() {
		try {
			models = await api.listTeacherModels();
		} catch (e: unknown) {
			modelsError =
				e && typeof e === 'object' && 'error' in e
					? String((e as { error: unknown }).error)
					: 'Failed to load teacher models';
		}
	}

	async function run(modelId: string) {
		if (runningIds.has(modelId)) return;
		// $state Set: copy → mutate → reassign so Svelte sees the change.
		const next = new Set(runningIds);
		next.add(modelId);
		runningIds = next;
		lastError = null;
		try {
			const updated = await api.rerunSampleTeacher(sampleId, modelId);
			lastSuccess = {
				modelId,
				count: Array.isArray(updated.detection_bboxes) ? updated.detection_bboxes.length : 0
			};
			onResult(updated);
		} catch (e: unknown) {
			lastError = {
				modelId,
				message:
					e && typeof e === 'object' && 'error' in e
						? String((e as { error: unknown }).error)
						: 'Teacher rerun failed'
			};
		} finally {
			const after = new Set(runningIds);
			after.delete(modelId);
			runningIds = after;
		}
	}
</script>

<div class="border border-border bg-white">
	<div class="flex items-center justify-between border-b border-border px-3 py-2">
		<h3 class="text-xs font-semibold uppercase tracking-wider text-text-muted">Re-run teacher</h3>
		<a
			href={`/samples/${sampleId}/compare`}
			class="text-[11px] text-text-muted hover:text-primary"
			title="Compare all models side-by-side"
		>
			Compare →
		</a>
	</div>

	{#if modelsError}
		<div class="border-b border-border bg-warning-bg px-3 py-2 text-[11px] text-warning-strong">
			{modelsError}
		</div>
	{/if}

	<div class="p-2 {dense ? 'grid grid-cols-2 gap-1.5' : 'flex flex-col gap-1.5'}">
		{#each models as m (m.model_id)}
			{@const running = runningIds.has(m.model_id)}
			{@const isPreferred = preferredModelId === m.model_id}
			<button
				type="button"
				disabled={running}
				onclick={() => run(m.model_id)}
				title={m.notes || m.model_id}
				class="flex items-center gap-2 border px-2 py-1.5 text-left text-xs transition-colors disabled:cursor-not-allowed disabled:opacity-60 {isPreferred ? 'border-primary bg-primary-light text-primary' : 'border-border bg-white text-text hover:bg-bg'}"
			>
				{#if running}
					<span class="inline-block h-3 w-3 shrink-0 animate-spin border-2 border-current border-t-transparent rounded-full"></span>
				{:else}
					<svg class="h-3 w-3 shrink-0 text-text-muted" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
						<path stroke-linecap="round" stroke-linejoin="round" d="M14 5l7 7m0 0l-7 7m7-7H3" />
					</svg>
				{/if}
				<span class="min-w-0 flex-1 truncate font-medium">{m.display_name}</span>
				{#if formatPrice(m.model_id)}
					<span
						class="shrink-0 font-mono text-[10px] text-text-muted tabular-nums"
						title="≈ cost per call (2k input + 150 output tokens)"
					>
						{formatPrice(m.model_id)}
					</span>
				{/if}
			</button>
		{/each}
	</div>

	{#if lastSuccess}
		<div class="border-t border-border bg-success/10 px-3 py-1.5 text-[11px] text-success">
			{lastSuccess.count} box{lastSuccess.count === 1 ? '' : 'es'} via {models.find((m) => m.model_id === lastSuccess?.modelId)?.display_name ?? lastSuccess.modelId}
		</div>
	{/if}
	{#if lastError}
		<div class="border-t border-border bg-warning-bg px-3 py-1.5 text-[11px] text-warning-strong">
			{models.find((m) => m.model_id === lastError?.modelId)?.display_name ?? lastError.modelId}: {lastError.message}
		</div>
	{/if}
</div>
