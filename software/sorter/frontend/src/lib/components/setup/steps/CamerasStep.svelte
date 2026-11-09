<!--
	A camera for each part of the machine that needs one, with its picture
	settings and its zone. The cameras found, the choices and the save are
	this step's own; what is saved comes back in the setup summary.
-->
<script lang="ts">
	import { untrack } from 'svelte';
	import CheckCircle2 from '@lucide/svelte/icons/circle-check';
	import RefreshCcw from '@lucide/svelte/icons/refresh-ccw';
	import Alert from '$lib/components/ui/Alert.svelte';
	import Button from '$lib/components/ui/Button.svelte';
	import Modal from '$lib/components/ui/Modal.svelte';
	import SetupCameraAreaCard from '$lib/components/setup/SetupCameraAreaCard.svelte';
	import SetupPictureSettingsModal from '$lib/components/setup/SetupPictureSettingsModal.svelte';
	import SetupZoneEditorModal from '$lib/components/setup/SetupZoneEditorModal.svelte';
	import { assignCameras, listUsbCameras, type UsbCamera } from '$lib/api/cameras';
	import { errorMessage } from '$lib/api/http';
	import { buildCameraChoices, parseCameraSource, sourceKey } from '$lib/setup/camera-choices';
	import type { SetupFlow } from '$lib/setup/flow.svelte';

	let { flow }: { flow: SetupFlow; onnext: () => void } = $props();

	type Role = 'c_channel_2' | 'c_channel_3' | 'classification_channel';
	const ROLES: Role[] = ['c_channel_2', 'c_channel_3', 'classification_channel'];
	const LABELS: Record<Role, string> = {
		c_channel_2: 'C-Channel 2',
		c_channel_3: 'C-Channel 3',
		classification_channel: 'Classification channel (C4)'
	};
	const DESCRIPTIONS: Record<Role, string> = {
		c_channel_2: 'The feeder path of the second C-channel.',
		c_channel_3: 'The feeder path of the third C-channel.',
		classification_channel: 'The classification channel, in a view of its own.'
	};

	const assigned = $derived(flow.summary!.config.camera_assignments);

	function savedSelections(): Record<string, string> {
		const next: Record<string, string> = {};
		for (const role of ROLES) next[role] = sourceKey(assigned[role] ?? null);
		return next;
	}

	let cameras = $state<UsbCamera[]>([]);
	let loadingCameras = $state(false);
	let selections = $state<Record<string, string>>(untrack(savedSelections));
	let saving = $state(false);
	let error = $state<string | null>(null);
	let status = $state<string | null>(null);
	let pictureRole = $state<Role | null>(null);
	let zoneRole = $state<Role | null>(null);

	const choices = $derived(buildCameraChoices(cameras, selections));
	const unsaved = $derived(ROLES.some((role) => sourceKey(assigned[role] ?? null) !== (selections[role] ?? '__none__')));

	function choiceLabel(key: string | undefined): string {
		return choices.find((entry) => entry.key === (key ?? '__none__'))?.label ?? 'No camera';
	}

	function hasCamera(role: Role): boolean {
		return parseCameraSource(selections[role] ?? '__none__') !== null;
	}

	async function loadCameras() {
		loadingCameras = true;
		error = null;
		try {
			cameras = await listUsbCameras(flow.base);
		} catch (e) {
			error = errorMessage(e, 'The cameras could not be listed.');
		} finally {
			loadingCameras = false;
		}
	}

	async function save() {
		saving = true;
		error = null;
		status = null;
		try {
			const changed = ROLES.filter((role) => sourceKey(assigned[role] ?? null) !== (selections[role] ?? '__none__'));
			const payload: Record<string, number | string | null> = {};
			for (const role of ROLES) payload[role] = parseCameraSource(selections[role] ?? '__none__');
			await assignCameras(flow.base, payload);
			// A camera that changed has a new picture and zone to look at.
			const zones = { ...flow.marks.zones };
			const pictures = { ...flow.marks.pictures };
			for (const role of changed) {
				delete zones[role];
				delete pictures[role];
			}
			flow.mark({ zones, pictures, finished: false });
			status = 'The cameras are saved.';
			await flow.reload();
			selections = savedSelections();
		} catch (e) {
			error = errorMessage(e, 'The cameras were not saved.');
		} finally {
			saving = false;
		}
	}

	$effect(() => {
		void loadCameras();
	});
</script>

<div class="flex flex-col gap-(--gap-panels)">
	<div class="flex justify-end">
		<Button icon={RefreshCcw} loading={loadingCameras} onclick={() => void loadCameras()}>Look for cameras again</Button>
	</div>
	<div class="grid grid-cols-1 gap-(--gap-panels) md:grid-cols-2 xl:grid-cols-3">
		{#each ROLES as role (role)}
			<SetupCameraAreaCard
				{role}
				label={LABELS[role]}
				description={DESCRIPTIONS[role]}
				required={true}
				selectedKey={selections[role] ?? '__none__'}
				selectedLabel={choiceLabel(selections[role])}
				zoneReviewed={Boolean(flow.marks.zones?.[role])}
				pictureTuned={Boolean(flow.marks.pictures?.[role])}
				choices={choices.filter((choice) => choice.key !== '__none__')}
				onSelect={(r, key) => (selections = { ...selections, [r]: key })}
				onOpenPictureSettings={(r) => hasCamera(r as Role) && (pictureRole = r as Role)}
				onOpenZoneEditor={(r) => hasCamera(r as Role) && (zoneRole = r as Role)}
			/>
		{/each}
	</div>
	{#if error}
		<Alert tone="danger">{error}</Alert>
	{/if}
	<div class="flex flex-wrap items-center gap-3">
		<Button variant="primary" icon={CheckCircle2} loading={saving} disabled={!unsaved} onclick={() => void save()}>
			Save the cameras
		</Button>
		{#if unsaved}
			<span class="text-sm text-ink-muted">Not saved yet.</span>
		{:else if status}
			<span class="text-sm text-success-ink">{status}</span>
		{/if}
	</div>
</div>

<Modal open={pictureRole !== null} title="Picture settings" size="lg" onclose={() => (pictureRole = null)}>
	{#if pictureRole}
		{@const role = pictureRole}
		<SetupPictureSettingsModal
			{role}
			label={LABELS[role]}
			hasCamera={hasCamera(role)}
			source={parseCameraSource(selections[role] ?? '__none__')}
			onsaved={() => {
				flow.mark({ pictures: { ...flow.marks.pictures, [role]: true } });
				status = `${LABELS[role]}: picture settings saved.`;
				pictureRole = null;
			}}
		/>
	{/if}
</Modal>

<Modal open={zoneRole !== null} title="Edit the zone" size="lg" onclose={() => (zoneRole = null)}>
	{#if zoneRole}
		{@const role = zoneRole}
		<SetupZoneEditorModal
			{role}
			onsaved={() => {
				flow.mark({ zones: { ...flow.marks.zones, [role]: true } });
				status = `${LABELS[role]}: zone saved.`;
				zoneRole = null;
			}}
		/>
	{/if}
</Modal>
