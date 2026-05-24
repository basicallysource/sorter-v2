<script lang="ts">
	import { api } from '$lib/api';

	type Props = {
		sampleId: string;
		samplePayload?: Record<string, unknown> | null;
		onSaved?: (analysis: Record<string, unknown>) => void;
	};

	type Flag =
		| 'single_part'
		| 'compound_part'
		| 'multiple_parts'
		| 'clean'
		| 'dirty'
		| 'damaged'
		| 'scratched'
		| 'broken'
		| 'trash_candidate';

	const COMPOSITION_OPTIONS = [
		{ value: 'single_part', label: 'Single' },
		{ value: 'compound_part', label: 'Compound' },
		{ value: 'multi_part', label: 'Multiple' },
		{ value: 'empty_or_not_lego', label: 'Empty / NaL' },
		{ value: 'uncertain', label: 'Unsure' }
	] as const;

	const CONDITION_OPTIONS = [
		{ value: 'clean_ok', label: 'Clean' },
		{ value: 'minor_wear', label: 'Minor wear' },
		{ value: 'dirty', label: 'Dirty' },
		{ value: 'damaged', label: 'Damaged' },
		{ value: 'scratched', label: 'Scratched' },
		{ value: 'broken', label: 'Broken' },
		{ value: 'trash_candidate', label: 'Trash' },
		{ value: 'uncertain', label: 'Unsure' }
	] as const;

	// Free-form flag chips. Composition + condition radios above already
	// cover the primary axis; these are independent modifiers a labeller
	// might want to add (e.g. "compound piece that's also scratched").
	const FLAG_CHIPS: Array<{ value: Flag; label: string }> = [
		{ value: 'dirty', label: 'Dirty' },
		{ value: 'scratched', label: 'Scratched' },
		{ value: 'broken', label: 'Broken' },
		{ value: 'damaged', label: 'Damaged' },
		{ value: 'multiple_parts', label: 'Multiple' },
		{ value: 'compound_part', label: 'Compound' },
		{ value: 'trash_candidate', label: 'Trash' },
		{ value: 'clean', label: 'Clean' }
	];

	let { sampleId, samplePayload = null, onSaved }: Props = $props();

	function readObject(value: unknown): Record<string, unknown> | null {
		return value && typeof value === 'object' && !Array.isArray(value)
			? (value as Record<string, unknown>)
			: null;
	}

	function existingAnalysis(payload: Record<string, unknown> | null): Record<string, unknown> | null {
		const analyses = Array.isArray(payload?.analyses) ? payload?.analyses : [];
		return (
			analyses
				.map(readObject)
				.find((a) => a && (a.kind === 'condition' || a.analysis_id === 'cond_primary')) ?? null
		);
	}

	// All UI state is owned locally; whenever the sample changes we reset
	// from whatever cond_primary block (if any) is already on the payload.
	let composition = $state('');
	let condition = $state('');
	let flags = $state<Record<string, boolean>>({});
	let evidence = $state('');

	$effect(() => {
		const analysis = existingAnalysis(samplePayload);
		const outputs = readObject(analysis?.outputs);
		composition = typeof outputs?.composition === 'string' ? (outputs.composition as string) : '';
		condition = typeof outputs?.condition === 'string' ? (outputs.condition as string) : '';
		const fl = readObject(outputs?.flags) ?? {};
		const next: Record<string, boolean> = {};
		for (const [k, v] of Object.entries(fl)) {
			if (typeof v === 'boolean') next[k] = v;
		}
		flags = next;
		evidence =
			typeof outputs?.visible_evidence === 'string' ? (outputs.visible_evidence as string) : '';
		saveError = null;
		justSaved = false;
	});

	let saving = $state(false);
	let saveError = $state<string | null>(null);
	let justSaved = $state(false);

	function toggleFlag(name: Flag) {
		flags = { ...flags, [name]: !flags[name] };
	}

	async function save() {
		if (!composition || !condition) {
			saveError = 'Pick a composition and a condition first.';
			return;
		}
		saving = true;
		saveError = null;
		try {
			const result = await api.tagCondition(sampleId, {
				composition,
				condition,
				flags,
				visible_evidence: evidence.trim() ? evidence.trim() : null
			});
			justSaved = true;
			onSaved?.(result.analysis);
		} catch (e) {
			saveError = e instanceof Error ? e.message : 'Save failed.';
		} finally {
			saving = false;
		}
	}

	const providerLabel = $derived.by<string | null>(() => {
		const analysis = existingAnalysis(samplePayload);
		const provider = analysis?.provider;
		return typeof provider === 'string' ? provider.replace(/_/g, ' ') : null;
	});
</script>

<div class="border border-border bg-white">
	<div class="flex items-center justify-between border-b border-border px-4 py-2.5">
		<h2 class="text-xs font-semibold uppercase tracking-wider text-text-muted">Tag condition</h2>
		{#if providerLabel}
			<span class="bg-bg px-2 py-0.5 text-[11px] font-medium text-text-muted">
				Was: {providerLabel}
			</span>
		{/if}
	</div>

	<div class="space-y-4 p-3">
		<div>
			<div class="mb-1.5 text-[10px] font-semibold uppercase tracking-wide text-text-muted">
				Composition
			</div>
			<div class="flex flex-wrap gap-1.5">
				{#each COMPOSITION_OPTIONS as opt}
					<button
						type="button"
						class="border px-2.5 py-1 text-[11px] font-medium {composition === opt.value
							? 'border-primary bg-primary text-white'
							: 'border-border bg-white text-text hover:border-primary'}"
						onclick={() => (composition = opt.value)}
					>
						{opt.label}
					</button>
				{/each}
			</div>
		</div>

		<div>
			<div class="mb-1.5 text-[10px] font-semibold uppercase tracking-wide text-text-muted">
				Condition
			</div>
			<div class="flex flex-wrap gap-1.5">
				{#each CONDITION_OPTIONS as opt}
					<button
						type="button"
						class="border px-2.5 py-1 text-[11px] font-medium {condition === opt.value
							? 'border-primary bg-primary text-white'
							: 'border-border bg-white text-text hover:border-primary'}"
						onclick={() => (condition = opt.value)}
					>
						{opt.label}
					</button>
				{/each}
			</div>
		</div>

		<div>
			<div class="mb-1.5 text-[10px] font-semibold uppercase tracking-wide text-text-muted">
				Flags (independent modifiers)
			</div>
			<div class="flex flex-wrap gap-1.5">
				{#each FLAG_CHIPS as chip}
					<button
						type="button"
						class="border px-2.5 py-1 text-[11px] font-medium {flags[chip.value]
							? 'border-text bg-text text-white'
							: 'border-border bg-white text-text-muted hover:border-text'}"
						onclick={() => toggleFlag(chip.value)}
					>
						{chip.label}
					</button>
				{/each}
			</div>
		</div>

		<div>
			<label class="mb-1.5 block text-[10px] font-semibold uppercase tracking-wide text-text-muted" for="condition-evidence">
				Evidence (optional, one short line)
			</label>
			<input
				id="condition-evidence"
				type="text"
				bind:value={evidence}
				placeholder="Visible scratch on top stud, slight discoloration..."
				class="w-full border border-border bg-white px-2 py-1.5 text-xs text-text focus:border-primary focus:outline-none"
			/>
		</div>

		<div class="flex items-center justify-between gap-3 border-t border-border pt-3">
			<div class="text-[11px] text-text-muted">
				{#if justSaved}
					<span class="text-success">Saved — overrides any prior auto-label.</span>
				{:else if saveError}
					<span class="text-danger">{saveError}</span>
				{:else}
					Human override always wins over Perceptron auto-label.
				{/if}
			</div>
			<button
				type="button"
				class="border border-primary bg-primary px-4 py-1.5 text-xs font-semibold text-white hover:bg-primary-hover disabled:cursor-not-allowed disabled:opacity-50"
				disabled={saving || !composition || !condition}
				onclick={() => void save()}
			>
				{saving ? 'Saving…' : 'Save tag'}
			</button>
		</div>
	</div>
</div>
