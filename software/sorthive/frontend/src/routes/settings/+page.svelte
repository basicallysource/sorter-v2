<script lang="ts">
	import { auth } from '$lib/auth.svelte';
	import { api } from '$lib/api';
	import { goto } from '$app/navigation';
	import Modal from '$lib/components/Modal.svelte';
	import Badge from '$lib/components/Badge.svelte';

	let showDeleteModal = $state(false);
	let deleteError = $state<string | null>(null);

	// Profile editing
	let editingName = $state(false);
	let displayName = $state(auth.user?.display_name ?? '');
	let nameError = $state<string | null>(null);
	let nameSaved = $state(false);

	// Password change
	let currentPassword = $state('');
	let newPassword = $state('');
	let confirmPassword = $state('');
	let passwordError = $state<string | null>(null);
	let passwordSaved = $state(false);

	// AI / OpenRouter
	let openrouterApiKey = $state('');
	let preferredAiModel = $state(auth.user?.preferred_ai_model ?? 'anthropic/claude-sonnet-4.6');
	let aiError = $state<string | null>(null);
	let aiSaved = $state(false);
	let aiSaving = $state(false);

	const aiModelOptions = [
		'anthropic/claude-sonnet-4.6',
		'anthropic/claude-3.7-sonnet',
		'openai/gpt-5.4',
		'google/gemini-3.1-pro-preview',
		'google/gemini-3-flash-preview'
	];

	async function handleSaveName() {
		nameError = null;
		nameSaved = false;
		try {
			const updated = await api.updateProfile({ display_name: displayName });
			if (auth.user) {
				auth.user.display_name = updated.display_name;
			}
			editingName = false;
			nameSaved = true;
			setTimeout(() => { nameSaved = false; }, 3000);
		} catch (e: any) {
			nameError = e.error || 'Failed to update name';
		}
	}

	async function handleChangePassword() {
		passwordError = null;
		passwordSaved = false;

		if (newPassword.length < 8) {
			passwordError = 'Password must be at least 8 characters';
			return;
		}
		if (newPassword !== confirmPassword) {
			passwordError = 'Passwords do not match';
			return;
		}

		try {
			const updated = await api.updateProfile({ current_password: currentPassword, new_password: newPassword });
			if (auth.user) {
				auth.user.has_password = updated.has_password;
			}
			currentPassword = '';
			newPassword = '';
			confirmPassword = '';
			passwordSaved = true;
			setTimeout(() => { passwordSaved = false; }, 3000);
		} catch (e: any) {
			passwordError = e.error || 'Failed to change password';
		}
	}

	async function handleLogout() {
		await auth.logout();
		goto('/login');
	}

	async function handleSaveAiSettings() {
		aiError = null;
		aiSaved = false;
		aiSaving = true;
		try {
			const updated = await api.updateProfile({
				openrouter_api_key: openrouterApiKey.trim() || undefined,
				preferred_ai_model: preferredAiModel.trim() || null
			});
			if (auth.user) {
				auth.user.openrouter_configured = updated.openrouter_configured;
				auth.user.preferred_ai_model = updated.preferred_ai_model;
			}
			openrouterApiKey = '';
			aiSaved = true;
			setTimeout(() => { aiSaved = false; }, 3000);
		} catch (e: any) {
			aiError = e.error || 'Failed to save AI settings';
		} finally {
			aiSaving = false;
		}
	}

	async function handleClearAiKey() {
		aiError = null;
		aiSaved = false;
		aiSaving = true;
		try {
			const updated = await api.updateProfile({
				clear_openrouter_api_key: true
			});
			if (auth.user) {
				auth.user.openrouter_configured = updated.openrouter_configured;
				auth.user.preferred_ai_model = updated.preferred_ai_model;
			}
			openrouterApiKey = '';
			aiSaved = true;
			setTimeout(() => { aiSaved = false; }, 3000);
		} catch (e: any) {
			aiError = e.error || 'Failed to clear OpenRouter key';
		} finally {
			aiSaving = false;
		}
	}

	async function handleDelete() {
		const result = await auth.deleteAccount();
		if (result) {
			deleteError = result;
		} else {
			goto('/login');
		}
	}

	const roleVariant: Record<string, 'success' | 'info' | 'neutral'> = {
		admin: 'success',
		reviewer: 'info',
		member: 'neutral'
	};
</script>

<svelte:head>
	<title>Settings - SortHive</title>
</svelte:head>

<h1 class="mb-6 text-2xl font-bold text-gray-900">Account Settings</h1>

{#if auth.user}
	<div class="max-w-lg space-y-6">
		<!-- Profile Section -->
		<div class="border border-gray-200 bg-white p-6">
			<h2 class="mb-4 font-semibold text-gray-900">Profile</h2>
			<dl class="space-y-3 text-sm">
				<div>
					<dt class="text-gray-500">Display Name</dt>
					<dd>
						{#if editingName}
							<div class="mt-1 flex gap-2">
								<input
									type="text"
									bind:value={displayName}
									class="flex-1 border border-gray-300 px-3 py-1.5 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
								/>
								<button
									onclick={handleSaveName}
									class="bg-blue-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-blue-700"
								>
									Save
								</button>
								<button
									onclick={() => { editingName = false; displayName = auth.user?.display_name ?? ''; }}
									class="border border-gray-300 px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-50"
								>
									Cancel
								</button>
							</div>
							{#if nameError}
								<p class="mt-1 text-xs text-red-600">{nameError}</p>
							{/if}
						{:else}
							<div class="flex items-center gap-2">
								<span class="font-medium text-gray-900">{auth.user.display_name}</span>
								<button
									onclick={() => { editingName = true; displayName = auth.user?.display_name ?? ''; }}
									class="text-xs text-blue-600 hover:text-blue-800"
								>
									Edit
								</button>
								{#if nameSaved}
									<span class="text-xs text-green-600">Saved!</span>
								{/if}
							</div>
						{/if}
					</dd>
				</div>
				<div>
					<dt class="text-gray-500">Email</dt>
					<dd class="font-medium text-gray-900">{auth.user.email}</dd>
				</div>
				<div>
					<dt class="text-gray-500">GitHub</dt>
					<dd class="font-medium text-gray-900">
						{#if auth.user.github_login}
							@{auth.user.github_login}
						{:else}
							<span class="text-gray-400">Not connected</span>
						{/if}
					</dd>
				</div>
				<div>
					<dt class="text-gray-500">Role</dt>
					<dd>
						<Badge text={auth.user.role} variant={roleVariant[auth.user.role] ?? 'neutral'} />
					</dd>
				</div>
				<div>
					<dt class="text-gray-500">Member since</dt>
					<dd class="font-medium text-gray-900">{new Date(auth.user.created_at).toLocaleDateString()}</dd>
				</div>
			</dl>
		</div>

		<!-- Password Section -->
		<div id="password" class="border border-gray-200 bg-white p-6">
			<h2 class="mb-4 font-semibold text-gray-900">{auth.user.has_password ? 'Change Password' : 'Set Password'}</h2>
			{#if !auth.user.has_password}
				<p class="mb-4 text-sm text-gray-600">
					This account currently uses GitHub sign-in only. Set a password if you also want to sign in with email and password.
				</p>
			{/if}
			<form
				class="space-y-3"
				onsubmit={(e) => { e.preventDefault(); handleChangePassword(); }}
			>
				{#if auth.user.has_password}
					<div>
						<label for="current-password" class="block text-sm text-gray-600">Current Password</label>
						<input
							id="current-password"
							type="password"
							bind:value={currentPassword}
							required
							class="mt-1 w-full border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
						/>
					</div>
				{/if}
				<div>
					<label for="new-password" class="block text-sm text-gray-600">{auth.user.has_password ? 'New Password' : 'Password'}</label>
					<input
						id="new-password"
						type="password"
						bind:value={newPassword}
						required
						minlength="8"
						class="mt-1 w-full border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
					/>
				</div>
				<div>
					<label for="confirm-password" class="block text-sm text-gray-600">Confirm Password</label>
					<input
						id="confirm-password"
						type="password"
						bind:value={confirmPassword}
						required
						minlength="8"
						class="mt-1 w-full border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
					/>
				</div>

				{#if passwordError}
					<div class="bg-red-50 p-3 text-sm text-red-700">{passwordError}</div>
				{/if}
				{#if passwordSaved}
					<div class="bg-green-50 p-3 text-sm text-green-700">Password changed successfully!</div>
				{/if}

				<button
					type="submit"
					class="bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700"
				>
					{auth.user.has_password ? 'Change Password' : 'Set Password'}
				</button>
			</form>
		</div>

		<!-- AI Section -->
		<div class="border border-gray-200 bg-white p-6">
			<h2 class="mb-4 font-semibold text-gray-900">AI Assistant</h2>
			<p class="mb-4 text-sm text-gray-600">
				SortHive uses your personal OpenRouter key on the server side for profile-generation prompts, rule suggestions, and assisted edits.
			</p>
			<div class="mb-4 rounded bg-gray-50 p-3 text-sm text-gray-600">
				OpenRouter key:
				<span class="font-medium text-gray-900">
					{auth.user.openrouter_configured ? 'configured' : 'not configured'}
				</span>
			</div>
			<form
				class="space-y-4"
				onsubmit={(e) => { e.preventDefault(); handleSaveAiSettings(); }}
			>
				<div>
					<label for="openrouter-key" class="block text-sm text-gray-600">OpenRouter API Key</label>
					<input
						id="openrouter-key"
						type="password"
						bind:value={openrouterApiKey}
						placeholder={auth.user.openrouter_configured ? 'Leave blank to keep current key' : 'sk-or-v1-...'}
						class="mt-1 w-full border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
					/>
					<p class="mt-1 text-xs text-gray-500">
						The key is stored encrypted and only used by SortHive when you ask for AI help.
					</p>
				</div>

				<div>
					<label for="preferred-model" class="block text-sm text-gray-600">Preferred Model</label>
					<select
						id="preferred-model"
						bind:value={preferredAiModel}
						class="mt-1 w-full border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
					>
						{#each aiModelOptions as model}
							<option value={model}>{model}</option>
						{/each}
					</select>
				</div>

				{#if aiError}
					<div class="bg-red-50 p-3 text-sm text-red-700">{aiError}</div>
				{/if}
				{#if aiSaved}
					<div class="bg-green-50 p-3 text-sm text-green-700">AI settings saved.</div>
				{/if}

				<div class="flex flex-wrap gap-2">
					<button
						type="submit"
						disabled={aiSaving}
						class="bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
					>
						{aiSaving ? 'Saving...' : 'Save AI Settings'}
					</button>
					{#if auth.user.openrouter_configured}
						<button
							type="button"
							onclick={handleClearAiKey}
							disabled={aiSaving}
							class="border border-gray-300 px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-50"
						>
							Remove Key
						</button>
					{/if}
				</div>
			</form>
		</div>

		<!-- Danger Zone -->
		<div class="border border-red-200 bg-white p-6">
			<h2 class="mb-4 font-semibold text-red-900">Danger Zone</h2>
			<p class="mb-4 text-sm text-gray-600">
				Deleting your account will permanently remove all your machines, samples, and reviews.
			</p>
			<button
				onclick={() => { showDeleteModal = true; }}
				class="border border-red-300 px-4 py-2 text-sm font-medium text-red-700 hover:bg-red-50"
			>
				Delete Account
			</button>
		</div>
	</div>
{/if}

<Modal open={showDeleteModal} title="Delete Account" onclose={() => { showDeleteModal = false; }}>
	<div class="space-y-4">
		{#if deleteError}
			<div class="bg-red-50 p-3 text-sm text-red-700">{deleteError}</div>
		{/if}
		<p class="text-sm text-gray-600">
			This will delete all your machines, samples, and data permanently. This action cannot be undone.
		</p>
		<div class="flex gap-2 justify-end">
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
				Delete My Account
			</button>
		</div>
	</div>
</Modal>
