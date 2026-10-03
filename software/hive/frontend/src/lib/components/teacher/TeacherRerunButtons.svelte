<script lang="ts">
	import { onMount } from 'svelte';
	import { api, type SampleDetail, type TeacherModelInfo } from '$lib/api';
	import Alert from '$lib/components/Alert.svelte';
	import Button from '$lib/components/Button.svelte';
	import Panel from '$lib/components/Panel.svelte';
	import Columns2 from '@lucide/svelte/icons/columns-2';

	interface Props {
		sampleId: string;
		// Called with the freshly-rerun sample so the parent can swap its local state.
		// Returning false will not block the click but signals the panel to keep its
		// error state visible (currently unused — kept for future hooks).
		onResult: (sample: SampleDetail) => void;
		// The admin's default model, whose Run is the primary one.
		preferredModelId?: string | null;
	}

	let { sampleId, onResult, preferredModelId = null }: Props = $props();

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

<Panel title="Re-run the teacher" flush>
	{#snippet actions()}
		<Button size="sm" variant="ghost" href={`/samples/${sampleId}/compare`} icon={Columns2} title="Every model side by side"
			>Compare</Button
		>
	{/snippet}
	{#if modelsError}<div class="px-(--pad-panel) pb-3"><Alert tone="warning">{modelsError}</Alert></div>{/if}
	<ul class="divide-y divide-line border-t border-line">
		{#each models as m (m.model_id)}
			<li class="flex items-center gap-3 px-(--pad-panel) py-2" title={m.notes || m.model_id}>
				<span class="min-w-0 flex-1 truncate text-sm text-ink">{m.display_name}</span>
				{#if formatPrice(m.model_id)}
					<span class="num text-sm text-ink-muted" title="About the cost of a call: 2,000 tokens in and 150 out"
						>{formatPrice(m.model_id)}</span
					>
				{/if}
				<Button
					size="sm"
					variant={preferredModelId === m.model_id ? 'primary' : 'secondary'}
					loading={runningIds.has(m.model_id)}
					onclick={() => run(m.model_id)}>Run</Button
				>
			</li>
		{/each}
	</ul>
	{#if lastSuccess || lastError}
		<div class="border-t border-line px-(--pad-panel) py-3">
			{#if lastSuccess}
				<Alert tone="success">
					{lastSuccess.count} box{lastSuccess.count === 1 ? '' : 'es'} from {models.find((m) => m.model_id === lastSuccess?.modelId)
						?.display_name ?? lastSuccess.modelId}
				</Alert>
			{/if}
			{#if lastError}
				<Alert tone="warning">
					{models.find((m) => m.model_id === lastError?.modelId)?.display_name ?? lastError.modelId}: {lastError.message}
				</Alert>
			{/if}
		</div>
	{/if}
</Panel>
