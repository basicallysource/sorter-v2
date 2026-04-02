<script lang="ts">
	import { auth } from '$lib/auth.svelte';
	import { api, type User } from '$lib/api';
	import { goto } from '$app/navigation';
	import Badge from '$lib/components/Badge.svelte';
	import Modal from '$lib/components/Modal.svelte';
	import Spinner from '$lib/components/Spinner.svelte';

	let users = $state<User[]>([]);
	let loading = $state(true);
	let error = $state<string | null>(null);

	// Role editing
	let editingUser = $state<User | null>(null);
	let selectedRole = $state('member');

	// Delete confirmation
	let deletingUser = $state<User | null>(null);
	let deleteError = $state<string | null>(null);

	$effect(() => {
		if (!auth.isAdmin) {
			goto('/');
			return;
		}
		loadUsers();
	});

	async function loadUsers() {
		loading = true;
		error = null;
		try {
			users = await api.getUsers();
		} catch (e: any) {
			error = e.error || 'Failed to load users';
		} finally {
			loading = false;
		}
	}

	function openRoleModal(user: User) {
		editingUser = user;
		selectedRole = user.role;
	}

	async function saveRole() {
		if (!editingUser) return;
		try {
			const updated = await api.updateUser(String(editingUser.id), { role: selectedRole });
			const idx = users.findIndex(u => u.id === updated.id);
			if (idx !== -1) users[idx] = updated;
			editingUser = null;
		} catch (e: any) {
			error = e.error || 'Failed to update role';
		}
	}

	async function toggleActive(user: User) {
		try {
			const updated = await api.updateUser(String(user.id), { is_active: !user.is_active });
			const idx = users.findIndex(u => u.id === updated.id);
			if (idx !== -1) users[idx] = updated;
		} catch (e: any) {
			error = e.error || 'Failed to update user';
		}
	}

	async function handleDeleteUser() {
		if (!deletingUser) return;
		deleteError = null;
		try {
			await api.deleteUser(String(deletingUser.id));
			users = users.filter(u => u.id !== deletingUser!.id);
			deletingUser = null;
		} catch (e: any) {
			deleteError = e.error || 'Failed to delete user';
		}
	}

	const roleVariant: Record<string, 'success' | 'info' | 'neutral' | 'warning'> = {
		admin: 'success',
		reviewer: 'info',
		member: 'neutral'
	};
</script>

<svelte:head>
	<title>Manage Users - SortHive</title>
</svelte:head>

<div class="mb-6 flex items-center justify-between">
	<h1 class="text-2xl font-bold text-gray-900">Manage Users</h1>
	<span class="text-sm text-gray-500">{users.length} users total</span>
</div>

{#if error}
	<div class="mb-4 bg-red-50 p-3 text-sm text-red-700">{error}</div>
{/if}

{#if loading}
	<div class="flex justify-center py-12">
		<Spinner />
	</div>
{:else}
	<div class="overflow-hidden border border-gray-200 bg-white">
		<table class="min-w-full divide-y divide-gray-200">
			<thead class="bg-gray-50">
				<tr>
					<th class="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">User</th>
					<th class="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Role</th>
					<th class="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Status</th>
					<th class="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Joined</th>
					<th class="px-6 py-3 text-right text-xs font-medium uppercase tracking-wider text-gray-500">Actions</th>
				</tr>
			</thead>
			<tbody class="divide-y divide-gray-200">
				{#each users as user (user.id)}
					<tr class="hover:bg-gray-50 {!user.is_active ? 'opacity-50' : ''}">
						<td class="whitespace-nowrap px-6 py-4">
							<div>
								<p class="text-sm font-medium text-gray-900">{user.display_name || '—'}</p>
								<p class="text-xs text-gray-500">{user.email}</p>
							</div>
						</td>
						<td class="whitespace-nowrap px-6 py-4">
							<button onclick={() => openRoleModal(user)} class="cursor-pointer">
								<Badge text={user.role} variant={roleVariant[user.role] ?? 'neutral'} />
							</button>
						</td>
						<td class="whitespace-nowrap px-6 py-4">
							<Badge
								text={user.is_active ? 'Active' : 'Inactive'}
								variant={user.is_active ? 'success' : 'danger'}
							/>
						</td>
						<td class="whitespace-nowrap px-6 py-4 text-sm text-gray-500">
							{new Date(user.created_at).toLocaleDateString()}
						</td>
						<td class="whitespace-nowrap px-6 py-4 text-right">
							<div class="flex items-center justify-end gap-2">
								<button
									onclick={() => toggleActive(user)}
									class="text-xs font-medium {user.is_active ? 'text-yellow-600 hover:text-yellow-800' : 'text-green-600 hover:text-green-800'}"
									title={user.is_active ? 'Deactivate' : 'Activate'}
								>
									{user.is_active ? 'Deactivate' : 'Activate'}
								</button>
								{#if String(user.id) !== String(auth.user?.id)}
									<button
										onclick={() => { deletingUser = user; }}
										class="text-xs font-medium text-red-600 hover:text-red-800"
									>
										Delete
									</button>
								{/if}
							</div>
						</td>
					</tr>
				{/each}
			</tbody>
		</table>
	</div>
{/if}

<!-- Role Edit Modal -->
<Modal open={editingUser !== null} title="Change Role" onclose={() => { editingUser = null; }}>
	{#if editingUser}
		<div class="space-y-4">
			<p class="text-sm text-gray-600">
				Change role for <strong>{editingUser.display_name || editingUser.email}</strong>
			</p>
			<div class="space-y-2">
				{#each ['member', 'reviewer', 'admin'] as role}
					<label class="flex items-center gap-3 border border-gray-200 p-3 cursor-pointer hover:bg-gray-50 {selectedRole === role ? 'border-blue-500 bg-blue-50' : ''}">
						<input type="radio" bind:group={selectedRole} value={role} class="text-blue-600" />
						<div>
							<p class="text-sm font-medium text-gray-900 capitalize">{role}</p>
							<p class="text-xs text-gray-500">
								{#if role === 'member'}
									Can manage own machines and view samples
								{:else if role === 'reviewer'}
									Can review and verify samples
								{:else}
									Full access including user management
								{/if}
							</p>
						</div>
					</label>
				{/each}
			</div>
			<div class="flex justify-end gap-2">
				<button
					onclick={() => { editingUser = null; }}
					class="border border-gray-300 px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50"
				>
					Cancel
				</button>
				<button
					onclick={saveRole}
					class="bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700"
				>
					Save Role
				</button>
			</div>
		</div>
	{/if}
</Modal>

<!-- Delete User Modal -->
<Modal open={deletingUser !== null} title="Delete User" onclose={() => { deletingUser = null; deleteError = null; }}>
	{#if deletingUser}
		<div class="space-y-4">
			{#if deleteError}
				<div class="bg-red-50 p-3 text-sm text-red-700">{deleteError}</div>
			{/if}
			<p class="text-sm text-gray-600">
				This will permanently delete <strong>{deletingUser.display_name || deletingUser.email}</strong> and all their machines, samples, and reviews.
			</p>
			<div class="flex justify-end gap-2">
				<button
					onclick={() => { deletingUser = null; deleteError = null; }}
					class="border border-gray-300 px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50"
				>
					Cancel
				</button>
				<button
					onclick={handleDeleteUser}
					class="bg-red-600 px-4 py-2 text-sm font-medium text-white hover:bg-red-700"
				>
					Delete User
				</button>
			</div>
		</div>
	{/if}
</Modal>
