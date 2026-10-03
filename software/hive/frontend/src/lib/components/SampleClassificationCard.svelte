<script lang="ts">
	import { api, type SampleClassificationPayload } from '$lib/api';
	import type { ClassificationApi } from '$lib/components/classification-api.svelte';
	import { sentence } from '$lib/text';
	import Alert from './Alert.svelte';
	import Badge from './Badge.svelte';
	import Button from './Button.svelte';
	import Field from './Field.svelte';
	import Input from './Input.svelte';
	import KeyValue from './KeyValue.svelte';
	import Panel from './Panel.svelte';

	type Props = {
		sampleId: string;
		sourceRole?: string | null;
		captureReason?: string | null;
		extraMetadata?: Record<string, unknown> | null;
		externalApi?: ClassificationApi | null;
		onSaved?: ((payload: SampleClassificationPayload | null) => void) | undefined;
	};

	type ClassificationSummary = {
		provider: string | null;
		status: string | null;
		part_id: string | null;
		item_name: string | null;
		color_name: string | null;
		confidence: number | null;
		source_view: string | null;
		error: string | null;
	};

	let {
		sampleId,
		sourceRole = null,
		captureReason = null,
		extraMetadata = null,
		externalApi = null,
		onSaved = undefined
	}: Props = $props();

	function normalizeString(value: string | null | undefined): string | null {
		if (typeof value !== 'string') return null;
		const normalized = value.trim();
		return normalized || null;
	}

	function readObject(value: unknown): Record<string, unknown> | null {
		return value && typeof value === 'object' && !Array.isArray(value)
			? (value as Record<string, unknown>)
			: null;
	}

	function readNumber(value: unknown): number | null {
		return typeof value === 'number' && Number.isFinite(value) ? value : null;
	}

	function parseAutoClassification(raw: unknown): ClassificationSummary | null {
		const record = readObject(raw);
		if (!record) return null;
		return {
			provider: normalizeString(record.provider as string | null | undefined),
			status: normalizeString(record.status as string | null | undefined),
			part_id: normalizeString(record.part_id as string | null | undefined),
			item_name: normalizeString(record.item_name as string | null | undefined),
			color_name: normalizeString(record.color_name as string | null | undefined),
			confidence: readNumber(record.confidence),
			source_view: normalizeString(record.source_view as string | null | undefined),
			error: normalizeString(record.error as string | null | undefined)
		};
	}

	function parseManualClassification(raw: unknown): SampleClassificationPayload | null {
		const record = readObject(raw);
		if (!record) return null;
		return {
			version: 'hive-classification-v1',
			updated_at:
				typeof record.updated_at === 'string' || record.updated_at === null
					? (record.updated_at as string | null)
					: null,
			updated_by_display_name:
				typeof record.updated_by_display_name === 'string' || record.updated_by_display_name === null
					? (record.updated_by_display_name as string | null)
					: null,
			part_id: normalizeString(record.part_id as string | null | undefined),
			item_name: normalizeString(record.item_name as string | null | undefined),
			color_id: normalizeString(record.color_id as string | null | undefined),
			color_name: normalizeString(record.color_name as string | null | undefined)
		};
	}

	function formatStatus(value: string | null): string {
		return value ? sentence(value) : 'No result';
	}

	const isClassificationSample = $derived.by(() => {
		if (sourceRole === 'classification_chamber') return true;
		if (captureReason === 'live_classification') return true;
		return extraMetadata?.detection_scope === 'classification';
	});

	const autoClassification = $derived(parseAutoClassification(extraMetadata?.classification_result));
	const incomingManualClassification = $derived(
		parseManualClassification(extraMetadata?.manual_classification)
	);

	let persistedManualClassification = $state<SampleClassificationPayload | null>(null);
	let formPartId = $state('');
	let formItemName = $state('');
	let baselinePartId = $state('');
	let baselineItemName = $state('');
	let syncMarker = $state<string | null>(null);
	let saving = $state(false);
	let feedback = $state<string | null>(null);
	let feedbackTone = $state<'neutral' | 'success' | 'danger'>('neutral');

	const activeManualClassification = $derived(
		persistedManualClassification ?? incomingManualClassification
	);
	const effectivePartId = $derived(
		activeManualClassification?.part_id ?? autoClassification?.part_id ?? null
	);
	const effectiveItemName = $derived(
		activeManualClassification?.item_name ?? autoClassification?.item_name ?? null
	);
	const effectiveColorName = $derived(
		activeManualClassification?.color_name ?? autoClassification?.color_name ?? null
	);
	const isDirty = $derived(
		formPartId.trim() !== baselinePartId || formItemName.trim() !== baselineItemName
	);

	$effect(() => {
		const nextMarker = JSON.stringify({
			sampleId,
			auto: autoClassification,
			manual: incomingManualClassification
		});

		if (nextMarker === syncMarker) return;

		persistedManualClassification = incomingManualClassification;
		const nextPartId = incomingManualClassification?.part_id ?? autoClassification?.part_id ?? '';
		const nextItemName = incomingManualClassification?.item_name ?? autoClassification?.item_name ?? '';

		formPartId = nextPartId;
		formItemName = nextItemName;
		baselinePartId = nextPartId;
		baselineItemName = nextItemName;
		feedback = null;
		feedbackTone = 'neutral';
		syncMarker = nextMarker;
	});

	function resetForm() {
		formPartId = baselinePartId;
		formItemName = baselineItemName;
		feedback = null;
		feedbackTone = 'neutral';
	}

	function clearForm() {
		formPartId = '';
		formItemName = '';
		feedback = null;
		feedbackTone = 'neutral';
	}

	async function saveClassification() {
		if (!isClassificationSample) return false;
		saving = true;
		feedback = null;
		feedbackTone = 'neutral';

		try {
			const response = await api.saveSampleClassification(sampleId, {
				part_id: normalizeString(formPartId),
				item_name: normalizeString(formItemName)
			});

			persistedManualClassification = response.data;
			const nextPartId = response.data?.part_id ?? autoClassification?.part_id ?? '';
			const nextItemName = response.data?.item_name ?? autoClassification?.item_name ?? '';
			formPartId = nextPartId;
			formItemName = nextItemName;
			baselinePartId = nextPartId;
			baselineItemName = nextItemName;
			feedback = response.cleared
				? 'Manual classification cleared.'
				: 'Classification correction saved.';
			feedbackTone = 'success';
			onSaved?.(response.data);
			return true;
		} catch (e) {
			feedback = (e as { error?: string }).error || 'Failed to save classification correction.';
			feedbackTone = 'danger';
			return false;
		} finally {
			saving = false;
		}
	}

	$effect(() => {
		if (!externalApi) return;
		externalApi.isDirty = isDirty;
		externalApi.saving = saving;
		externalApi.feedback = feedback;
		externalApi.feedbackTone = feedbackTone;
		externalApi.hasManualOverride = Boolean(
			activeManualClassification?.part_id || activeManualClassification?.item_name
		);
		externalApi.partId = effectivePartId ?? '';
		externalApi.itemName = effectiveItemName ?? '';
		externalApi.save = saveClassification;
		externalApi.reset = resetForm;
		externalApi.clear = clearForm;
	});
</script>

{#if isClassificationSample}
	<Panel title="Classification" flush>
		{#snippet actions()}
			{#if activeManualClassification?.part_id || activeManualClassification?.item_name}
				<Badge tone="primary">Manual override</Badge>
			{:else if autoClassification}
				<Badge>{autoClassification.provider ?? 'Automatic'}</Badge>
			{/if}
		{/snippet}
		<div class="flex flex-col gap-3 px-(--pad-panel) pb-(--pad-panel)">
			<div class="rounded-control bg-well px-3 py-2.5">
				<div class="label">The label now</div>
				<div class="mt-0.5 text-sm font-semibold text-ink">{effectivePartId ?? 'Unknown part'}</div>
				{#if effectiveItemName}<div class="text-sm text-ink-muted">{effectiveItemName}</div>{/if}
				{#if effectiveColorName}<div class="text-sm text-ink-muted">Color: {effectiveColorName}</div>{/if}
			</div>

			{#if autoClassification}
				{@const auto = autoClassification}
				<div>
					<div class="label">Automatic result</div>
					<div class="mt-0.5 text-sm font-medium text-ink">{auto.part_id ?? 'Unknown part'}</div>
					{#if auto.item_name}<div class="text-sm text-ink-muted">{auto.item_name}</div>{/if}
					<KeyValue
						items={[
							{ label: 'Status', value: formatStatus(auto.status) },
							...(auto.confidence != null ? [{ label: 'Confidence', value: `${Math.round(auto.confidence * 100)}%` }] : []),
							...(auto.color_name ? [{ label: 'Color', value: auto.color_name }] : []),
							...(auto.source_view ? [{ label: 'View', value: sentence(auto.source_view) }] : [])
						]}
					/>
					{#if auto.error}<Alert tone="danger">{auto.error}</Alert>{/if}
				</div>
			{:else}
				<p class="text-sm text-ink-muted">No classification result has come in for this sample yet.</p>
			{/if}

			<Field label="Part ID" for={`classification-part-${sampleId}`}>
				<Input
					id={`classification-part-${sampleId}`}
					bind:value={formPartId}
					placeholder={autoClassification?.part_id ?? 'For example 3001'}
				/>
			</Field>
			<Field label="Name" for={`classification-name-${sampleId}`}>
				<Input
					id={`classification-name-${sampleId}`}
					bind:value={formItemName}
					placeholder={autoClassification?.item_name ?? 'A readable name, if you like'}
				/>
			</Field>

			{#if feedback}
				<Alert tone={feedbackTone === 'danger' ? 'danger' : feedbackTone === 'success' ? 'success' : 'info'}>{feedback}</Alert>
			{/if}
		</div>
		{#snippet footer()}
			<Button size="sm" variant="ghost" onclick={resetForm} disabled={saving || !isDirty}>Reset</Button>
			<Button size="sm" onclick={clearForm} disabled={saving || (!formPartId && !formItemName)}>Clear</Button>
			<Button size="sm" variant="primary" loading={saving} disabled={!isDirty} onclick={saveClassification}>Save</Button>
		{/snippet}
	</Panel>
{/if}
