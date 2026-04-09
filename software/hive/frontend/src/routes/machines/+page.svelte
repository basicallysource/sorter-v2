<script lang="ts">
	import { api, type Machine, type MachineProfileAssignment, type MachineStats, type MachineWithToken, type SortingProfileDetail, type SortingProfileSummary } from '$lib/api';
	import Badge from '$lib/components/Badge.svelte';
	import Modal from '$lib/components/Modal.svelte';
	import Spinner from '$lib/components/Spinner.svelte';

	let machines = $state<Machine[]>([]);
	let loading = $state(true);
	let error = $state<string | null>(null);

	let accessibleProfiles = $state<SortingProfileSummary[]>([]);
	let assignments = $state<Record<string, MachineProfileAssignment | null>>({});
	let setProgress = $state<Record<string, { total_needed: number; total_found: number } | null>>({});
	let machineStats = $state<Record<string, MachineStats>>({});

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

	async function loadSetProgressForAssignment(machineId: string, assignment: MachineProfileAssignment | null) {
		if (assignment?.profile?.profile_type !== 'set') {
			setProgress = { ...setProgress, [machineId]: null };
			return;
		}
		try {
			const result = await api.getMachineSetProgress(machineId);
			const total_needed = result.progress.reduce((sum, p) => sum + p.quantity_needed, 0);
			const total_found = result.progress.reduce((sum, p) => sum + p.quantity_found, 0);
			setProgress = {
				...setProgress,
				[machineId]: { total_needed, total_found }
			};
		} catch {
			setProgress = { ...setProgress, [machineId]: null };
		}
	}

	async function loadMachines() {
		loading = true;
		error = null;
		try {
			const [machineList, mine, library, stats] = await Promise.all([
				api.getMachines(),
				api.getProfiles({ scope: 'mine' }),
				api.getProfiles({ scope: 'library' }),
				api.getMachineStats()
			]);
			machines = machineList;
			accessibleProfiles = dedupeProfiles([...mine, ...library]);
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

			// Fetch set progress for machines with set-based profiles
			const nextSetProgress: Record<string, { total_needed: number; total_found: number } | null> = {};
			await Promise.all(
				machineList.map(async (machine) => {
					const assignment = nextAssignments[machine.id];
					if (assignment?.profile?.profile_type !== 'set') {
						nextSetProgress[machine.id] = null;
						return;
					}
					try {
						const result = await api.getMachineSetProgress(machine.id);
						const total_needed = result.progress.reduce((sum, p) => sum + p.quantity_needed, 0);
						const total_found = result.progress.reduce((sum, p) => sum + p.quantity_found, 0);
						nextSetProgress[machine.id] = { total_needed, total_found };
					} catch {
						nextSetProgress[machine.id] = null;
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

	function formatUptime(createdAt: string): string {
		const diff = Date.now() - new Date(createdAt).getTime();
		const days = Math.floor(diff / (1000 * 60 * 60 * 24));
		if (days < 1) return 'Today';
		if (days === 1) return '1 day';
		if (days < 30) return `${days} days`;
		const months = Math.floor(days / 30);
		if (months === 1) return '1 month';
		if (months < 12) return `${months} months`;
		const years = Math.floor(months / 12);
		return years === 1 ? '1 year' : `${years} years`;
	}

	function formatNumber(n: number): string {
		if (n >= 1000) return `${(n / 1000).toFixed(1).replace(/\.0$/, '')}k`;
		return n.toString();
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
			const nextAssignment = await api.assignMachineProfile(
				assignmentMachine.id,
				assignmentProfileId,
				assignmentVersionId
			);
			assignments = {
				...assignments,
				[assignmentMachine.id]: nextAssignment
			};
			await loadSetProgressForAssignment(assignmentMachine.id, nextAssignment);
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
			setProgress = { ...setProgress, [machine.id]: null };
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
	<title>Machines - Hive</title>
</svelte:head>

<div class="mb-6 flex items-center justify-between">
	<div>
		<h1 class="text-2xl font-bold text-[#1A1A1A]">Machines</h1>
		<p class="mt-1 text-sm text-[#7A7770]">
			Manage machine tokens and decide which sorting profile version each machine should pull.
		</p>
	</div>
	<button
		onclick={() => { showAddModal = true; }}
		class="bg-[#D01012] px-4 py-2 text-sm font-medium text-white hover:bg-[#B00E10]"
	>
		Add Machine
	</button>
</div>

{#if error}
	<div class="mb-4 bg-[#D01012]/8 p-3 text-sm text-[#D01012]">{error}</div>
{/if}

{#if loading}
	<Spinner />
{:else if machines.length === 0}
	<p class="text-[#7A7770]">No machines yet. Add one to get started.</p>
{:else}
	<div class="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
		{#each machines as machine (machine.id)}
			{@const assignment = assignments[machine.id]}
			{@const stats = machineStats[machine.id]}
			{@const isOnline = machine.last_seen_at && (Date.now() - new Date(machine.last_seen_at).getTime()) < 5 * 60 * 1000}
			{@const acceptRate = stats && stats.total_samples > 0 ? Math.round((stats.accepted_samples / stats.total_samples) * 100) : null}
			<div class="flex flex-col border border-[#E2E0DB] bg-white transition-colors hover:border-[#7A7770]">
				<!-- Header -->
				<div class="flex items-start gap-3 px-4 pt-4 pb-3">
					<div class="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center {isOnline ? 'bg-[#00852B]/10 text-[#00852B]' : 'bg-[#E2E0DB]/60 text-[#7A7770]'}">
						<svg class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor">
							<path stroke-linecap="square" stroke-linejoin="miter" d="M8.25 3v1.5M4.5 8.25H3m18 0h-1.5M4.5 12H3m18 0h-1.5m-15 3.75H3m18 0h-1.5M8.25 19.5V21M12 3v1.5m0 15V21m3.75-18v1.5m0 15V21m-9-1.5h10.5a2.25 2.25 0 002.25-2.25V6.75a2.25 2.25 0 00-2.25-2.25H6.75A2.25 2.25 0 004.5 6.75v10.5a2.25 2.25 0 002.25 2.25z" />
						</svg>
					</div>
					<div class="min-w-0 flex-1">
						<div class="flex items-center gap-2">
							<h3 class="truncate text-sm font-semibold text-[#1A1A1A]">{machine.name}</h3>
							<span class="shrink-0 text-[10px] font-medium uppercase tracking-wider {isOnline ? 'text-[#00852B]' : 'text-[#7A7770]'}">
								{isOnline ? 'Online' : 'Offline'}
							</span>
						</div>
						{#if machine.description}
							<p class="mt-0.5 truncate text-xs text-[#7A7770]">{machine.description}</p>
						{/if}
					</div>
					<div class="flex shrink-0 items-center gap-0.5">
						{#if machine.last_seen_ip}
							<a href={`http://${machine.last_seen_ip}:${machine.local_ui_port || '8000'}`}
								target="_blank" rel="noopener noreferrer"
								class="-mt-1 p-1.5 text-[#7A7770] hover:text-[#D01012]" title="Open local UI">
								<svg class="h-4 w-4" viewBox="0 0 20 20" fill="currentColor">
									<path fill-rule="evenodd" d="M4.25 5.5a.75.75 0 00-.75.75v8.5c0 .414.336.75.75.75h8.5a.75.75 0 00.75-.75v-4a.75.75 0 011.5 0v4A2.25 2.25 0 0112.75 17h-8.5A2.25 2.25 0 012 14.75v-8.5A2.25 2.25 0 014.25 4h5a.75.75 0 010 1.5h-5zm7.25-.75a.75.75 0 01.75-.75h3.5a.75.75 0 01.75.75v3.5a.75.75 0 01-1.5 0V6.31l-5.97 5.97a.75.75 0 01-1.06-1.06l5.97-5.97H12.25a.75.75 0 01-.75-.75z" clip-rule="evenodd" />
								</svg>
							</a>
						{/if}
					<!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
					<div class="relative" onclick={(event) => event.stopPropagation()}>
						<button onclick={() => toggleMenu(machine.id)}
							class="-mr-1 -mt-1 p-1.5 text-[#7A7770] hover:text-[#1A1A1A]" title="More actions">
							<svg class="h-4 w-4" fill="currentColor" viewBox="0 0 20 20">
								<path d="M10 6a2 2 0 110-4 2 2 0 010 4zM10 12a2 2 0 110-4 2 2 0 010 4zM10 18a2 2 0 110-4 2 2 0 010 4z" />
							</svg>
						</button>
						{#if openMenuId === machine.id}
							<div class="absolute right-0 z-10 mt-1 w-48 border border-[#E2E0DB] bg-white py-1 shadow-sm">
								<button onclick={() => openEdit(machine)} class="flex w-full items-center gap-2 px-4 py-2 text-sm text-[#1A1A1A] hover:bg-[#F7F6F3]">Edit</button>
								<button onclick={() => { void handleRotateToken(machine); openMenuId = null; }}
									class="flex w-full items-center gap-2 px-4 py-2 text-sm text-[#1A1A1A] hover:bg-[#F7F6F3]">
									Rotate Token
								</button>
								<div class="my-1 border-b border-[#E2E0DB]"></div>
								<button onclick={() => { openPurge(machine); openMenuId = null; }}
									class="flex w-full items-center gap-2 px-4 py-2 text-sm text-[#D01012] hover:bg-[#D01012]/8">
									Purge Data
								</button>
								<button onclick={() => { openDelete(machine); openMenuId = null; }}
									class="flex w-full items-center gap-2 px-4 py-2 text-sm text-[#D01012] hover:bg-[#FEF2F2]">
									Delete Machine
								</button>
							</div>
						{/if}
					</div>
					</div>
				</div>

				<!-- Stats grid -->
				<div class="grid grid-cols-3 gap-px border-t border-[#E2E0DB] bg-[#E2E0DB]">
					<div class="flex flex-col items-center bg-white py-3">
						<span class="text-lg font-bold text-[#1A1A1A]">{stats ? formatNumber(stats.total_samples) : '—'}</span>
						<span class="text-[10px] uppercase tracking-wider text-[#7A7770]">Samples</span>
					</div>
					<div class="flex flex-col items-center bg-white py-3">
						<span class="text-lg font-bold {acceptRate !== null && acceptRate >= 80 ? 'text-[#00852B]' : acceptRate !== null ? 'text-[#1A1A1A]' : 'text-[#1A1A1A]'}">
							{acceptRate !== null ? `${acceptRate}%` : '—'}
						</span>
						<span class="text-[10px] uppercase tracking-wider text-[#7A7770]">Accepted</span>
					</div>
					<div class="flex flex-col items-center bg-white py-3">
						<span class="text-lg font-bold text-[#1A1A1A]">{stats ? formatNumber(stats.total_sessions) : '—'}</span>
						<span class="text-[10px] uppercase tracking-wider text-[#7A7770]">Sessions</span>
					</div>
				</div>

				<!-- Set progress bar (if set-based profile) -->
				{#if stats && stats.parts_needed > 0}
					{@const pct = Math.round((stats.parts_found / stats.parts_needed) * 100)}
					<div class="border-t border-[#E2E0DB] px-4 py-2.5">
						<div class="mb-1.5 flex items-center justify-between text-xs">
							<span class="font-medium text-[#1A1A1A]">Parts Found</span>
							<span class="font-mono text-[#7A7770]">{stats.parts_found}/{stats.parts_needed}</span>
						</div>
						<div class="h-2 w-full bg-[#E2E0DB]">
							<div class="h-full bg-[#00852B] transition-all" style="width: {pct}%"></div>
						</div>
					</div>
				{/if}

				<!-- Profile assignment -->
				{#if assignment?.profile && assignment.desired_version}
					<div class="mt-auto border-t border-[#E2E0DB] px-4 py-2.5">
						<div class="flex items-center gap-2 text-xs">
							<svg class="h-3.5 w-3.5 shrink-0 text-[#7A7770]" viewBox="0 0 20 20" fill="currentColor">
								<path fill-rule="evenodd" d="M4.5 2A1.5 1.5 0 003 3.5v13A1.5 1.5 0 004.5 18h11a1.5 1.5 0 001.5-1.5V7.621a1.5 1.5 0 00-.44-1.06l-4.12-4.122A1.5 1.5 0 0011.378 2H4.5z" clip-rule="evenodd" />
							</svg>
								<a href={`/profiles/${assignment.profile.id}`} class="truncate font-medium text-[#1A1A1A] hover:text-[#D01012] hover:underline">{assignment.profile.name}</a>
							<span class="shrink-0 text-[#7A7770]">v{assignment.desired_version.version_number}</span>
							{#if assignment.active_version}
								<Badge text="Synced" variant="success" />
							{:else}
								<Badge text="Pending" variant="neutral" />
							{/if}
						</div>
					</div>
				{/if}

				<!-- Footer -->
				<div class="mt-auto border-t border-[#E2E0DB] bg-[#FAFAF8] px-4 py-2">
					<div class="flex items-center justify-between text-[10px] text-[#7A7770]">
						<span>Registered {formatUptime(machine.created_at)} ago</span>
						{#if machine.last_seen_at}
							<span>{isOnline ? 'Online now' : `Last seen ${new Date(machine.last_seen_at).toLocaleString()}`}</span>
						{:else}
							<span>Never connected</span>
						{/if}
					</div>
				</div>
			</div>
		{/each}
	</div>
{/if}

<Modal open={showAddModal} title="Add Machine" onclose={() => { showAddModal = false; }}>
	<form onsubmit={handleAdd} class="space-y-4">
		<div>
			<label for="machineName" class="mb-1 block text-sm font-medium text-[#1A1A1A]">Name</label>
			<input
				id="machineName"
				type="text"
				bind:value={newName}
				required
				class="w-full border border-[#E2E0DB] px-3 py-2 text-sm focus:border-[#D01012] focus:ring-1 focus:ring-[#D01012] focus:outline-none"
			/>
		</div>
		<div>
			<label for="machineDesc" class="mb-1 block text-sm font-medium text-[#1A1A1A]">Description (optional)</label>
			<input
				id="machineDesc"
				type="text"
				bind:value={newDescription}
				class="w-full border border-[#E2E0DB] px-3 py-2 text-sm focus:border-[#D01012] focus:ring-1 focus:ring-[#D01012] focus:outline-none"
			/>
		</div>
		<button
			type="submit"
			disabled={addSubmitting}
			class="w-full bg-[#D01012] px-4 py-2 text-sm font-medium text-white hover:bg-[#B00E10] disabled:opacity-50"
		>
			{addSubmitting ? 'Creating...' : 'Create Machine'}
		</button>
	</form>
</Modal>

<Modal open={showTokenModal} title="API Token" onclose={() => { showTokenModal = false; }}>
	<div class="space-y-4">
		<div class="bg-[#FFD500]/12 p-3 text-sm text-[#A16207]">
			Save this token now. It will not be shown again.
		</div>
		<div class="flex items-center gap-2">
			<code class="flex-1 overflow-x-auto bg-[#F7F6F3] p-2 text-xs break-all">{tokenDisplay}</code>
			<button
				onclick={copyToken}
				class="shrink-0 border border-[#E2E0DB] px-3 py-1 text-xs font-medium text-[#1A1A1A] hover:bg-[#F7F6F3]"
			>
				{tokenCopied ? 'Copied!' : 'Copy'}
			</button>
		</div>
	</div>
</Modal>

<Modal open={showEditModal} title="Edit Machine" onclose={() => { showEditModal = false; }}>
	<form onsubmit={handleEdit} class="space-y-4">
		<div>
			<label for="editName" class="mb-1 block text-sm font-medium text-[#1A1A1A]">Name</label>
			<input
				id="editName"
				type="text"
				bind:value={editName}
				required
				class="w-full border border-[#E2E0DB] px-3 py-2 text-sm focus:border-[#D01012] focus:ring-1 focus:ring-[#D01012] focus:outline-none"
			/>
		</div>
		<button
			type="submit"
			class="w-full bg-[#D01012] px-4 py-2 text-sm font-medium text-white hover:bg-[#B00E10]"
		>
			Save
		</button>
	</form>
</Modal>

<Modal open={showDeleteModal} title="Delete Machine" onclose={() => { showDeleteModal = false; }}>
	<div class="space-y-4">
		<p class="text-sm text-[#7A7770]">
			Are you sure you want to delete <strong>{deleteMachine?.name}</strong>? This also removes upload sessions, samples, and reviews associated with this machine.
		</p>
		<div class="flex justify-end gap-2">
			<button
				onclick={() => { showDeleteModal = false; }}
				class="border border-[#E2E0DB] px-4 py-2 text-sm font-medium text-[#1A1A1A] hover:bg-[#F7F6F3]"
			>
				Cancel
			</button>
			<button
				onclick={handleDelete}
				class="bg-[#D01012] px-4 py-2 text-sm font-medium text-white hover:bg-[#B00E10]"
			>
				Delete
			</button>
		</div>
	</div>
</Modal>

<Modal open={showPurgeModal} title="Purge Machine Data" onclose={() => { showPurgeModal = false; }}>
	<div class="space-y-4">
		{#if purgeResult}
			<div class="bg-[#00852B]/10 p-3 text-sm text-[#00852B]">{purgeResult}</div>
			<div class="flex justify-end">
				<button
					onclick={() => { showPurgeModal = false; }}
					class="border border-[#E2E0DB] px-4 py-2 text-sm font-medium text-[#1A1A1A] hover:bg-[#F7F6F3]"
				>
					Close
				</button>
			</div>
		{:else}
			<p class="text-sm text-[#7A7770]">
				This deletes <strong>all upload sessions, samples, reviews, and files</strong> for <strong>{purgeMachine?.name}</strong>. The machine itself remains registered.
			</p>
			<div class="flex justify-end gap-2">
				<button
					onclick={() => { showPurgeModal = false; }}
					class="border border-[#E2E0DB] px-4 py-2 text-sm font-medium text-[#1A1A1A] hover:bg-[#F7F6F3]"
				>
					Cancel
				</button>
				<button
					onclick={handlePurge}
					disabled={purging}
					class="bg-[#D01012] px-4 py-2 text-sm font-medium text-white hover:bg-[#B00E10] disabled:opacity-50"
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
			<p class="text-sm text-[#7A7770]">
				No profiles are available yet. Create one or save a public profile to your library first.
			</p>
			<div class="flex justify-end">
				<a
					href="/profiles?scope=mine"
					class="border border-[#E2E0DB] px-4 py-2 text-sm font-medium text-[#1A1A1A] hover:bg-[#F7F6F3]"
				>
					Open Profiles
				</a>
			</div>
		{:else}
			<div>
				<label for="assignment-profile" class="mb-1 block text-sm font-medium text-[#1A1A1A]">Profile</label>
				<select
					id="assignment-profile"
					bind:value={assignmentProfileId}
					onchange={(event) => void handleAssignmentProfileChange((event.currentTarget as HTMLSelectElement).value)}
					class="w-full border border-[#E2E0DB] px-3 py-2 text-sm focus:border-[#D01012] focus:outline-none focus:ring-1 focus:ring-[#D01012]"
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
				<label for="assignment-version" class="mb-1 block text-sm font-medium text-[#1A1A1A]">Version</label>
				<select
					id="assignment-version"
					bind:value={assignmentVersionId}
					disabled={!assignmentProfileDetail}
					class="w-full border border-[#E2E0DB] px-3 py-2 text-sm focus:border-[#D01012] focus:outline-none focus:ring-1 focus:ring-[#D01012] disabled:bg-[#F7F6F3]"
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
				<div class="bg-[#F7F6F3] p-3 text-sm text-[#7A7770]">
					<div class="font-medium text-[#1A1A1A]">{assignmentProfileDetail.name}</div>
					{#if assignmentProfileDetail.description}
						<p class="mt-1">{assignmentProfileDetail.description}</p>
					{/if}
					<div class="mt-2 text-xs text-[#7A7770]">
						{assignmentProfileDetail.latest_version?.compiled_part_count ?? 0} mapped parts in the newest visible version
					</div>
				</div>
			{/if}

			<div class="flex justify-end gap-2">
				{#if assignmentMachine && assignments[assignmentMachine.id]}
					<button
						onclick={() => { if (assignmentMachine) void handleClearAssignment(assignmentMachine); }}
						disabled={assignmentClearing}
						class="border border-[#E2E0DB] px-4 py-2 text-sm font-medium text-[#1A1A1A] hover:bg-[#F7F6F3] disabled:opacity-50"
					>
						{assignmentClearing ? 'Clearing...' : 'Clear'}
					</button>
				{/if}
				<button
					onclick={() => void handleSaveAssignment()}
					disabled={assignmentSaving || !assignmentProfileId || !assignmentVersionId}
					class="bg-[#D01012] px-4 py-2 text-sm font-medium text-white hover:bg-[#B00E10] disabled:opacity-50"
				>
					{assignmentSaving ? 'Saving...' : 'Save Assignment'}
				</button>
			</div>
		{/if}
	</div>
</Modal>
