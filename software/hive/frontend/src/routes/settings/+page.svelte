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

	// API keys (personal access tokens)
	import type { ApiKeySummary } from '$lib/api';

	let apiKeys = $state<ApiKeySummary[]>([]);
	let apiKeyName = $state('');
	let apiKeysError = $state<string | null>(null);
	let apiKeysLoading = $state(false);
	let apiKeyJustCreated = $state<{ name: string; token: string } | null>(null);

	async function loadApiKeys() {
		try {
			apiKeys = await api.listApiKeys();
		} catch (e: any) {
			apiKeysError = e.error || 'Failed to load API keys';
		}
	}

	async function handleCreateApiKey(event: Event) {
		event.preventDefault();
		apiKeysError = null;
		const name = apiKeyName.trim();
		if (!name) {
			apiKeysError = 'Name is required';
			return;
		}
		apiKeysLoading = true;
		try {
			const resp = await api.createApiKey(name);
			apiKeyJustCreated = { name: resp.summary.name, token: resp.raw_token };
			apiKeyName = '';
			await loadApiKeys();
		} catch (e: any) {
			apiKeysError = e.error || 'Failed to create API key';
		} finally {
			apiKeysLoading = false;
		}
	}

	async function handleRevokeApiKey(id: string) {
		apiKeysError = null;
		if (!confirm('Revoke this API key? This cannot be undone.')) return;
		try {
			await api.revokeApiKey(id);
			await loadApiKeys();
		} catch (e: any) {
			apiKeysError = e.error || 'Failed to revoke';
		}
	}

	function formatDate(iso: string | null) {
		if (!iso) return '—';
		return new Date(iso).toLocaleString(undefined, {
			year: 'numeric',
			month: 'short',
			day: 'numeric',
			hour: '2-digit',
			minute: '2-digit'
		});
	}

	$effect(() => {
		if (auth.user?.role === 'admin') {
			void loadApiKeys();
		}
	});

	// AI / OpenRouter
	let openrouterApiKey = $state('');
	let preferredAiModel = $state(auth.user?.preferred_ai_model ?? 'anthropic/claude-sonnet-4.6');
	let aiError = $state<string | null>(null);
	let aiSaved = $state(false);
	let aiSaving = $state(false);

	// Perceptron (admin-only teacher path that bypasses OpenRouter)
	let perceptronApiKey = $state('');
	let perceptronError = $state<string | null>(null);
	let perceptronSaved = $state(false);
	let perceptronSaving = $state(false);

	// Teacher pipeline defaults — separate from the AI chat model so an admin can choose
	// a vision model (Perceptron, Gemini, etc.) without breaking the chat assistant.
	let teacherModels = $state<{ model_id: string; display_name: string; adapter_kind: string }[]>([]);
	let preferredTeacherModel = $state(auth.user?.preferred_teacher_model ?? '');
	let teacherSettingError = $state<string | null>(null);
	let teacherSettingSaved = $state(false);
	let teacherSettingSaving = $state(false);

	$effect(() => {
		if (auth.user?.role === 'admin') {
			void api
				.listTeacherModels()
				.then((m) => {
					teacherModels = m;
				})
				.catch(() => {
					/* ignore — non-blocking */
				});
		}
	});

	async function handleSaveTeacherModel() {
		teacherSettingError = null;
		teacherSettingSaved = false;
		teacherSettingSaving = true;
		try {
			const updated = await api.updateProfile({
				preferred_teacher_model: preferredTeacherModel || null
			});
			if (auth.user) {
				auth.user.preferred_teacher_model = updated.preferred_teacher_model;
			}
			teacherSettingSaved = true;
			setTimeout(() => { teacherSettingSaved = false; }, 3000);
		} catch (e: any) {
			teacherSettingError = e.error || 'Failed to save teacher model';
		} finally {
			teacherSettingSaving = false;
		}
	}

	const aiModelOptions = [
		'anthropic/claude-haiku-4-5',
		'anthropic/claude-sonnet-4.6',
		'anthropic/claude-sonnet-5',
		'openai/gpt-5.4',
		'google/gemini-3.1-pro-preview',
		'google/gemini-3-flash-preview',
		'google/gemini-3.5-flash'
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

	async function handleSavePerceptronKey() {
		perceptronError = null;
		perceptronSaved = false;
		perceptronSaving = true;
		try {
			const updated = await api.updateProfile({
				perceptron_api_key: perceptronApiKey.trim() || undefined
			});
			if (auth.user) {
				auth.user.perceptron_configured = updated.perceptron_configured;
			}
			perceptronApiKey = '';
			perceptronSaved = true;
			setTimeout(() => { perceptronSaved = false; }, 3000);
		} catch (e: any) {
			perceptronError = e.error || 'Failed to save Perceptron key';
		} finally {
			perceptronSaving = false;
		}
	}

	async function handleClearPerceptronKey() {
		perceptronError = null;
		perceptronSaved = false;
		perceptronSaving = true;
		try {
			const updated = await api.updateProfile({
				clear_perceptron_api_key: true
			});
			if (auth.user) {
				auth.user.perceptron_configured = updated.perceptron_configured;
			}
			perceptronApiKey = '';
			perceptronSaved = true;
			setTimeout(() => { perceptronSaved = false; }, 3000);
		} catch (e: any) {
			perceptronError = e.error || 'Failed to clear Perceptron key';
		} finally {
			perceptronSaving = false;
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
	<title>Settings - Hive</title>
</svelte:head>

<h1 class="mb-6 text-2xl font-bold text-text">Account Settings</h1>

{#if auth.user}
	<div class="max-w-lg space-y-6">
		<!-- Profile Section -->
		<div class="border border-border bg-surface p-6">
			<h2 class="mb-4 font-semibold text-text">Profile</h2>
			<dl class="space-y-3 text-sm">
				<div>
					<dt class="text-text-muted">Display Name</dt>
					<dd>
						{#if editingName}
							<div class="mt-1 flex gap-2">
								<input
									type="text"
									bind:value={displayName}
									class="flex-1 border border-border px-3 py-1.5 text-sm focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"
								/>
								<button
									onclick={handleSaveName}
									class="bg-primary px-3 py-1.5 text-sm font-medium text-white hover:bg-primary-hover"
								>
									Save
								</button>
								<button
									onclick={() => { editingName = false; displayName = auth.user?.display_name ?? ''; }}
									class="border border-border px-3 py-1.5 text-sm font-medium text-text hover:bg-bg"
								>
									Cancel
								</button>
							</div>
							{#if nameError}
								<p class="mt-1 text-xs text-primary">{nameError}</p>
							{/if}
						{:else}
							<div class="flex items-center gap-2">
								<span class="font-medium text-text">{auth.user.display_name}</span>
								<button
									onclick={() => { editingName = true; displayName = auth.user?.display_name ?? ''; }}
									class="text-xs text-primary hover:text-primary-hover"
								>
									Edit
								</button>
								{#if nameSaved}
									<span class="text-xs text-success">Saved!</span>
								{/if}
							</div>
						{/if}
					</dd>
				</div>
				<div>
					<dt class="text-text-muted">Email</dt>
					<dd class="font-medium text-text">{auth.user.email}</dd>
				</div>
				<div>
					<dt class="text-text-muted">GitHub</dt>
					<dd class="font-medium text-text">
						{#if auth.user.github_login}
							@{auth.user.github_login}
						{:else}
							<span class="text-text-muted">Not connected</span>
						{/if}
					</dd>
				</div>
				<div>
					<dt class="text-text-muted">Role</dt>
					<dd>
						<Badge text={auth.user.role} variant={roleVariant[auth.user.role] ?? 'neutral'} />
					</dd>
				</div>
				<div>
					<dt class="text-text-muted">Member since</dt>
					<dd class="font-medium text-text">{new Date(auth.user.created_at).toLocaleDateString()}</dd>
				</div>
			</dl>
		</div>

		<!-- Password Section -->
		<div id="password" class="border border-border bg-surface p-6">
			<h2 class="mb-4 font-semibold text-text">{auth.user.has_password ? 'Change Password' : 'Set Password'}</h2>
			{#if !auth.user.has_password}
				<p class="mb-4 text-sm text-text-muted">
					This account currently uses GitHub sign-in only. Set a password if you also want to sign in with email and password.
				</p>
			{/if}
			<form
				class="space-y-3"
				onsubmit={(e) => { e.preventDefault(); handleChangePassword(); }}
			>
				{#if auth.user.has_password}
					<div>
						<label for="current-password" class="block text-sm text-text-muted">Current Password</label>
						<input
							id="current-password"
							type="password"
							bind:value={currentPassword}
							required
							class="mt-1 w-full border border-border px-3 py-2 text-sm focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"
						/>
					</div>
				{/if}
				<div>
					<label for="new-password" class="block text-sm text-text-muted">{auth.user.has_password ? 'New Password' : 'Password'}</label>
					<input
						id="new-password"
						type="password"
						bind:value={newPassword}
						required
						minlength="8"
						class="mt-1 w-full border border-border px-3 py-2 text-sm focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"
					/>
				</div>
				<div>
					<label for="confirm-password" class="block text-sm text-text-muted">Confirm Password</label>
					<input
						id="confirm-password"
						type="password"
						bind:value={confirmPassword}
						required
						minlength="8"
						class="mt-1 w-full border border-border px-3 py-2 text-sm focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"
					/>
				</div>

				{#if passwordError}
					<div class="bg-primary/8 p-3 text-sm text-primary">{passwordError}</div>
				{/if}
				{#if passwordSaved}
					<div class="bg-success/10 p-3 text-sm text-success">Password changed successfully!</div>
				{/if}

				<button
					type="submit"
					class="bg-primary px-4 py-2 text-sm font-medium text-white hover:bg-primary-hover"
				>
					{auth.user.has_password ? 'Change Password' : 'Set Password'}
				</button>
			</form>
		</div>

		<!-- AI Section -->
		<div class="border border-border bg-surface p-6">
			<h2 class="mb-4 font-semibold text-text">AI Assistant</h2>
			<p class="mb-4 text-sm text-text-muted">
				Hive uses your personal OpenRouter key on the server side for profile-generation prompts, rule suggestions, and assisted edits.
			</p>
			<div class="mb-4 bg-bg p-3 text-sm text-text-muted">
				OpenRouter key:
				<span class="font-medium text-text">
					{auth.user.openrouter_configured ? 'configured' : 'not configured'}
				</span>
			</div>
			<form
				class="space-y-4"
				onsubmit={(e) => { e.preventDefault(); handleSaveAiSettings(); }}
			>
				<div>
					<label for="openrouter-key" class="block text-sm text-text-muted">OpenRouter API Key</label>
					<input
						id="openrouter-key"
						type="password"
						bind:value={openrouterApiKey}
						placeholder={auth.user.openrouter_configured ? 'Leave blank to keep current key' : 'sk-or-v1-...'}
						class="mt-1 w-full border border-border px-3 py-2 text-sm focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"
					/>
					<p class="mt-1 text-xs text-text-muted">
						The key is stored encrypted and only used by Hive when you ask for AI help.
					</p>
				</div>

				<div>
					<label for="preferred-model" class="block text-sm text-text-muted">Preferred Model</label>
					<select
						id="preferred-model"
						bind:value={preferredAiModel}
						class="mt-1 w-full border border-border px-3 py-2 text-sm focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"
					>
						{#each aiModelOptions as model}
							<option value={model}>{model}</option>
						{/each}
					</select>
				</div>

				{#if aiError}
					<div class="bg-primary/8 p-3 text-sm text-primary">{aiError}</div>
				{/if}
				{#if aiSaved}
					<div class="bg-success/10 p-3 text-sm text-success">AI settings saved.</div>
				{/if}

				<div class="flex flex-wrap gap-2">
					<button
						type="submit"
						disabled={aiSaving}
						class="bg-primary px-4 py-2 text-sm font-medium text-white hover:bg-primary-hover disabled:opacity-50"
					>
						{aiSaving ? 'Saving...' : 'Save AI Settings'}
					</button>
					{#if auth.user.openrouter_configured}
						<button
							type="button"
							onclick={handleClearAiKey}
							disabled={aiSaving}
							class="border border-border px-4 py-2 text-sm font-medium text-text hover:bg-bg disabled:opacity-50"
						>
							Remove Key
						</button>
					{/if}
				</div>
			</form>
		</div>

		{#if auth.user.role === 'admin'}
			<!-- Catalog sync dashboard (admin-only dedicated page) -->
			<div class="border border-border bg-white p-6">
				<h2 class="mb-2 font-semibold text-text">Catalog Sync</h2>
				<p class="mb-4 text-sm text-text-muted">
					Sync the Rebrickable parts / categories / colors catalog and BrickLink prices, with
					live progress and resume-after-restart.
				</p>
				<a
					href="/settings/catalog-sync"
					class="inline-flex items-center gap-2 border border-border bg-bg px-4 py-2 text-sm font-medium text-text hover:bg-surface"
				>
					Open Catalog Sync →
				</a>
			</div>

			<!-- Perceptron native API key (teacher-only, admin scope) -->
			<div class="border border-border bg-white p-6">
				<h2 class="mb-4 font-semibold text-text">Perceptron Teacher</h2>
				<p class="mb-4 text-sm text-text-muted">
					Used for the Perceptron Mk1 teacher path, which calls Perceptron's native API
					directly instead of going through OpenRouter. Get a key at
					<a href="https://docs.perceptron.inc" target="_blank" class="text-primary hover:underline">docs.perceptron.inc</a>.
				</p>
				<div class="mb-4 bg-bg p-3 text-sm text-text-muted">
					Perceptron key:
					<span class="font-medium text-text">
						{auth.user.perceptron_configured ? 'configured' : 'not configured'}
					</span>
				</div>
				<form
					class="space-y-4"
					onsubmit={(e) => { e.preventDefault(); handleSavePerceptronKey(); }}
				>
					<div>
						<label for="perceptron-key" class="block text-sm text-text-muted">Perceptron API Key</label>
						<input
							id="perceptron-key"
							type="password"
							bind:value={perceptronApiKey}
							placeholder={auth.user.perceptron_configured ? 'Leave blank to keep current key' : 'pk_...'}
							class="mt-1 w-full border border-border px-3 py-2 text-sm focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"
						/>
						<p class="mt-1 text-xs text-text-muted">
							Stored encrypted. Only used when running Perceptron Mk1 from the teacher compare/re-run flows.
						</p>
					</div>

					{#if perceptronError}
						<div class="bg-primary/8 p-3 text-sm text-primary">{perceptronError}</div>
					{/if}
					{#if perceptronSaved}
						<div class="bg-success/10 p-3 text-sm text-success">Perceptron key saved.</div>
					{/if}

					<div class="flex flex-wrap gap-2">
						<button
							type="submit"
							disabled={perceptronSaving}
							class="bg-primary px-4 py-2 text-sm font-medium text-white hover:bg-primary-hover disabled:opacity-50"
						>
							{perceptronSaving ? 'Saving...' : 'Save Perceptron Key'}
						</button>
						{#if auth.user.perceptron_configured}
							<button
								type="button"
								onclick={handleClearPerceptronKey}
								disabled={perceptronSaving}
								class="border border-border px-4 py-2 text-sm font-medium text-text hover:bg-bg disabled:opacity-50"
							>
								Remove Key
							</button>
						{/if}
					</div>
				</form>
			</div>

			<!-- Default Teacher Model — separate from the AI Assistant chat model -->
			<div class="border border-border bg-white p-6">
				<h2 class="mb-4 font-semibold text-text">Default Teacher Model</h2>
				<p class="mb-4 text-sm text-text-muted">
					Used for re-running the Gemini/Perceptron/etc. teacher across samples. Separate
					from the AI Assistant model above because vision detection and chat assistance use
					different model families.
				</p>
				<form
					class="space-y-4"
					onsubmit={(e) => { e.preventDefault(); handleSaveTeacherModel(); }}
				>
					<div>
						<label for="teacher-model" class="block text-sm text-text-muted">Default Teacher Model</label>
						<select
							id="teacher-model"
							bind:value={preferredTeacherModel}
							class="mt-1 w-full border border-border px-3 py-2 text-sm focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"
						>
							<option value="">— Use system default (Gemini 3 Flash) —</option>
							{#each teacherModels as m (m.model_id)}
								<option value={m.model_id}>{m.display_name} · [{m.adapter_kind}]</option>
							{/each}
						</select>
						<p class="mt-1 text-xs text-text-muted">
							Applies when you click "Re-run teacher" on a sample, start a backfill job, or
							hit Run on the compare page without picking a model.
						</p>
					</div>

					{#if teacherSettingError}
						<div class="bg-primary/8 p-3 text-sm text-primary">{teacherSettingError}</div>
					{/if}
					{#if teacherSettingSaved}
						<div class="bg-success/10 p-3 text-sm text-success">Default teacher model saved.</div>
					{/if}

					<button
						type="submit"
						disabled={teacherSettingSaving}
						class="bg-primary px-4 py-2 text-sm font-medium text-white hover:bg-primary-hover disabled:opacity-50"
					>
						{teacherSettingSaving ? 'Saving...' : 'Save Default Teacher Model'}
					</button>
				</form>
			</div>

			<!-- API keys -->
			<div class="border border-border bg-surface p-6">
				<h2 class="mb-1 font-semibold text-text">Personal Access Tokens</h2>
				<p class="mb-4 text-sm text-text-muted">
					Use a token to authenticate from CLI tools (e.g. the training hub). Tokens inherit your account's permissions — treat them like a password.
				</p>

				{#if apiKeyJustCreated}
					<div class="mb-4 border border-warning/40 bg-warning/[0.06] p-3 text-sm text-text">
						<div class="mb-2 font-semibold">Copy this token now — it won't be shown again.</div>
						<div class="mb-2 text-text-muted">Name: <span class="font-mono">{apiKeyJustCreated.name}</span></div>
						<code class="block select-all break-all bg-bg p-2 font-mono text-xs">{apiKeyJustCreated.token}</code>
						<button
							onclick={() => { apiKeyJustCreated = null; }}
							class="mt-3 border border-border px-3 py-1 text-xs text-text-muted hover:text-text"
							type="button"
						>Dismiss</button>
					</div>
				{/if}

				{#if apiKeysError}
					<div class="mb-4 bg-primary/8 p-3 text-sm text-primary">{apiKeysError}</div>
				{/if}

				<form onsubmit={handleCreateApiKey} class="mb-6 flex flex-wrap items-end gap-2">
					<label class="flex flex-col gap-1 text-xs text-text-muted">
						<span>Token name</span>
						<input
							type="text"
							bind:value={apiKeyName}
							placeholder="e.g. marc-laptop-training"
							class="border border-border bg-bg px-2 py-1 text-sm text-text"
							required
						/>
					</label>
					<button
						type="submit"
						disabled={apiKeysLoading}
						class="bg-primary px-4 py-2 text-sm font-medium text-white hover:bg-primary-hover disabled:opacity-50"
					>
						{apiKeysLoading ? 'Creating...' : 'Create token'}
					</button>
				</form>

				{#if apiKeys.length === 0}
					<p class="text-sm text-text-muted">No tokens yet.</p>
				{:else}
					<div class="border border-border">
						<table class="w-full text-sm">
							<thead class="border-b border-border bg-bg text-left text-xs uppercase tracking-wide text-text-muted">
								<tr>
									<th class="px-3 py-2">Name</th>
									<th class="px-3 py-2">Token</th>
									<th class="px-3 py-2">Created</th>
									<th class="px-3 py-2">Last used</th>
									<th class="px-3 py-2">Status</th>
									<th class="px-3 py-2"></th>
								</tr>
							</thead>
							<tbody>
								{#each apiKeys as key (key.id)}
									<tr class="border-b border-border last:border-b-0">
										<td class="px-3 py-2 font-mono">{key.name}</td>
										<td class="px-3 py-2 font-mono text-xs text-text-muted">{key.token_prefix}…</td>
										<td class="px-3 py-2">{formatDate(key.created_at)}</td>
										<td class="px-3 py-2">{formatDate(key.last_used_at)}</td>
										<td class="px-3 py-2">
											{#if key.revoked_at}
												<span class="text-text-muted">Revoked</span>
											{:else}
												<span class="text-success">Active</span>
											{/if}
										</td>
										<td class="px-3 py-2 text-right">
											{#if !key.revoked_at}
												<button
													onclick={() => handleRevokeApiKey(key.id)}
													class="border border-primary/30 px-2 py-1 text-xs text-primary hover:bg-primary-light"
													type="button"
												>Revoke</button>
											{/if}
										</td>
									</tr>
								{/each}
							</tbody>
						</table>
					</div>
				{/if}
			</div>
		{/if}

		<!-- Danger Zone -->
		<div class="border border-primary/20 bg-surface p-6">
			<h2 class="mb-4 font-semibold text-primary">Danger Zone</h2>
			<p class="mb-4 text-sm text-text-muted">
				Deleting your account will permanently remove all your machines, samples, and reviews.
			</p>
			<button
				onclick={() => { showDeleteModal = true; }}
				class="border border-primary/30 px-4 py-2 text-sm font-medium text-primary hover:bg-primary-light"
			>
				Delete Account
			</button>
		</div>
	</div>
{/if}

<Modal open={showDeleteModal} title="Delete Account" onclose={() => { showDeleteModal = false; }}>
	<div class="space-y-4">
		{#if deleteError}
			<div class="bg-primary/8 p-3 text-sm text-primary">{deleteError}</div>
		{/if}
		<p class="text-sm text-text-muted">
			This will delete all your machines, samples, and data permanently. This action cannot be undone.
		</p>
		<div class="flex gap-2 justify-end">
			<button
				onclick={() => { showDeleteModal = false; }}
				class="border border-border px-4 py-2 text-sm font-medium text-text hover:bg-bg"
			>
				Cancel
			</button>
			<button
				onclick={handleDelete}
				class="bg-primary px-4 py-2 text-sm font-medium text-white hover:bg-primary-hover"
			>
				Delete My Account
			</button>
		</div>
	</div>
</Modal>
