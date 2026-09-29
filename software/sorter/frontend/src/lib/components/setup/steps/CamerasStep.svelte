<script lang="ts">
	import CheckCircle2 from '@lucide/svelte/icons/circle-check';
	import SetupCameraAreaCard from '$lib/components/setup/SetupCameraAreaCard.svelte';

	type CameraChoice = {
		key: string;
		source: number | string | null;
		label: string;
	};

	let {
		cameraRoles,
		roleLabels,
		roleDescriptions,
		roleSelections,
		reviewedZones,
		tunedPictures,
		cameraChoices,
		selectedCameraLabel,
		savingAssignments,
		cameraError,
		cameraStatus,
		onSelect,
		onOpenPictureSettings,
		onOpenZoneEditor,
		onSave
	}: {
		cameraRoles: string[];
		roleLabels: Record<string, string>;
		roleDescriptions: Record<string, string>;
		roleSelections: Record<string, string>;
		reviewedZones: Record<string, boolean>;
		tunedPictures: Record<string, boolean>;
		cameraChoices: CameraChoice[];
		selectedCameraLabel: (key: string | undefined) => string;
		savingAssignments: boolean;
		cameraError: string | null;
		cameraStatus: string;
		onSelect: (role: string, key: string) => void;
		onOpenPictureSettings: (role: string) => void;
		onOpenZoneEditor: (role: string) => void;
		onSave: () => void;
	} = $props();

	const choicesWithoutNone = $derived(cameraChoices.filter((choice) => choice.key !== '__none__'));
</script>

<div class="flex flex-col gap-4">
	<div class="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
		{#each cameraRoles as role}
			<SetupCameraAreaCard
				role={role as any}
				label={roleLabels[role]}
				description={roleDescriptions[role]}
				required={true}
				selectedKey={roleSelections[role] ?? '__none__'}
				selectedLabel={selectedCameraLabel(roleSelections[role])}
				zoneReviewed={Boolean(reviewedZones[role])}
				pictureTuned={Boolean(tunedPictures[role])}
				choices={choicesWithoutNone as any}
				{onSelect}
				{onOpenPictureSettings}
				{onOpenZoneEditor}
			/>
		{/each}
	</div>

	<div class="flex flex-wrap items-center gap-3">
		<button
			onclick={onSave}
			disabled={savingAssignments}
			class="setup-button-primary inline-flex items-center gap-2 px-4 py-2 text-sm font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-60"
		>
			<CheckCircle2 size={14} />
			{savingAssignments ? 'Saving...' : 'Save Camera Setup'}
		</button>
	</div>

	{#if cameraError}
		<div class="text-sm text-danger-ink">{cameraError}</div>
	{:else if cameraStatus}
		<div class="text-sm text-success-ink">{cameraStatus}</div>
	{/if}
</div>
