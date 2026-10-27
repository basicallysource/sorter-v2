<!--
	Choosing a channel's camera: every camera the machine finds, with a picture
	of what it sees, the one in use marked, and a camera another channel uses
	moved here only after asking.
-->
<script lang="ts">
	import Camera from '@lucide/svelte/icons/camera';
	import RefreshCw from '@lucide/svelte/icons/refresh-cw';
	import { getBackendHttpBase } from '$lib/backend';
	import CameraSourcePreview from '$lib/components/CameraSourcePreview.svelte';
	import Alert from '$lib/components/ui/Alert.svelte';
	import Badge from '$lib/components/ui/Badge.svelte';
	import Button from '$lib/components/ui/Button.svelte';
	import EmptyState from '$lib/components/ui/EmptyState.svelte';
	import Modal from '$lib/components/ui/Modal.svelte';
	import Spinner from '$lib/components/ui/Spinner.svelte';
	import { CAMERA_ROLES, ROLE_LABELS, type CameraSource } from '$lib/settings/cameras';
	import type { CameraRole } from '$lib/settings/stations';

	type UsbCameraInfo = {
		kind: 'usb';
		index: number;
		width: number;
		height: number;
		name?: string;
		preview_available?: boolean;
	};

	let {
		open = $bindable(false),
		role,
		label,
		assignments = $bindable(),
		onassigned
	}: {
		open?: boolean;
		role: CameraRole;
		label: string;
		// Every role's camera, kept up to date here as cameras are chosen.
		assignments: Record<CameraRole, CameraSource>;
		onassigned?: (message: string) => void;
	} = $props();

	let loading = $state(false);
	let saving = $state(false);
	let error = $state<string | null>(null);
	let cameras = $state<UsbCameraInfo[]>([]);
	let abort: AbortController | null = null;
	let reassign = $state<{ source: CameraSource; from: CameraRole; cameraLabel: string } | null>(null);
	let reassignOpen = $state(false);

	$effect(() => {
		if (open) void refresh();
	});
	$effect(() => {
		if (!reassignOpen) reassign = null;
	});

	async function refresh() {
		abort?.abort();
		const controller = new AbortController();
		abort = controller;
		loading = true;
		error = null;
		try {
			const res = await fetch(`${getBackendHttpBase()}/api/cameras/list`, { signal: controller.signal });
			if (!res.ok) throw new Error(await res.text());
			const payload = await res.json();
			cameras = Array.isArray(payload.usb) ? payload.usb.filter((c: UsbCameraInfo) => c.index >= 0) : [];
		} catch (e: any) {
			if (e.name !== 'AbortError') error = e.message ?? 'The cameras could not be listed.';
		} finally {
			if (abort === controller) {
				loading = false;
				abort = null;
			}
		}
	}

	function cancel() {
		abort?.abort();
		loading = false;
		open = false;
	}

	async function save(target: CameraRole, source: CameraSource) {
		saving = true;
		error = null;
		try {
			const res = await fetch(`${getBackendHttpBase()}/api/cameras/assign`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ [target]: source })
			});
			if (!res.ok) throw new Error(await res.text());
			assignments = { ...assignments, [target]: source };
			onassigned?.(source === null ? 'Camera removed.' : 'Camera changed.');
			return true;
		} catch (e: any) {
			error = e.message ?? 'The camera could not be saved.';
			return false;
		} finally {
			saving = false;
		}
	}

	function usedBy(source: CameraSource): CameraRole | null {
		return CAMERA_ROLES.find((r) => r !== role && assignments[r] === source) ?? null;
	}

	async function choose(index: number) {
		const other = usedBy(index);
		if (other) {
			const cam = cameras.find((c) => c.index === index);
			reassign = { source: index, from: other, cameraLabel: cam?.name ?? `Camera ${index}` };
			reassignOpen = true;
			return;
		}
		if (await save(role, index)) open = false;
	}

	async function confirmReassign() {
		if (!reassign) return;
		const { source, from } = reassign;
		reassignOpen = false;
		if (!(await save(from, null))) return;
		if (await save(role, source)) open = false;
	}
</script>

<Modal bind:open title="Choose the camera for {label}" size="lg">
	<div class="flex flex-col gap-4">
		{#if error}
			<Alert tone="danger">{error}</Alert>
		{/if}
		{#if loading}
			<div class="flex items-center justify-center gap-2 py-8 text-ink-muted">
				<Spinner size={16} />
				Looking for cameras
			</div>
		{:else if cameras.length > 0}
			<div class="grid grid-cols-2 gap-3 sm:grid-cols-3">
				{#each cameras as cam (cam.index)}
					{@const isSelected = assignments[role] === cam.index}
					{@const other = isSelected ? null : usedBy(cam.index)}
					<button
						type="button"
						onclick={() => choose(cam.index)}
						disabled={saving}
						aria-pressed={isSelected}
						class="flex flex-col overflow-hidden rounded-control text-left transition-colors {isSelected
							? 'bg-primary-soft'
							: 'bg-well hover:bg-hover'}"
					>
						<span class="dark block bg-media">
							{#if cam.preview_available === false}
								<span class="flex aspect-video items-center justify-center text-xs text-ink-muted">No preview</span>
							{:else}
								<CameraSourcePreview
									source={cam.index}
									baseUrl={getBackendHttpBase()}
									label={cam.name ?? `Camera ${cam.index}`}
									fit="cover"
									block
								/>
							{/if}
						</span>
						<span class="flex items-start justify-between gap-2 px-2.5 py-2 text-sm">
							<span class="min-w-0">
								<span class="block truncate font-medium text-ink">{cam.name ?? `Camera ${cam.index}`}</span>
								<span class="num block text-ink-muted">
									{#if !cam.name}Index {cam.index}{/if}{#if !cam.name && cam.width > 0 && cam.height > 0}
										·
									{/if}{#if cam.width > 0 && cam.height > 0}{cam.width}×{cam.height}{/if}
								</span>
							</span>
							{#if isSelected}
								<Badge tone="success">Active</Badge>
							{:else if other}
								<Badge tone="warning">{ROLE_LABELS[other]}</Badge>
							{/if}
						</span>
					</button>
				{/each}
			</div>
		{:else}
			<EmptyState icon={Camera} title="No cameras found">Refresh to look again.</EmptyState>
		{/if}
	</div>
	{#snippet footer()}
		{#if assignments[role] !== null}
			<Button variant="danger" class="mr-auto" disabled={saving} onclick={() => save(role, null)}>
				Remove the camera
			</Button>
		{/if}
		{#if loading}
			<Button variant="ghost" onclick={cancel}>Cancel</Button>
		{:else}
			<Button variant="ghost" icon={RefreshCw} onclick={refresh}>Refresh</Button>
		{/if}
	{/snippet}
</Modal>

{#if reassign}
	<Modal bind:open={reassignOpen} title="Move the camera?" size="sm">
		<p>
			<span class="font-medium">{reassign.cameraLabel}</span> is set for
			<span class="font-medium">{ROLE_LABELS[reassign.from]}</span>. Moving it here takes it off that
			role.
		</p>
		{#snippet footer()}
			<Button variant="ghost" onclick={() => (reassignOpen = false)}>Cancel</Button>
			<Button variant="danger" loading={saving} onclick={confirmReassign}>Move the camera</Button>
		{/snippet}
	</Modal>
{/if}
