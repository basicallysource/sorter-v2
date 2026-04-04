<script lang="ts">
	import { api, type Machine, type MachineProfileAssignment, type MachineWithToken, type SortingProfileDetail, type SortingProfileSummary } from '$lib/api';
	import Badge from '$lib/components/Badge.svelte';
	import Modal from '$lib/components/Modal.svelte';
	import Spinner from '$lib/components/Spinner.svelte';

	let machines = $state<Machine[]>([]);
	let loading = $state(true);
	let error = $state<string | null>(null);

	let accessibleProfiles = $state<SortingProfileSummary[]>([]);
	let assignments = $state<Record<string, MachineProfileAssignment | null>>({});
	let setProgress = $state<Record<string, { total_needed: number; total_found: number } | null>>({});

	let showAddModal = $state(false);
	let newName = $state('');
	let newDescription = $state('');
	let addSubmitting = $state(false);

	let showTokenModal = $state(false);
	let tokenDisplay = $state('');
	let tokenCopied = $state(false);

	let showEditModal = $state(false);
	let editMachine = $state<Machine | null>(null);
	let editName = $state('');

	let showDeleteModal = $state(false);
	let deleteMachine = $state<Machine | null>(null);

	let showPurgeModal = $state(false);
	let purgeMachine = $state<Machine | null>(null);
	let purging = $state(false);
	let purgeResult = $state<string | null>(null);

	let showAssignModal = $state(false);
	let assignmentMachine = $state<Machine | null>(null);
	let assignmentProfileId = $state('');
	let assignmentVersionId = $state('');
	let assignmentLoading = $state(false);
	let assignmentSaving = $state(false);
	let assignmentClearing = $state(false);
	let assignmentProfileDetail = $state<SortingProfileDetail | null>(null);

	let openMenuId = $state<string | null>(null);

	$effect(() => {
		void loadMachines();
	});

	async function loadMachines() {
		loading = true;
		error = null;
		try {
			const [machineList, mine, library] = await Promise.all([
				api.getMachines(),
				api.getProfiles({ scope: 'mine' }),
				api.getProfiles({ scope: 'library' })
			]);
			machines = machineList;
			accessibleProfiles = dedupeProfiles([...mine, ...library]);

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

			// Fetch set progress for machines with set-based profiles
			const nextSetProgress: Record<string, { total_needed: number; total_found: number } | null> = {};
			await Promise.all(
				machineList.map(async (machine) => {
					const a = nextAssignments[machine.id];
					if (a?.profile?.profile_type === 'set') {
						try {
							const result = await api.getMachineSetProgress(machine.id);
							const total_needed = result.progress.reduce((sum, p) => sum + p.quantity_needed, 0);
							const total_found = result.progress.reduce((sum, p) => sum + p.quantity_found, 0);
							nextSetProgress[machine.id] = { total_needed, total_found };
						} catch {
							nextSetProgress[machine.id] = null;
						}
					}
				})
			);
			setProgress = nextSetProgress;
		} catch (err) {
			error = (err as { error?: string }).error || 'Failed to load machines';
		} finally {
			loading = false;
		}
	}

	function dedupeProfiles(items: SortingProfileSummary[]) {
		const seen = new Set<string>();
		return items.filter((profile) => {
			if (seen.has(profile.id)) return false;
			seen.add(profile.id);
			return true;
		});
	}

	async function handleAdd(event: Event) {
		event.preventDefault();
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
			tokenCopied = false;
			showTokenModal = true;
		} catch (err) {
			error = (err as { error?: string }).error || 'Failed to rotate token';
		}
	}

	async function handleEdit(event: Event) {
		event.preventDefault();
		if (!editMachine) return;
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

	function toggleMenu(machineId: string) {
		openMenuId = openMenuId === machineId ? null : machineId;
	}

	async function copyToken() {
		await navigator.clipboard.writeText(tokenDisplay);
		tokenCopied = true;
	}

	function visibleVersions(detail: SortingProfileDetail | null) {
		if (!detail) return [];
		return detail.is_owner ? detail.versions : detail.versions.filter((version) => version.is_published);
	}

	async function openAssignModal(machine: Machine) {
		showAssignModal = true;
		assignmentMachine = machine;
		assignmentLoading = true;
		assignmentProfileDetail = null;
		error = null;

		try {
			const existingAssignment = assignments[machine.id];
			if (existingAssignment?.profile) {
				assignmentProfileId = existingAssignment.profile.id;
				const detail = await loadAssignmentProfile(existingAssignment.profile.id);
				assignmentVersionId =
					existingAssignment.desired_version?.id ??
					detail.current_version?.id ??
					visibleVersions(detail)[0]?.id ??
					'';
			} else {
				const defaultProfile = accessibleProfiles[0] ?? null;
				assignmentProfileId = defaultProfile?.id ?? '';
				if (defaultProfile) {
					const detail = await loadAssignmentProfile(defaultProfile.id);
					assignmentVersionId =
						detail.current_version?.id ?? visibleVersions(detail)[0]?.id ?? '';
				} else {
					assignmentVersionId = '';
				}
			}
		} catch (err) {
			error = (err as { error?: string }).error || 'Failed to load assignment options';
		} finally {
			assignmentLoading = false;
		}
	}

async function loadAssignmentProfile(profileId: string) {
	const detail = await api.getSortingProfile(profileId);
	assignmentProfileDetail = detail;
	return detail;
}

	async function handleAssignmentProfileChange(profileId: string) {
		assignmentProfileId = profileId;
		assignmentVersionId = '';
		if (!profileId) {
			assignmentProfileDetail = null;
			return;
		}
	assignmentLoading = true;
	try {
		const detail = await loadAssignmentProfile(profileId);
		assignmentVersionId = detail.current_version?.id ?? visibleVersions(detail)[0]?.id ?? '';
	} catch (err) {
		error = (err as { error?: string }).error || 'Failed to load versions';
	} finally {
			assignmentLoading = false;
		}
	}

	async function handleSaveAssignment() {
		if (!assignmentMachine || !assignmentProfileId || !assignmentVersionId) return;
		assignmentSaving = true;
		error = null;
		try {
			assignments = {
				...assignments,
				[assignmentMachine.id]: await api.assignMachineProfile(
					assignmentMachine.id,
					assignmentProfileId,
					assignmentVersionId
				)
			};
			showAssignModal = false;
		} catch (err) {
			error = (err as { error?: string }).error || 'Failed to assign profile';
		} finally {
			assignmentSaving = false;
		}
	}

	async function handleClearAssignment(machine: Machine) {
		assignmentClearing = true;
		error = null;
		try {
			await api.clearMachineProfileAssignment(machine.id);
			assignments = { ...assignments, [machine.id]: null };
			if (assignmentMachine?.id === machine.id) {
				showAssignModal = false;
			}
		} catch (err) {
			error = (err as { error?: string }).error || 'Failed to clear machine assignment';
		} finally {
			assignmentClearing = false;
		}
	}
</script>

<svelte:window onclick={() => { openMenuId = null; }} />

<svelte:head>
	<title>Machines - SortHive</title>
</svelte:head>

<div class="mb-6 flex items-center justify-between">
	<div>
		<h1 class="text-2xl font-bold text-gray-900">Machines</h1>
		<p class="mt-1 text-sm text-gray-500">
			Manage machine tokens and decide which sorting profile version each machine should pull.
		</p>
	</div>
	<button
		onclick={() => { showAddModal = true; }}
		class="bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700"
	>
		Add Machine
	</button>
</div>

{#if error}
	<div class="mb-4 bg-red-50 p-3 text-sm text-red-700">{error}</div>
{/if}

{#if loading}
	<Spinner />
{:else if machines.length === 0}
	<p class="text-gray-500">No machines yet. Add one to get started.</p>
{:else}
	<div class="space-y-4">
		{#each machines as machine (machine.id)}
			{@const assignment = assignments[machine.id]}
			<div class="border border-gray-200 bg-white p-4">
				<div class="flex flex-wrap items-start justify-between gap-4">
					<div class="space-y-3">
						<div>
							<h3 class="font-semibold text-gray-900">{machine.name}</h3>
							{#if machine.description}
								<p class="mt-1 text-sm text-gray-500">{machine.description}</p>
							{/if}
							<div class="mt-2 flex flex-wrap items-center gap-3 text-xs text-gray-500">
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

						<div class="rounded bg-gray-50 p-3 text-sm">
							{#if assignment?.profile && assignment.desired_version}
								<div class="font-medium text-gray-900">
									Desired profile: {assignment.profile.name} v{assignment.desired_version.version_number}
								</div>
								<div class="mt-1 text-gray-600">
									{#if assignment.active_version}
										Active on machine: v{assignment.active_version.version_number}
									{:else}
										Not active on the machine yet
									{/if}
								</div>
								<div class="mt-1 text-xs text-gray-500">
									{#if assignment.last_activated_at}
										Last activated: {new Date(assignment.last_activated_at).toLocaleString()}
									{:else if assignment.last_synced_at}
										Last synced: {new Date(assignment.last_synced_at).toLocaleString()}
									{/if}
								</div>
								{#if assignment.last_error}
									<div class="mt-2 text-xs text-red-600">{assignment.last_error}</div>
								{/if}
								{#if assignment.profile?.profile_type === 'set' && setProgress[machine.id]}
									{@const sp = setProgress[machine.id]!}
									{@const pct = sp.total_needed > 0 ? Math.round((sp.total_found / sp.total_needed) * 100) : 0}
									<div class="mt-2">
										<div class="flex items-center justify-between text-xs text-gray-600">
											<span>Set progress: {sp.total_found}/{sp.total_needed} parts</span>
											<span class="font-medium">{pct}%</span>
										</div>
										<div class="mt-1 h-1.5 w-full bg-gray-200">
											<div class="h-full bg-green-500 transition-all" style="width: {pct}%"></div>
										</div>
									</div>
								{/if}
							{:else}
								<div class="font-medium text-gray-900">No sorting profile assigned</div>
								<div class="mt-1 text-gray-600">
									Choose any profile from your library or your own drafts, then the machine can pull that version.
								</div>
							{/if}
						</div>
					</div>

					<div class="flex flex-wrap items-center gap-2">
						<button
							onclick={() => void openAssignModal(machine)}
							class="border border-gray-300 px-3 py-1.5 text-xs font-medium text-gray-700 hover:bg-gray-50"
						>
							{assignment ? 'Change Profile' : 'Assign Profile'}
						</button>
						{#if assignment}
							<button
								onclick={() => void handleClearAssignment(machine)}
								disabled={assignmentClearing}
								class="border border-gray-300 px-3 py-1.5 text-xs font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-50"
							>
								Clear Profile
							</button>
						{/if}
						<button
							onclick={() => openEdit(machine)}
							class="border border-gray-300 px-3 py-1.5 text-xs font-medium text-gray-700 hover:bg-gray-50"
						>
							Edit
						</button>
						<!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
						<div class="relative" onclick={(event) => event.stopPropagation()}>
							<button
								onclick={() => toggleMenu(machine.id)}
								class="border border-gray-300 p-1.5 text-gray-500 hover:bg-gray-50"
								title="More actions"
							>
								<svg class="h-4 w-4" fill="currentColor" viewBox="0 0 20 20">
									<path d="M10 6a2 2 0 110-4 2 2 0 010 4zM10 12a2 2 0 110-4 2 2 0 010 4zM10 18a2 2 0 110-4 2 2 0 010 4z" />
								</svg>
							</button>
							{#if openMenuId === machine.id}
								<div class="absolute right-0 z-10 mt-1 w-44 border border-gray-200 bg-white py-1 shadow-lg">
									<button
										onclick={() => { void handleRotateToken(machine); openMenuId = null; }}
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

<Modal open={showAddModal} title="Add Machine" onclose={() => { showAddModal = false; }}>
	<form onsubmit={handleAdd} class="space-y-4">
		<div>
			<label for="machineName" class="mb-1 block text-sm font-medium text-gray-700">Name</label>
			<input
				id="machineName"
				type="text"
				bind:value={newName}
				required
				class="w-full border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:ring-1 focus:ring-blue-500 focus:outline-none"
			/>
		</div>
		<div>
			<label for="machineDesc" class="mb-1 block text-sm font-medium text-gray-700">Description (optional)</label>
			<input
				id="machineDesc"
				type="text"
				bind:value={newDescription}
				class="w-full border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:ring-1 focus:ring-blue-500 focus:outline-none"
			/>
		</div>
		<button
			type="submit"
			disabled={addSubmitting}
			class="w-full bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
		>
			{addSubmitting ? 'Creating...' : 'Create Machine'}
		</button>
	</form>
</Modal>

<Modal open={showTokenModal} title="API Token" onclose={() => { showTokenModal = false; }}>
	<div class="space-y-4">
		<div class="bg-yellow-50 p-3 text-sm text-yellow-800">
			Save this token now. It will not be shown again.
		</div>
		<div class="flex items-center gap-2">
			<code class="flex-1 overflow-x-auto bg-gray-100 p-2 text-xs break-all">{tokenDisplay}</code>
			<button
				onclick={copyToken}
				class="shrink-0 border border-gray-300 px-3 py-1 text-xs font-medium text-gray-700 hover:bg-gray-50"
			>
				{tokenCopied ? 'Copied!' : 'Copy'}
			</button>
		</div>
	</div>
</Modal>

<Modal open={showEditModal} title="Edit Machine" onclose={() => { showEditModal = false; }}>
	<form onsubmit={handleEdit} class="space-y-4">
		<div>
			<label for="editName" class="mb-1 block text-sm font-medium text-gray-700">Name</label>
			<input
				id="editName"
				type="text"
				bind:value={editName}
				required
				class="w-full border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:ring-1 focus:ring-blue-500 focus:outline-none"
			/>
		</div>
		<button
			type="submit"
			class="w-full bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700"
		>
			Save
		</button>
	</form>
</Modal>

<Modal open={showDeleteModal} title="Delete Machine" onclose={() => { showDeleteModal = false; }}>
	<div class="space-y-4">
		<p class="text-sm text-gray-600">
			Are you sure you want to delete <strong>{deleteMachine?.name}</strong>? This also removes upload sessions, samples, and reviews associated with this machine.
		</p>
		<div class="flex justify-end gap-2">
			<button
				onclick={() => { showDeleteModal = false; }}
				class="border border-gray-300 px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50"
			>
				Cancel
			</button>
			<button
				onclick={handleDelete}
				class="bg-red-600 px-4 py-2 text-sm font-medium text-white hover:bg-red-700"
			>
				Delete
			</button>
		</div>
	</div>
</Modal>

<Modal open={showPurgeModal} title="Purge Machine Data" onclose={() => { showPurgeModal = false; }}>
	<div class="space-y-4">
		{#if purgeResult}
			<div class="bg-green-50 p-3 text-sm text-green-700">{purgeResult}</div>
			<div class="flex justify-end">
				<button
					onclick={() => { showPurgeModal = false; }}
					class="border border-gray-300 px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50"
				>
					Close
				</button>
			</div>
		{:else}
			<p class="text-sm text-gray-600">
				This deletes <strong>all upload sessions, samples, reviews, and files</strong> for <strong>{purgeMachine?.name}</strong>. The machine itself remains registered.
			</p>
			<div class="flex justify-end gap-2">
				<button
					onclick={() => { showPurgeModal = false; }}
					class="border border-gray-300 px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50"
				>
					Cancel
				</button>
				<button
					onclick={handlePurge}
					disabled={purging}
					class="bg-yellow-600 px-4 py-2 text-sm font-medium text-white hover:bg-yellow-700 disabled:opacity-50"
				>
					{purging ? 'Purging...' : 'Purge All Data'}
				</button>
			</div>
		{/if}
	</div>
</Modal>

<Modal
	open={showAssignModal}
	title={assignmentMachine ? `Assign Profile to ${assignmentMachine.name}` : 'Assign Profile'}
	onclose={() => { showAssignModal = false; }}
>
	<div class="space-y-4">
		{#if assignmentLoading}
			<Spinner />
		{:else if accessibleProfiles.length === 0}
			<p class="text-sm text-gray-600">
				No profiles are available yet. Create one or save a public profile to your library first.
			</p>
			<div class="flex justify-end">
				<a
					href="/profiles?scope=mine"
					class="border border-gray-300 px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50"
				>
					Open Profiles
				</a>
			</div>
		{:else}
			<div>
				<label for="assignment-profile" class="mb-1 block text-sm font-medium text-gray-700">Profile</label>
				<select
					id="assignment-profile"
					bind:value={assignmentProfileId}
					onchange={(event) => void handleAssignmentProfileChange((event.currentTarget as HTMLSelectElement).value)}
					class="w-full border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
				>
					<option value="">Select a profile</option>
					{#each accessibleProfiles as profile}
						<option value={profile.id}>
							{profile.name}
							{profile.is_owner ? ' · your profile' : ` · ${profile.owner.display_name ?? profile.owner.github_login ?? 'community'}`}
						</option>
					{/each}
				</select>
			</div>

			<div>
				<label for="assignment-version" class="mb-1 block text-sm font-medium text-gray-700">Version</label>
				<select
					id="assignment-version"
					bind:value={assignmentVersionId}
					disabled={!assignmentProfileDetail}
					class="w-full border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500 disabled:bg-gray-50"
				>
					<option value="">Select a version</option>
					{#each visibleVersions(assignmentProfileDetail) as version}
						<option value={version.id}>
							v{version.version_number}
							{version.label ? ` · ${version.label}` : ''}
							{version.is_published ? ' · published' : ' · draft'}
						</option>
					{/each}
				</select>
			</div>

			{#if assignmentProfileDetail}
				<div class="rounded bg-gray-50 p-3 text-sm text-gray-600">
					<div class="font-medium text-gray-900">{assignmentProfileDetail.name}</div>
					{#if assignmentProfileDetail.description}
						<p class="mt-1">{assignmentProfileDetail.description}</p>
					{/if}
					<div class="mt-2 text-xs text-gray-500">
						{assignmentProfileDetail.latest_version?.compiled_part_count ?? 0} mapped parts in the newest visible version
					</div>
				</div>
			{/if}

			<div class="flex justify-end gap-2">
				{#if assignmentMachine && assignments[assignmentMachine.id]}
					<button
						onclick={() => { if (assignmentMachine) void handleClearAssignment(assignmentMachine); }}
						disabled={assignmentClearing}
						class="border border-gray-300 px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-50"
					>
						{assignmentClearing ? 'Clearing...' : 'Clear'}
					</button>
				{/if}
				<button
					onclick={() => void handleSaveAssignment()}
					disabled={assignmentSaving || !assignmentProfileId || !assignmentVersionId}
					class="bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
				>
					{assignmentSaving ? 'Saving...' : 'Save Assignment'}
				</button>
			</div>
		{/if}
	</div>
</Modal>
