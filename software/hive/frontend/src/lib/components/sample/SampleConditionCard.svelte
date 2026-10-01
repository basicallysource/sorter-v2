<script lang="ts">
	import { sentence } from '$lib/text';
	import Badge from '$lib/components/Badge.svelte';
	import KeyValue from '$lib/components/KeyValue.svelte';
	import Panel from '$lib/components/Panel.svelte';
	type Props = {
		samplePayload?: Record<string, unknown> | null;
	};

	type ConditionSummary = {
		provider: string | null;
		model: string | null;
		status: string | null;
		composition: string | null;
		condition: string | null;
		confidence: number | null;
		partCountEstimate: number | null;
		flags: Record<string, boolean>;
		issues: string[];
		visibleEvidence: string | null;
		sourceCropPath: string | null;
	};

	let { samplePayload = null }: Props = $props();

	function readObject(value: unknown): Record<string, unknown> | null {
		return value && typeof value === 'object' && !Array.isArray(value)
			? (value as Record<string, unknown>)
			: null;
	}

	function readString(value: unknown): string | null {
		if (typeof value !== 'string') return null;
		const trimmed = value.trim();
		return trimmed || null;
	}

	function readNumber(value: unknown): number | null {
		return typeof value === 'number' && Number.isFinite(value) ? value : null;
	}

	function readBooleanFlags(value: unknown): Record<string, boolean> {
		const record = readObject(value);
		if (!record) return {};
		return Object.fromEntries(
			Object.entries(record)
				.filter(([, flag]) => typeof flag === 'boolean')
				.map(([key, flag]) => [key, flag as boolean])
		);
	}

	function readStringList(value: unknown): string[] {
		if (!Array.isArray(value)) return [];
		return value.filter((item): item is string => typeof item === 'string' && item.trim().length > 0);
	}

	function prettify(value: string | null): string {
		return value ? sentence(value) : 'Unknown';
	}

	function compactPath(value: string | null): string | null {
		if (!value) return null;
		const parts = value.split('/').filter(Boolean);
		if (parts.length <= 4) return value;
		return `${parts[0]}/.../${parts.slice(-3).join('/')}`;
	}

	function parseConditionSummary(payload: Record<string, unknown> | null): ConditionSummary | null {
		const analyses = Array.isArray(payload?.analyses) ? payload?.analyses : [];
		const analysis = analyses
			.map(readObject)
			.find((item) => {
				if (!item) return false;
				return item.kind === 'condition' || item.analysis_id === 'cond_primary';
			});
		if (!analysis) return null;

		const outputs = readObject(analysis.outputs) ?? {};
		const provenance = readObject(payload?.provenance);
		const conditionSample = readObject(provenance?.condition_sample);

		return {
			provider: readString(analysis.provider),
			model: readString(analysis.model),
			status: readString(analysis.status),
			composition: readString(outputs.composition),
			condition: readString(outputs.condition),
			confidence: readNumber(outputs.confidence),
			partCountEstimate: readNumber(outputs.part_count_estimate),
			flags: readBooleanFlags(outputs.flags),
			issues: readStringList(outputs.issues),
			visibleEvidence: readString(outputs.visible_evidence),
			sourceCropPath: readString(conditionSample?.condition_source_crop_path)
		};
	}

	function compositionTone(summary: ConditionSummary): string {
		if (summary.composition === 'multi_part') return 'bg-warning-soft text-warning-ink';
		if (summary.composition === 'empty_or_not_lego' || summary.composition === 'uncertain') {
			return 'bg-well text-ink-muted';
		}
		return 'bg-info-soft text-info-ink';
	}

	function conditionTone(summary: ConditionSummary): string {
		if (summary.condition === 'trash_candidate' || summary.flags.trash_candidate) {
			return 'bg-danger-soft text-danger-ink';
		}
		if (summary.condition === 'damaged' || summary.flags.damaged || summary.condition === 'dirty' || summary.flags.dirty) {
			return 'bg-warning-soft text-warning-ink';
		}
		if (summary.condition === 'clean_ok' || summary.condition === 'minor_wear' || summary.flags.clean) {
			return 'bg-success-soft text-success-ink';
		}
		return 'bg-well text-ink-muted';
	}


	const conditionSummary = $derived(parseConditionSummary(samplePayload));
</script>

{#if conditionSummary}
	{@const summary = conditionSummary}
	<Panel title="Condition" flush>
		{#snippet actions()}
			{#if summary.provider}<Badge>{summary.provider}</Badge>{/if}
		{/snippet}
		<div class="flex flex-col gap-3 px-(--pad-panel) pb-(--pad-panel)">
			<div class="grid grid-cols-2 gap-2">
				<div class="rounded-control px-3 py-2.5 {compositionTone(summary)}">
					<div class="text-sm opacity-80">Composition</div>
					<div class="mt-0.5 text-sm font-semibold">{prettify(summary.composition)}</div>
				</div>
				<div class="rounded-control px-3 py-2.5 {conditionTone(summary)}">
					<div class="text-sm opacity-80">Quality</div>
					<div class="mt-0.5 text-sm font-semibold">{prettify(summary.condition)}</div>
				</div>
			</div>

			<!-- Every flag shows; the ones not raised are faded. -->
			<div class="flex flex-wrap gap-1.5">
				{#each [
					{ key: 'single_part', label: 'Single', risk: false },
					{ key: 'compound_part', label: 'Compound', risk: false },
					{ key: 'multiple_parts', label: 'Multiple', risk: true },
					{ key: 'dirty', label: 'Dirty', risk: true },
					{ key: 'damaged', label: 'Damaged', risk: true },
					{ key: 'trash_candidate', label: 'Trash', risk: true }
				] as flag (flag.key)}
					{@const raised = summary.flags[flag.key] === true}
					<span class={raised ? '' : 'opacity-50'}>
						<Badge tone={raised ? (flag.risk ? 'warning' : 'info') : 'neutral'} dot={raised}>{flag.label}</Badge>
					</span>
				{/each}
			</div>

			{#if summary.visibleEvidence}
				<div class="rounded-control bg-well px-3 py-2.5">
					<div class="label">Evidence</div>
					<p class="mt-0.5 text-sm text-ink">{summary.visibleEvidence}</p>
				</div>
			{/if}

			{#if summary.issues.length > 0}
				<div>
					<div class="label mb-1.5">Issues</div>
					<div class="flex flex-wrap gap-1.5">
						{#each summary.issues as issue, i (i)}<Badge tone="warning">{issue}</Badge>{/each}
					</div>
				</div>
			{/if}

			<KeyValue
				items={[
					...(summary.partCountEstimate != null ? [{ label: 'Part count', value: summary.partCountEstimate }] : []),
					...(summary.confidence != null ? [{ label: 'Confidence', value: `${Math.round(summary.confidence * 100)}%` }] : []),
					...(summary.status ? [{ label: 'Status', value: prettify(summary.status) }] : []),
					...(summary.sourceCropPath ? [{ label: 'Source crop', value: compactPath(summary.sourceCropPath) ?? '', mono: true }] : []),
					...(summary.model ? [{ label: 'Model', value: summary.model, mono: true }] : [])
				]}
			/>
		</div>
	</Panel>
{/if}
