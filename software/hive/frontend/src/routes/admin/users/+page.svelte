<script lang="ts">
	import { sentence } from '$lib/text';
	import { auth } from '$lib/auth.svelte';
	import { api, type User } from '$lib/api';
	import { goto } from '$app/navigation';
	import Badge from '$lib/components/Badge.svelte';
	import Modal from '$lib/components/Modal.svelte';
	import Spinner from '$lib/components/Spinner.svelte';
	import Alert from '$lib/components/Alert.svelte';
	import Button from '$lib/components/Button.svelte';
	import PageHeader from '$lib/components/PageHeader.svelte';
	import Panel from '$lib/components/Panel.svelte';
	import RadioGroup from '$lib/components/RadioGroup.svelte';
	import Trash2 from '@lucide/svelte/icons/trash-2';

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
	<title>Users - Hive</title>
</svelte:head>

<PageHeader title="Users">
	{#snippet actions()}<span class="num text-sm text-ink-muted">{users.length} users</span>{/snippet}
</PageHeader>

{#if error}<Alert tone="danger">{error}</Alert>{/if}

{#if loading}
	<div class="flex justify-center py-12"><Spinner size={32} /></div>
{:else}
	<Panel flush>
		<div class="overflow-x-auto">
			<table class="data-table">
				<thead>
					<tr><th>Person</th><th>Role</th><th>Status</th><th>Joined</th><th aria-label="Actions"></th></tr>
				</thead>
				<tbody>
					{#each users as user (user.id)}
						<tr class={user.is_active ? '' : 'opacity-50'}>
							<td>
								<div class="font-medium">{user.display_name || '-'}</div>
								<div class="text-ink-muted">{user.email}</div>
							</td>
							<td>
								<button type="button" onclick={() => openRoleModal(user)} title="Change the role">
									<Badge tone={roleVariant[user.role] ?? 'neutral'}>{sentence(user.role)}</Badge>
								</button>
							</td>
							<td><Badge tone={user.is_active ? 'success' : 'danger'} dot>{user.is_active ? 'Active' : 'Inactive'}</Badge></td>
							<td class="whitespace-nowrap text-ink-muted">{new Date(user.created_at).toLocaleDateString()}</td>
							<td>
								<div class="flex items-center justify-end gap-1">
									<Button size="sm" variant="ghost" onclick={() => toggleActive(user)}
										>{user.is_active ? 'Deactivate' : 'Activate'}</Button
									>
									{#if String(user.id) !== String(auth.user?.id)}
										<Button size="sm" variant="ghost" icon={Trash2} label="Delete the user" onclick={() => (deletingUser = user)} />
									{/if}
								</div>
							</td>
						</tr>
					{/each}
				</tbody>
			</table>
		</div>
	</Panel>
{/if}

<Modal open={editingUser !== null} title="Change the role" size="sm" onclose={() => (editingUser = null)}>
	{#if editingUser}
		<p class="mb-4 text-sm text-ink-muted">For {editingUser.display_name || editingUser.email}.</p>
		<RadioGroup
			name="user-role"
			label="Role"
			bind:value={selectedRole}
			options={[
				{ value: 'member', label: 'Member', help: 'Manages their own machines and sees samples.' },
				{ value: 'reviewer', label: 'Reviewer', help: 'Reviews and verifies samples too.' },
				{ value: 'admin', label: 'Admin', help: 'Everything, including managing people.' }
			]}
		/>
	{/if}
	{#snippet footer()}
		<Button variant="ghost" onclick={() => (editingUser = null)}>Cancel</Button>
		<Button variant="primary" onclick={saveRole}>Save role</Button>
	{/snippet}
</Modal>

<Modal
	open={deletingUser !== null}
	title="Delete the user"
	size="sm"
	onclose={() => {
		deletingUser = null;
		deleteError = null;
	}}
>
	{#if deleteError}<Alert tone="danger" class="mb-3">{deleteError}</Alert>{/if}
	{#if deletingUser}
		<p class="text-sm text-ink-muted">
			This deletes <strong class="font-medium text-ink">{deletingUser.display_name || deletingUser.email}</strong> and all
			their machines, samples and reviews, for good.
		</p>
	{/if}
	{#snippet footer()}
		<Button
			variant="ghost"
			onclick={() => {
				deletingUser = null;
				deleteError = null;
			}}>Cancel</Button
		>
		<Button variant="danger" onclick={handleDeleteUser}>Delete user</Button>
	{/snippet}
</Modal>
