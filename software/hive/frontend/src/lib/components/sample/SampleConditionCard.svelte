<script lang="ts">
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
		if (!value) return 'Unknown';
		return value
			.split('_')
			.filter(Boolean)
			.map((part) => part.charAt(0).toUpperCase() + part.slice(1))
			.join(' ');
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
		if (summary.composition === 'multi_part') return 'border-warning/40 bg-warning/15 text-[#A16207]';
		if (summary.composition === 'empty_or_not_lego' || summary.composition === 'uncertain') {
			return 'border-border bg-bg text-text-muted';
		}
		return 'border-info/30 bg-info/8 text-info';
	}

	function conditionTone(summary: ConditionSummary): string {
		if (summary.condition === 'trash_candidate' || summary.flags.trash_candidate) {
			return 'border-primary/30 bg-primary/8 text-primary';
		}
		if (summary.condition === 'damaged' || summary.flags.damaged || summary.condition === 'dirty' || summary.flags.dirty) {
			return 'border-warning/40 bg-warning/15 text-[#A16207]';
		}
		if (summary.condition === 'clean_ok' || summary.condition === 'minor_wear' || summary.flags.clean) {
			return 'border-success/30 bg-success/10 text-success';
		}
		return 'border-border bg-bg text-text-muted';
	}

	function flagTone(active: boolean, risk = false): string {
		if (!active) return 'border-border bg-bg text-text-muted opacity-60';
		if (risk) return 'border-warning/40 bg-warning/15 text-[#A16207]';
		return 'border-border bg-white text-text';
	}

	const conditionSummary = $derived(parseConditionSummary(samplePayload));
</script>

{#if conditionSummary}
	<div class="border border-border bg-white">
		<div class="flex items-center justify-between border-b border-border px-4 py-2.5">
			<h2 class="text-xs font-semibold uppercase tracking-wider text-text-muted">Condition</h2>
			{#if conditionSummary.provider}
				<span class="bg-bg px-2 py-0.5 text-[11px] font-medium text-text-muted">
					{conditionSummary.provider}
				</span>
			{/if}
		</div>

		<div class="space-y-3 p-3">
			<div class="grid grid-cols-2 gap-2">
				<div class="border px-3 py-2.5 {compositionTone(conditionSummary)}">
					<div class="text-[10px] font-semibold uppercase tracking-wide opacity-75">Composition</div>
					<div class="mt-1 text-sm font-semibold">{prettify(conditionSummary.composition)}</div>
				</div>
				<div class="border px-3 py-2.5 {conditionTone(conditionSummary)}">
					<div class="text-[10px] font-semibold uppercase tracking-wide opacity-75">Quality</div>
					<div class="mt-1 text-sm font-semibold">{prettify(conditionSummary.condition)}</div>
				</div>
			</div>

			<div class="flex flex-wrap gap-1.5">
				<span class="border px-2 py-1 text-[11px] font-medium {flagTone(conditionSummary.flags.single_part)}">Single</span>
				<span class="border px-2 py-1 text-[11px] font-medium {flagTone(conditionSummary.flags.compound_part)}">Compound</span>
				<span class="border px-2 py-1 text-[11px] font-medium {flagTone(conditionSummary.flags.multiple_parts, true)}">Multiple</span>
				<span class="border px-2 py-1 text-[11px] font-medium {flagTone(conditionSummary.flags.dirty, true)}">Dirty</span>
				<span class="border px-2 py-1 text-[11px] font-medium {flagTone(conditionSummary.flags.damaged, true)}">Damaged</span>
				<span class="border px-2 py-1 text-[11px] font-medium {flagTone(conditionSummary.flags.trash_candidate, true)}">Trash</span>
			</div>

			{#if conditionSummary.visibleEvidence}
				<div class="border border-border bg-bg px-3 py-2.5">
					<div class="text-[10px] font-semibold uppercase tracking-wide text-text-muted">Evidence</div>
					<p class="mt-1 text-xs leading-relaxed text-text">{conditionSummary.visibleEvidence}</p>
				</div>
			{/if}

			{#if conditionSummary.issues.length > 0}
				<div class="space-y-1">
					<div class="text-[10px] font-semibold uppercase tracking-wide text-text-muted">Issues</div>
					<div class="flex flex-wrap gap-1.5">
						{#each conditionSummary.issues as issue}
							<span class="border border-warning/40 bg-warning/15 px-2 py-0.5 text-[11px] font-medium text-[#A16207]">
								{issue}
							</span>
						{/each}
					</div>
				</div>
			{/if}

			<div class="grid grid-cols-2 gap-2 text-[11px] text-text-muted">
				{#if conditionSummary.partCountEstimate != null}
					<div>
						<div class="font-medium">Part count</div>
						<div class="mt-0.5 font-medium text-text">{conditionSummary.partCountEstimate}</div>
					</div>
				{/if}
				{#if conditionSummary.confidence != null}
					<div>
						<div class="font-medium">Confidence</div>
						<div class="mt-0.5 font-medium text-text">{Math.round(conditionSummary.confidence * 100)}%</div>
					</div>
				{/if}
				{#if conditionSummary.status}
					<div>
						<div class="font-medium">Status</div>
						<div class="mt-0.5 font-medium text-text capitalize">{prettify(conditionSummary.status)}</div>
					</div>
				{/if}
				{#if conditionSummary.sourceCropPath}
					<div>
						<div class="font-medium">Source crop</div>
						<div class="mt-0.5 truncate font-mono text-[10px] text-text" title={conditionSummary.sourceCropPath}>
							{compactPath(conditionSummary.sourceCropPath)}
						</div>
					</div>
				{/if}
			</div>

			{#if conditionSummary.model}
				<div class="truncate border-t border-border pt-2 text-[10px] font-mono text-text-muted" title={conditionSummary.model}>
					{conditionSummary.model}
				</div>
			{/if}
		</div>
	</div>
{/if}
