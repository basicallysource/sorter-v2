<script lang="ts">
	import { api } from '$lib/api';
	import { sentence } from '$lib/text';
	import Alert from '$lib/components/Alert.svelte';
	import Badge from '$lib/components/Badge.svelte';
	import Button from '$lib/components/Button.svelte';
	import Checkbox from '$lib/components/Checkbox.svelte';
	import Field from '$lib/components/Field.svelte';
	import Input from '$lib/components/Input.svelte';
	import Panel from '$lib/components/Panel.svelte';
	import Select from '$lib/components/Select.svelte';

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
		{ value: 'empty_or_not_lego', label: 'Empty, or not LEGO' },
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
		return typeof provider === 'string' ? sentence(provider) : null;
	});
</script>

<Panel title="Tag the condition" flush>
	{#snippet actions()}
		{#if providerLabel}<Badge>Was {providerLabel}</Badge>{/if}
	{/snippet}
	<div class="flex flex-col gap-4 px-(--pad-panel) pb-(--pad-panel)">
		<div class="grid grid-cols-2 gap-3">
			<Field label="Composition" for="condition-composition">
				<Select id="condition-composition" bind:value={composition} options={[...COMPOSITION_OPTIONS]} />
			</Field>
			<Field label="Condition" for="condition-condition">
				<Select id="condition-condition" bind:value={condition} options={[...CONDITION_OPTIONS]} />
			</Field>
		</div>

		<fieldset>
			<legend class="label mb-2">Flags, each on its own</legend>
			<div class="grid grid-cols-2 gap-2">
				{#each FLAG_CHIPS as chip (chip.value)}
					<Checkbox checked={flags[chip.value] ?? false} onchange={() => toggleFlag(chip.value)}>{chip.label}</Checkbox>
				{/each}
			</div>
		</fieldset>

		<Field label="Evidence" for="condition-evidence" help="Optional; one short line.">
			<Input id="condition-evidence" bind:value={evidence} placeholder="A scratch on the top stud, a little discolored" />
		</Field>

		{#if justSaved}
			<Alert tone="success">Saved. It overrides any earlier automatic label.</Alert>
		{:else if saveError}
			<Alert tone="danger">{saveError}</Alert>
		{/if}
	</div>
	{#snippet footer()}
		<span class="mr-auto text-sm text-ink-muted">A person's tag always wins over Perceptron's.</span>
		<Button variant="primary" size="sm" loading={saving} disabled={!composition || !condition} onclick={() => void save()}>Save the tag</Button>
	{/snippet}
</Panel>
