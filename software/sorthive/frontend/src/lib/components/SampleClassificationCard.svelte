<script lang="ts">
	import { api, type SampleClassificationPayload } from '$lib/api';
	import type { ClassificationApi } from '$lib/components/classification-api.svelte';

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
			version: 'sorthive-classification-v1',
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
		if (!value) return 'No result';
		return value.replaceAll('_', ' ');
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
	<div class="border border-gray-200 bg-white">
		<div class="flex items-center justify-between border-b border-gray-100 px-4 py-2.5">
			<h2 class="text-xs font-semibold uppercase tracking-wider text-gray-400">Classification</h2>
			{#if activeManualClassification?.part_id || activeManualClassification?.item_name}
				<span class="bg-[#FEF2F2] px-2 py-0.5 text-[11px] font-medium text-[#D01012]">
					Manual override
				</span>
			{:else if autoClassification}
				<span class="bg-gray-50 px-2 py-0.5 text-[11px] font-medium text-gray-500">
					{autoClassification.provider ?? 'Auto'}
				</span>
			{/if}
		</div>

		<div class="space-y-3 p-3">
			<div class="border border-gray-200 bg-gray-50 px-3 py-3">
				<div class="text-[11px] font-semibold tracking-wide text-gray-500 uppercase">
					Current Label
				</div>
				<div class="mt-1 text-sm font-semibold text-gray-900">
					{effectivePartId ?? 'Unknown part'}
				</div>
				{#if effectiveItemName}
					<div class="mt-0.5 text-xs text-gray-600">{effectiveItemName}</div>
				{/if}
				{#if effectiveColorName}
					<div class="mt-1 text-[11px] text-gray-500">Color: {effectiveColorName}</div>
				{/if}
			</div>

			{#if autoClassification}
				<div class="border border-gray-200 px-3 py-3">
					<div class="text-[11px] font-semibold tracking-wide text-gray-500 uppercase">
						Auto Result
					</div>
					<div class="mt-1 text-sm font-medium text-gray-900">
						{autoClassification.part_id ?? 'Unknown part'}
					</div>
					{#if autoClassification.item_name}
						<div class="mt-0.5 text-xs text-gray-600">{autoClassification.item_name}</div>
					{/if}
					<div class="mt-2 grid grid-cols-2 gap-2 text-[11px] text-gray-500">
						<div>
							<div class="font-medium text-gray-400">Status</div>
							<div class="mt-0.5 text-gray-700 capitalize">{formatStatus(autoClassification.status)}</div>
						</div>
						{#if autoClassification.confidence != null}
							<div>
								<div class="font-medium text-gray-400">Confidence</div>
								<div class="mt-0.5 text-gray-700">{Math.round(autoClassification.confidence * 100)}%</div>
							</div>
						{/if}
						{#if autoClassification.color_name}
							<div>
								<div class="font-medium text-gray-400">Color</div>
								<div class="mt-0.5 text-gray-700">{autoClassification.color_name}</div>
							</div>
						{/if}
						{#if autoClassification.source_view}
							<div>
								<div class="font-medium text-gray-400">View</div>
								<div class="mt-0.5 text-gray-700 capitalize">{autoClassification.source_view}</div>
							</div>
						{/if}
					</div>
					{#if autoClassification.error}
						<p class="mt-2 bg-[#FEF2F2] px-2 py-1.5 text-[11px] text-[#D01012]">
							{autoClassification.error}
						</p>
					{/if}
				</div>
			{:else}
				<p class="text-xs text-gray-500">
					No classification result has been uploaded for this sample yet.
				</p>
			{/if}

			<div class="space-y-2">
				<div>
					<label for={`classification-part-${sampleId}`} class="mb-1 block text-[11px] font-medium text-gray-500">
						Part ID
					</label>
					<input
						id={`classification-part-${sampleId}`}
						bind:value={formPartId}
						type="text"
						placeholder={autoClassification?.part_id ?? 'e.g. 3001'}
						class="w-full border border-gray-300 px-3 py-2 text-sm text-gray-900 placeholder:text-gray-400 focus:border-[#D01012] focus:outline-none focus:ring-1 focus:ring-[#D01012]"
					/>
				</div>
				<div>
					<label for={`classification-name-${sampleId}`} class="mb-1 block text-[11px] font-medium text-gray-500">
						Name
					</label>
					<input
						id={`classification-name-${sampleId}`}
						bind:value={formItemName}
						type="text"
						placeholder={autoClassification?.item_name ?? 'Optional human-readable name'}
						class="w-full border border-gray-300 px-3 py-2 text-sm text-gray-900 placeholder:text-gray-400 focus:border-[#D01012] focus:outline-none focus:ring-1 focus:ring-[#D01012]"
					/>
				</div>
			</div>

			{#if feedback}
				<p
					class="px-3 py-2 text-[11px] {feedbackTone === 'danger'
						? 'bg-[#D01012]/8 text-[#D01012]'
						: feedbackTone === 'success'
							? 'bg-[#00852B]/10 text-[#00852B]'
							: 'bg-[#F7F6F3] text-[#7A7770]'}"
				>
					{feedback}
				</p>
			{/if}

			<div class="flex gap-2">
				<button
					type="button"
					onclick={resetForm}
					disabled={saving || !isDirty}
					class="flex-1 border border-gray-200 px-3 py-2 text-xs font-medium text-gray-600 transition-colors hover:bg-gray-50 disabled:cursor-not-allowed disabled:text-gray-300"
				>
					Reset
				</button>
				<button
					type="button"
					onclick={clearForm}
					disabled={saving || (!formPartId && !formItemName)}
					class="flex-1 border border-[#FFD500]/30 px-3 py-2 text-xs font-medium text-[#A16207] transition-colors hover:bg-[#FFFBEB] disabled:cursor-not-allowed disabled:border-[#E2E0DB] disabled:text-[#E2E0DB]"
				>
					Clear
				</button>
				<button
					type="button"
					onclick={saveClassification}
					disabled={saving || !isDirty}
					class="flex-1 px-3 py-2 text-xs font-medium text-white transition-colors disabled:cursor-not-allowed disabled:bg-[#D01012]/40 {saving || !isDirty ? 'bg-[#D01012]/40' : 'bg-[#D01012] hover:bg-[#B00E10]'}"
				>
					{saving ? 'Saving...' : 'Save'}
				</button>
			</div>
		</div>
	</div>
{/if}
