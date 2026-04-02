<script lang="ts">
	import { api, type Machine, type MachineWithToken } from '$lib/api';
	import Modal from '$lib/components/Modal.svelte';
	import Spinner from '$lib/components/Spinner.svelte';
	import Badge from '$lib/components/Badge.svelte';

	let machines = $state<Machine[]>([]);
	let loading = $state(true);
	let error = $state<string | null>(null);

	// Add machine modal
	let showAddModal = $state(false);
	let newName = $state('');
	let newDescription = $state('');
	let addSubmitting = $state(false);

	// Token display modal
	let showTokenModal = $state(false);
	let tokenDisplay = $state('');
	let tokenCopied = $state(false);

	// Edit modal
	let showEditModal = $state(false);
	let editMachine = $state<Machine | null>(null);
	let editName = $state('');

	// Delete confirmation
	let showDeleteModal = $state(false);
	let deleteMachine = $state<Machine | null>(null);

	// Purge data confirmation
	let showPurgeModal = $state(false);
	let purgeMachine = $state<Machine | null>(null);
	let purging = $state(false);
	let purgeResult = $state<string | null>(null);

	$effect(() => {
		loadMachines();
	});

	async function loadMachines() {
		loading = true;
		try {
			machines = await api.getMachines();
		} catch {
			error = 'Failed to load machines';
		} finally {
			loading = false;
		}
	}

	async function handleAdd(e: Event) {
		e.preventDefault();
		addSubmitting = true;
		try {
			const result: MachineWithToken = await api.createMachine(newName, newDescription || undefined);
			machines = [...machines, result];
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
			tokenCopied = false;
			showTokenModal = true;
		} catch (err) {
			error = (err as { error?: string }).error || 'Failed to rotate token';
		}
	}

	async function handleEdit(e: Event) {
		e.preventDefault();
		if (!editMachine) return;
		try {
			const updated = await api.updateMachine(editMachine.id, { name: editName });
			machines = machines.map((m) => (m.id === updated.id ? updated : m));
			showEditModal = false;
			editMachine = null;
		} catch (err) {
			error = (err as { error?: string }).error || 'Failed to update machine';
		}
	}

	async function handleDelete() {
		if (!deleteMachine) return;
		try {
			await api.deleteMachine(deleteMachine.id);
			machines = machines.filter((m) => m.id !== deleteMachine!.id);
			showDeleteModal = false;
			deleteMachine = null;
		} catch (err) {
			error = (err as { error?: string }).error || 'Failed to delete machine';
		}
	}

	function openEdit(machine: Machine) {
		editMachine = machine;
		editName = machine.name;
		showEditModal = true;
	}

	function openDelete(machine: Machine) {
		deleteMachine = machine;
		showDeleteModal = true;
	}

	function openPurge(machine: Machine) {
		purgeMachine = machine;
		purgeResult = null;
		showPurgeModal = true;
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

	let openMenuId = $state<string | null>(null);

	function toggleMenu(machineId: string) {
		openMenuId = openMenuId === machineId ? null : machineId;
	}

	async function copyToken() {
		await navigator.clipboard.writeText(tokenDisplay);
		tokenCopied = true;
	}
</script>

<svelte:window onclick={() => { openMenuId = null; }} />

<svelte:head>
	<title>Machines - SortHive</title>
</svelte:head>

<div class="mb-6 flex items-center justify-between">
	<h1 class="text-2xl font-bold text-gray-900">Machines</h1>
	<button
		onclick={() => { showAddModal = true; }}
		class="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700"
	>
		Add Machine
	</button>
</div>

{#if error}
	<div class="mb-4 rounded-lg bg-red-50 p-3 text-sm text-red-700">{error}</div>
{/if}

{#if loading}
	<Spinner />
{:else if machines.length === 0}
	<p class="text-gray-500">No machines yet. Add one to get started.</p>
{:else}
	<div class="space-y-4">
		{#each machines as machine (machine.id)}
			<div class="rounded-lg border border-gray-200 bg-white p-4">
				<div class="flex items-start justify-between">
					<div>
						<h3 class="font-semibold text-gray-900">{machine.name}</h3>
						{#if machine.description}
							<p class="mt-1 text-sm text-gray-500">{machine.description}</p>
						{/if}
						<div class="mt-2 flex items-center gap-3 text-xs text-gray-500">
							<span>Token: {machine.token_prefix}...</span>
							<Badge
								text={machine.is_active ? 'Active' : 'Inactive'}
								variant={machine.is_active ? 'success' : 'neutral'}
							/>
							{#if machine.last_seen_at}
								<span>Last seen: {new Date(machine.last_seen_at).toLocaleString()}</span>
							{/if}
						</div>
					</div>
					<div class="flex items-center gap-2">
						<button
							onclick={() => openEdit(machine)}
							class="rounded-lg border border-gray-300 px-3 py-1.5 text-xs font-medium text-gray-700 hover:bg-gray-50"
						>
							Edit
						</button>
						<!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
						<div class="relative" onclick={(e) => e.stopPropagation()}>
							<button
								onclick={() => toggleMenu(machine.id)}
								class="rounded-lg border border-gray-300 p-1.5 text-gray-500 hover:bg-gray-50"
								title="More actions"
							>
								<svg class="h-4 w-4" fill="currentColor" viewBox="0 0 20 20">
									<path d="M10 6a2 2 0 110-4 2 2 0 010 4zM10 12a2 2 0 110-4 2 2 0 010 4zM10 18a2 2 0 110-4 2 2 0 010 4z" />
								</svg>
							</button>
							{#if openMenuId === machine.id}
								<div class="absolute right-0 z-10 mt-1 w-44 rounded-lg border border-gray-200 bg-white py-1 shadow-lg">
									<button
										onclick={() => { handleRotateToken(machine); openMenuId = null; }}
										class="flex w-full items-center gap-2 px-4 py-2 text-sm text-gray-700 hover:bg-gray-50"
									>
										Rotate Token
									</button>
									<button
										onclick={() => { openPurge(machine); openMenuId = null; }}
										class="flex w-full items-center gap-2 px-4 py-2 text-sm text-yellow-700 hover:bg-yellow-50"
									>
										Purge Data
									</button>
									<button
										onclick={() => { openDelete(machine); openMenuId = null; }}
										class="flex w-full items-center gap-2 px-4 py-2 text-sm text-red-600 hover:bg-red-50"
									>
										Delete
									</button>
								</div>
							{/if}
						</div>
					</div>
				</div>
			</div>
		{/each}
	</div>
{/if}

<!-- Add Machine Modal -->
<Modal open={showAddModal} title="Add Machine" onclose={() => { showAddModal = false; }}>
	<form onsubmit={handleAdd} class="space-y-4">
		<div>
			<label for="machineName" class="mb-1 block text-sm font-medium text-gray-700">Name</label>
			<input
				id="machineName"
				type="text"
				bind:value={newName}
				required
				class="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:ring-1 focus:ring-blue-500 focus:outline-none"
			/>
		</div>
		<div>
			<label for="machineDesc" class="mb-1 block text-sm font-medium text-gray-700">Description (optional)</label>
			<input
				id="machineDesc"
				type="text"
				bind:value={newDescription}
				class="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:ring-1 focus:ring-blue-500 focus:outline-none"
			/>
		</div>
		<button
			type="submit"
			disabled={addSubmitting}
			class="w-full rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
		>
			{addSubmitting ? 'Creating...' : 'Create Machine'}
		</button>
	</form>
</Modal>

<!-- Token Display Modal -->
<Modal open={showTokenModal} title="API Token" onclose={() => { showTokenModal = false; }}>
	<div class="space-y-4">
		<div class="rounded-lg bg-yellow-50 p-3 text-sm text-yellow-800">
			Save this token now. It will not be shown again.
		</div>
		<div class="flex items-center gap-2">
			<code class="flex-1 overflow-x-auto rounded bg-gray-100 p-2 text-xs break-all">{tokenDisplay}</code>
			<button
				onclick={copyToken}
				class="shrink-0 rounded border border-gray-300 px-3 py-1 text-xs font-medium text-gray-700 hover:bg-gray-50"
			>
				{tokenCopied ? 'Copied!' : 'Copy'}
			</button>
		</div>
	</div>
</Modal>

<!-- Edit Machine Modal -->
<Modal open={showEditModal} title="Edit Machine" onclose={() => { showEditModal = false; }}>
	<form onsubmit={handleEdit} class="space-y-4">
		<div>
			<label for="editName" class="mb-1 block text-sm font-medium text-gray-700">Name</label>
			<input
				id="editName"
				type="text"
				bind:value={editName}
				required
				class="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:ring-1 focus:ring-blue-500 focus:outline-none"
			/>
		</div>
		<button
			type="submit"
			class="w-full rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700"
		>
			Save
		</button>
	</form>
</Modal>

<!-- Delete Confirmation Modal -->
<Modal open={showDeleteModal} title="Delete Machine" onclose={() => { showDeleteModal = false; }}>
	<div class="space-y-4">
		<p class="text-sm text-gray-600">
			Are you sure you want to delete <strong>{deleteMachine?.name}</strong>? This will also delete all sessions, samples, and data associated with this machine.
		</p>
		<div class="flex gap-2 justify-end">
			<button
				onclick={() => { showDeleteModal = false; }}
				class="rounded-lg border border-gray-300 px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50"
			>
				Cancel
			</button>
			<button
				onclick={handleDelete}
				class="rounded-lg bg-red-600 px-4 py-2 text-sm font-medium text-white hover:bg-red-700"
			>
				Delete
			</button>
		</div>
	</div>
</Modal>

<!-- Purge Data Confirmation Modal -->
<Modal open={showPurgeModal} title="Purge Machine Data" onclose={() => { showPurgeModal = false; }}>
	<div class="space-y-4">
		{#if purgeResult}
			<div class="rounded-lg bg-green-50 p-3 text-sm text-green-700">{purgeResult}</div>
			<div class="flex justify-end">
				<button
					onclick={() => { showPurgeModal = false; }}
					class="rounded-lg border border-gray-300 px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50"
				>
					Close
				</button>
			</div>
		{:else}
			<p class="text-sm text-gray-600">
				This will delete <strong>all upload sessions, samples, reviews, and files</strong> for <strong>{purgeMachine?.name}</strong>. The machine itself will remain.
			</p>
			<div class="flex gap-2 justify-end">
				<button
					onclick={() => { showPurgeModal = false; }}
					class="rounded-lg border border-gray-300 px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50"
				>
					Cancel
				</button>
				<button
					onclick={handlePurge}
					disabled={purging}
					class="rounded-lg bg-yellow-600 px-4 py-2 text-sm font-medium text-white hover:bg-yellow-700 disabled:opacity-50"
				>
					{purging ? 'Purging...' : 'Purge All Data'}
				</button>
			</div>
		{/if}
	</div>
</Modal>
