<script lang="ts">
	import {
		api,
		type Machine,
		type MachineProfileAssignment,
		type MachineStats,
		type MachineWithToken
	} from '$lib/api';
	import { localUiUrl } from '$lib/machineNetwork';
	import Cpu from '@lucide/svelte/icons/cpu';
	import ExternalLink from '@lucide/svelte/icons/external-link';
	import FileText from '@lucide/svelte/icons/file-text';
	import Ellipsis from '@lucide/svelte/icons/ellipsis';
	import Plus from '@lucide/svelte/icons/plus';
	import AnalyticsDashboard from '$lib/components/charts/AnalyticsDashboard.svelte';
	import PageHeader from '$lib/components/PageHeader.svelte';
	import Alert from '$lib/components/Alert.svelte';
	import Badge from '$lib/components/Badge.svelte';
	import Button from '$lib/components/Button.svelte';
	import Card from '$lib/components/Card.svelte';
	import CopyField from '$lib/components/CopyField.svelte';
	import Panel from '$lib/components/Panel.svelte';
	import EmptyState from '$lib/components/EmptyState.svelte';
	import Field from '$lib/components/Field.svelte';
	import Input from '$lib/components/Input.svelte';
	import Menu from '$lib/components/Menu.svelte';
	import Modal from '$lib/components/Modal.svelte';
	import ProgressBar from '$lib/components/ProgressBar.svelte';
	import Spinner from '$lib/components/Spinner.svelte';
	import Stat from '$lib/components/Stat.svelte';

	let machines = $state<Machine[]>([]);
	let loading = $state(true);
	let error = $state<string | null>(null);

	let assignments = $state<Record<string, MachineProfileAssignment | null>>({});
	let machineStats = $state<Record<string, MachineStats>>({});

	let showAddModal = $state(false);
	let newName = $state('');
	let newDescription = $state('');
	let addSubmitting = $state(false);

	let showTokenModal = $state(false);
	let tokenDisplay = $state('');

	let showEditModal = $state(false);
	let editMachine = $state<Machine | null>(null);
	let editName = $state('');

	let showDeleteModal = $state(false);
	let deleteMachine = $state<Machine | null>(null);

	let showPurgeModal = $state(false);
	let purgeMachine = $state<Machine | null>(null);
	let purging = $state(false);
	let purgeResult = $state<string | null>(null);

	$effect(() => {
		void loadMachines();
	});

	async function loadMachines() {
		loading = true;
		error = null;
		try {
			const [machineList, stats] = await Promise.all([api.getMachines(), api.getMachineStats()]);
			machines = machineList;
			machineStats = stats;

			const nextAssignments: Record<string, MachineProfileAssignment | null> = {};
			await Promise.all(
				machineList.map(async (machine) => {
					try {
						nextAssignments[machine.id] = await api.getMachineProfileAssignment(machine.id);
					} catch {
						nextAssignments[machine.id] = null;
					}
				})
			);
			assignments = nextAssignments;
		} catch (err) {
			error = (err as { error?: string }).error || 'Failed to load machines';
		} finally {
			loading = false;
		}
	}

	async function handleAdd(event: Event) {
		event.preventDefault();
		if (addSubmitting || !newName.trim()) return;
		addSubmitting = true;
		try {
			const result: MachineWithToken = await api.createMachine(newName, newDescription || undefined);
			machines = [...machines, result];
			assignments = { ...assignments, [result.id]: null };
			showAddModal = false;
			newName = '';
			newDescription = '';
			tokenDisplay = result.raw_token;
			showTokenModal = true;
		} catch (err) {
			error = (err as { error?: string }).error || 'Failed to create machine';
		} finally {
			addSubmitting = false;
		}
	}

	async function handleRotateToken(machine: Machine) {
		try {
			const result = await api.rotateToken(machine.id);
			tokenDisplay = result.raw_token;
			showTokenModal = true;
		} catch (err) {
			error = (err as { error?: string }).error || 'Failed to rotate token';
		}
	}

	async function handleEdit(event: Event) {
		event.preventDefault();
		if (!editMachine || !editName.trim()) return;
		try {
			const updated = await api.updateMachine(editMachine.id, { name: editName });
			machines = machines.map((machine) => (machine.id === updated.id ? updated : machine));
			showEditModal = false;
			editMachine = null;
		} catch (err) {
			error = (err as { error?: string }).error || 'Failed to update machine';
		}
	}

	async function handleDelete() {
		if (!deleteMachine) return;
		const machineToDelete = deleteMachine;
		try {
			await api.deleteMachine(machineToDelete.id);
			machines = machines.filter((machine) => machine.id !== machineToDelete.id);
			const nextAssignments = { ...assignments };
			delete nextAssignments[machineToDelete.id];
			assignments = nextAssignments;
			showDeleteModal = false;
			deleteMachine = null;
		} catch (err) {
			error = (err as { error?: string }).error || 'Failed to delete machine';
		}
	}

	async function handlePurge() {
		if (!purgeMachine) return;
		purging = true;
		purgeResult = null;
		try {
			const result = await api.purgeMachineData(purgeMachine.id);
			purgeResult = `Deleted ${result.deleted_samples} samples across ${result.deleted_sessions} sessions.`;
		} catch (err) {
			error = (err as { error?: string }).error || 'Failed to purge data';
			showPurgeModal = false;
		} finally {
			purging = false;
		}
	}

	function machineMenu(machine: Machine) {
		return [
			{
				label: 'Edit',
				onselect: () => {
					editMachine = machine;
					editName = machine.name;
					showEditModal = true;
				}
			},
			{ label: 'Rotate token', onselect: () => void handleRotateToken(machine) },
			'separator' as const,
			{
				label: 'Purge data',
				danger: true,
				onselect: () => {
					purgeMachine = machine;
					purgeResult = null;
					showPurgeModal = true;
				}
			},
			{
				label: 'Delete machine',
				danger: true,
				onselect: () => {
					deleteMachine = machine;
					showDeleteModal = true;
				}
			}
		];
	}

	function formatUptime(createdAt: string): string {
		const diff = Date.now() - new Date(createdAt).getTime();
		const days = Math.floor(diff / (1000 * 60 * 60 * 24));
		if (days < 1) return 'today';
		if (days === 1) return '1 day ago';
		if (days < 30) return `${days} days ago`;
		const months = Math.floor(days / 30);
		if (months === 1) return '1 month ago';
		if (months < 12) return `${months} months ago`;
		const years = Math.floor(months / 12);
		return years === 1 ? '1 year ago' : `${years} years ago`;
	}

	function formatNumber(n: number): string {
		if (n >= 1000) return `${(n / 1000).toFixed(1).replace(/\.0$/, '')}k`;
		return n.toString();
	}
</script>

<svelte:head>
	<title>Machines - Hive</title>
</svelte:head>

<PageHeader
	title="Machines"
	description="Manage machine tokens and decide which sorting profile version each machine should pull."
>
	{#snippet actions()}
		<Button variant="primary" icon={Plus} onclick={() => (showAddModal = true)}>Add machine</Button>
	{/snippet}
</PageHeader>

{#if error}
	<Alert tone="danger">{error}</Alert>
{/if}

{#if loading}
	<div class="flex justify-center p-8"><Spinner size={32} /></div>
{:else if machines.length === 0}
	<Panel>
		<EmptyState icon={Cpu} title="No machines yet">
			Add a machine to get a token for it; the Sorter uses it to send its pieces and samples here.
			{#snippet action()}
				<Button variant="primary" icon={Plus} onclick={() => (showAddModal = true)}>Add machine</Button>
			{/snippet}
		</EmptyState>
	</Panel>
{:else}
	<div class="grid gap-(--gap-panels) sm:grid-cols-2 lg:grid-cols-3">
		{#each machines as machine (machine.id)}
			{@const assignment = assignments[machine.id]}
			{@const stats = machineStats[machine.id]}
			{@const isOnline =
				machine.last_seen_at && Date.now() - new Date(machine.last_seen_at).getTime() < 5 * 60 * 1000}
			{@const acceptRate =
				stats && stats.total_samples > 0
					? Math.round((stats.accepted_samples / stats.total_samples) * 100)
					: null}
			{@const localUi = localUiUrl(machine.network_info)}
			<Card href={`/machines/${machine.id}`} label={machine.name} padded={false} class="overflow-hidden">
				<div class="flex items-start gap-3 px-(--pad-panel) pt-4 pb-3">
					<span
						class="mt-0.5 flex size-9 shrink-0 items-center justify-center rounded-control {isOnline
							? 'bg-success-soft text-success-ink'
							: 'bg-well text-ink-muted'}"
					>
						<Cpu size={18} />
					</span>
					<div class="min-w-0 flex-1">
						<div class="flex items-center gap-2">
							<span class="truncate font-semibold text-ink">{machine.name}</span>
							<Badge tone={isOnline ? 'success' : 'neutral'} dot>{isOnline ? 'Online' : 'Offline'}</Badge>
						</div>
						{#if machine.description}
							<p class="mt-0.5 truncate text-sm text-ink-muted">{machine.description}</p>
						{/if}
						{#if machine.last_seen_at && !machine.network_info}
							<p class="mt-0.5 text-sm text-ink-muted">Update the Sorter software to get a link to it here.</p>
						{/if}
					</div>
					<div class="-mt-1 -mr-2 flex shrink-0 items-center">
						{#if localUi}
							<Button
								href={localUi}
								target="_blank"
								rel="noopener noreferrer"
								variant="ghost"
								size="sm"
								icon={ExternalLink}
								label="Open the Sorter's own page"
							/>
						{/if}
						<Menu label={`${machine.name} actions`} items={machineMenu(machine)}>
							{#snippet trigger(props)}
								<Button {...props} variant="ghost" size="sm" icon={Ellipsis} label="More actions" />
							{/snippet}
						</Menu>
					</div>
				</div>

				<div class="grid grid-cols-3 divide-x divide-line border-t border-line">
					<Stat label="Samples" value={stats ? formatNumber(stats.total_samples) : '-'} />
					<Stat
						label="Accepted"
						value={acceptRate !== null ? `${acceptRate}%` : '-'}
						tone={acceptRate !== null && acceptRate >= 80 ? 'success' : undefined}
					/>
					<Stat label="Sessions" value={stats ? formatNumber(stats.total_sessions) : '-'} />
				</div>

				{#if stats && stats.parts_needed > 0}
					<div class="border-t border-line px-(--pad-panel) py-3">
						<div class="mb-2 flex items-center justify-between text-sm">
							<span class="text-ink">Parts found</span>
							<span class="num text-ink-muted">{stats.parts_found} of {stats.parts_needed}</span>
						</div>
						<ProgressBar
							label="Parts found"
							value={stats.parts_found}
							max={stats.parts_needed}
							tone="success"
						/>
					</div>
				{/if}

				{#if assignment?.profile && assignment.desired_version}
					<div class="flex items-center gap-2 border-t border-line px-(--pad-panel) py-3 text-sm">
						<FileText size={16} class="shrink-0 text-ink-muted" />
						<a href={`/profiles/${assignment.profile.id}`} class="truncate font-medium text-ink hover:underline"
							>{assignment.profile.name}</a
						>
						<span class="num shrink-0 text-ink-muted">v{assignment.desired_version.version_number}</span>
						{#if assignment.active_version}
							<Badge tone="success">Synced</Badge>
						{:else}
							<Badge>Pending</Badge>
						{/if}
					</div>
				{/if}

				<div
					class="mt-auto flex flex-wrap items-center justify-between gap-x-3 gap-y-0.5 border-t border-line px-(--pad-panel) py-2.5 text-sm text-ink-muted"
				>
					<span>Registered {formatUptime(machine.created_at)}</span>
					{#if machine.last_seen_at}
						<span
							>{isOnline
								? 'Online now'
								: `Last seen ${new Date(machine.last_seen_at).toLocaleString()}`}</span
						>
					{:else}
						<span>Never connected</span>
					{/if}
				</div>
			</Card>
		{/each}
	</div>

	<section>
		<h2 class="mb-(--gap-panels) text-base font-semibold text-ink">Fleet analytics</h2>
		<AnalyticsDashboard scope="mine" />
	</section>
{/if}

<Modal bind:open={showAddModal} title="Add machine" size="sm">
	<form id="add-machine" onsubmit={handleAdd} class="flex flex-col gap-4">
		<Field label="Name" for="machine-name">
			<Input id="machine-name" bind:value={newName} />
		</Field>
		<Field label="Description" for="machine-description" help="Optional.">
			<Input id="machine-description" bind:value={newDescription} />
		</Field>
	</form>
	{#snippet footer()}
		<Button variant="ghost" onclick={() => (showAddModal = false)}>Cancel</Button>
		<Button
			type="submit"
			form="add-machine"
			variant="primary"
			loading={addSubmitting}
			disabled={!newName.trim()}>Create machine</Button
		>
	{/snippet}
</Modal>

<!-- Wide, so the token fits on one line. -->
<Modal bind:open={showTokenModal} title="Machine token" size="lg" onclose={() => (tokenDisplay = '')}>
	<CopyField
		name="machine token"
		value={tokenDisplay}
		mono
		note="Hive shows the token only now. The machine needs it to send its pieces and samples here."
	/>
	{#snippet footer()}
		<Button onclick={() => (showTokenModal = false)}>Done</Button>
	{/snippet}
</Modal>

<Modal bind:open={showEditModal} title="Edit machine" size="sm">
	<form id="edit-machine" onsubmit={handleEdit}>
		<Field label="Name" for="edit-machine-name">
			<Input id="edit-machine-name" bind:value={editName} />
		</Field>
	</form>
	{#snippet footer()}
		<Button variant="ghost" onclick={() => (showEditModal = false)}>Cancel</Button>
		<Button type="submit" form="edit-machine" variant="primary" disabled={!editName.trim()}>Save</Button>
	{/snippet}
</Modal>

<Modal bind:open={showDeleteModal} title="Delete machine" size="sm">
	<p class="text-sm text-ink-muted">
		Delete <strong class="font-medium text-ink">{deleteMachine?.name}</strong>? This also removes the upload
		sessions, samples and reviews that came from it.
	</p>
	{#snippet footer()}
		<Button variant="ghost" onclick={() => (showDeleteModal = false)}>Cancel</Button>
		<Button variant="danger" onclick={handleDelete}>Delete machine</Button>
	{/snippet}
</Modal>

<Modal bind:open={showPurgeModal} title="Purge machine data" size="sm">
	{#if purgeResult}
		<Alert tone="success">{purgeResult}</Alert>
	{:else}
		<p class="text-sm text-ink-muted">
			This deletes <strong class="font-medium text-ink">all upload sessions, samples, reviews and files</strong>
			for <strong class="font-medium text-ink">{purgeMachine?.name}</strong>. The machine itself stays registered.
		</p>
	{/if}
	{#snippet footer()}
		{#if purgeResult}
			<Button variant="primary" onclick={() => (showPurgeModal = false)}>Done</Button>
		{:else}
			<Button variant="ghost" onclick={() => (showPurgeModal = false)}>Cancel</Button>
			<Button variant="danger" loading={purging} onclick={handlePurge}>Purge all data</Button>
		{/if}
	{/snippet}
</Modal>
