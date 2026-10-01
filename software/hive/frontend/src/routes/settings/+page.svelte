<script lang="ts">
	import { sentence } from '$lib/text';
	import { auth } from '$lib/auth.svelte';
	import { api, getApiBaseUrl, type AiModelCatalog, type AuthOptions, type Machine, type UserIdentitySummary } from '$lib/api';
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import Modal from '$lib/components/Modal.svelte';
	import Alert from '$lib/components/Alert.svelte';
	import Button from '$lib/components/Button.svelte';
	import Checkbox from '$lib/components/Checkbox.svelte';
	import CopyField from '$lib/components/CopyField.svelte';
	import Field from '$lib/components/Field.svelte';
	import Input from '$lib/components/Input.svelte';
	import PageHeader from '$lib/components/PageHeader.svelte';
	import Panel from '$lib/components/Panel.svelte';
	import Select from '$lib/components/Select.svelte';
	import SettingRow from '$lib/components/SettingRow.svelte';
	import SegmentedControl from '$lib/components/SegmentedControl.svelte';
	import { theme, type Theme } from '$lib/stores/theme';
	import ArrowRight from '@lucide/svelte/icons/arrow-right';
	import Moon from '@lucide/svelte/icons/moon';
	import Pencil from '@lucide/svelte/icons/pencil';
	import Plus from '@lucide/svelte/icons/plus';
	import Sun from '@lucide/svelte/icons/sun';
	import Trash2 from '@lucide/svelte/icons/trash-2';
	import Badge from '$lib/components/Badge.svelte';
	import ModelSelect from '$lib/components/ModelSelect.svelte';
	import AiUsagePanel from '$lib/components/AiUsagePanel.svelte';
	import BrandMark from '$lib/components/BrandMark.svelte';
	import Check from '@lucide/svelte/icons/check';
	import KeyRound from '@lucide/svelte/icons/key-round';
	import ArrowUpRight from '@lucide/svelte/icons/arrow-up-right';

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

	// Connected accounts (OAuth identities)
	const OAUTH_PROVIDER_LABELS: Record<string, string> = { github: 'GitHub', discord: 'Discord' };
	let identities = $state<UserIdentitySummary[]>([]);
	let authOptions = $state<AuthOptions | null>(null);
	// Link-flow failures land back here as /settings?error=...
	let identitiesError = $state<string | null>(page.url.searchParams.get('error'));

	// balloon's Discord "Claim your machine" button points at
	// /settings?link=discord so a fresh visitor lands straight on a focused
	// "connect Discord" modal instead of a long settings page.
	let linkModalOpen = $state(page.url.searchParams.get('link') === 'discord');

	function closeLinkModal() {
		linkModalOpen = false;
	}

	async function loadIdentities() {
		try {
			identities = await api.listIdentities();
		} catch {
			/* non-blocking */
		}
	}

	$effect(() => {
		if (auth.user) {
			void loadIdentities();
			void api
				.authOptions()
				.then((o) => {
					authOptions = o;
				})
				.catch(() => {
					authOptions = null;
				});
		}
	});

	function identityFor(provider: string): UserIdentitySummary | undefined {
		return identities.find((i) => i.provider === provider);
	}

	const discordIdentity = $derived(identityFor('discord'));

	function providerEnabled(provider: string): boolean {
		if (!authOptions) return false;
		return provider === 'github' ? authOptions.github_enabled : authOptions.discord_enabled;
	}

	// What the confirmation dialog asks, and what its button then does.
	let pendingConfirm = $state<{ title: string; text: string; action: string; run: () => Promise<void> } | null>(null);
	let confirming = $state(false);

	async function runConfirmed() {
		if (!pendingConfirm) return;
		confirming = true;
		await pendingConfirm.run();
		confirming = false;
		pendingConfirm = null;
	}

	function handleUnlink(provider: 'github' | 'discord') {
		identitiesError = null;
		const name = OAUTH_PROVIDER_LABELS[provider];
		pendingConfirm = {
			title: `Disconnect ${name}?`,
			text: `You can no longer sign in with ${name} until you connect it again.`,
			action: 'Disconnect',
			run: async () => {
				try {
					await api.unlinkIdentity(provider);
					await loadIdentities();
				} catch (e: any) {
					identitiesError = e.error || 'Failed to disconnect';
				}
			}
		};
	}

	// API keys (personal access tokens)
	import type { ApiKeySummary } from '$lib/api';

	let apiKeys = $state<ApiKeySummary[]>([]);
	let apiKeyName = $state('');
	let apiKeysError = $state<string | null>(null);
	let apiKeysLoading = $state(false);
	// A new key is shown once, in a dialog, and forgotten when it closes.
	let apiKeyJustCreated = $state<{ name: string; token: string } | null>(null);
	let apiKeyShown = $state(false);

	// The scopes a key can have. Anyone can make a key with the first three
	// (an assistant working on their own profiles, kits and records); the rest
	// reach fleet-wide or server data and stay with admins.
	const API_KEY_SCOPES: { scope: string; label: string; everyone?: boolean }[] = [
		{ scope: 'profiles:read', label: 'Read your sorting profiles and kits', everyone: true },
		{ scope: 'profiles:write', label: 'Change your sorting profiles and kits', everyone: true },
		{ scope: 'records:read', label: 'Read what your machines sorted', everyone: true },
		{ scope: 'models:read', label: 'Read models' },
		{ scope: 'models:write', label: 'Write models' },
		{ scope: 'samples:read', label: 'Read samples' },
		{ scope: 'samples:write', label: 'Write samples' },
		{ scope: 'keys:manage', label: 'Manage API keys' },
		{ scope: 'stats:read', label: 'Read aggregate stats' },
		{ scope: 'fleet:read', label: 'Read the fleet roster (machines + linked owners)' },
		{ scope: 'fleet:anon', label: 'Read the de-identified fleet roster (no owners, no names)' },
		{ scope: 'contributors:read', label: 'Read the contributor leaderboard' },
		{ scope: 'parts:read', label: 'Read the parts catalog' },
		{ scope: 'parts:prices', label: 'Read parts market prices' },
		{ scope: 'server_health:read', label: 'Read server health (storage, DB size, memory)' }
	];
	const visibleScopes = $derived(
		auth.user?.role === 'admin' ? API_KEY_SCOPES : API_KEY_SCOPES.filter((s) => s.everyone)
	);
	let apiKeySelectedScopes = $state<string[]>([]);
	let apiKeyExpiresInDays = $state('');
	let apiKeyMachines = $state<Machine[]>([]);
	let apiKeySelectedMachines = $state<string[]>([]);

	function toggleApiKeyScope(scope: string) {
		apiKeySelectedScopes = apiKeySelectedScopes.includes(scope)
			? apiKeySelectedScopes.filter((s) => s !== scope)
			: [...apiKeySelectedScopes, scope];
	}

	function toggleApiKeyMachine(id: string) {
		apiKeySelectedMachines = apiKeySelectedMachines.includes(id)
			? apiKeySelectedMachines.filter((m) => m !== id)
			: [...apiKeySelectedMachines, id];
	}

	function machineName(id: string): string {
		return apiKeyMachines.find((m) => m.id === id)?.name ?? `${id.slice(0, 8)}...`;
	}

	async function loadApiKeys() {
		try {
			apiKeys = await api.listApiKeys();
		} catch (e: any) {
			apiKeysError = e.error || 'Failed to load API keys';
		}
	}

	async function handleCreateApiKey(event: Event) {
		event.preventDefault();
		if (apiKeysLoading) return;
		apiKeysError = null;
		const name = apiKeyName.trim();
		if (!name) {
			apiKeysError = 'Name is required';
			return;
		}
		if (apiKeySelectedScopes.length === 0) {
			apiKeysError = 'Select at least one scope';
			return;
		}
		const expiresRaw = apiKeyExpiresInDays.trim();
		let expiresInDays: number | undefined;
		if (expiresRaw) {
			expiresInDays = Number(expiresRaw);
			if (!Number.isInteger(expiresInDays) || expiresInDays < 1 || expiresInDays > 3650) {
				apiKeysError = 'Expiry must be a whole number of days (1 to 3650)';
				return;
			}
		}
		apiKeysLoading = true;
		try {
			const resp = await api.createApiKey(
				name,
				apiKeySelectedScopes,
				expiresInDays,
				apiKeySelectedMachines.length > 0 ? apiKeySelectedMachines : undefined
			);
			apiKeyJustCreated = { name: resp.summary.name, token: resp.raw_token };
			apiKeyShown = true;
			apiKeyName = '';
			apiKeySelectedScopes = [];
			apiKeyExpiresInDays = '';
			apiKeySelectedMachines = [];
			await loadApiKeys();
		} catch (e: any) {
			apiKeysError = e.error || 'Failed to create API key';
		} finally {
			apiKeysLoading = false;
		}
	}

	function handleRevokeApiKey(id: string) {
		apiKeysError = null;
		pendingConfirm = {
			title: 'Revoke this key?',
			text: 'Anything that uses it stops working at once. It cannot be undone.',
			action: 'Revoke',
			run: async () => {
				try {
					await api.revokeApiKey(id);
					await loadApiKeys();
				} catch (e: any) {
					apiKeysError = e.error || 'Failed to revoke';
				}
			}
		};
	}

	// Connect an assistant: one key with the three scopes an assistant needs.
	const ASSISTANT_SCOPES = ['profiles:read', 'profiles:write', 'records:read'];
	let assistantKey = $state<{ name: string; token: string } | null>(null);
	let assistantShown = $state(false);
	let assistantBusy = $state(false);
	let assistantError = $state<string | null>(null);

	// Where an assistant reads its instructions: this Hive's own address.
	const skillUrl = $derived(`${getApiBaseUrl() || page.url.origin}/api/agent/skill.md`);
	const assistantMessage = $derived(
		assistantKey ? `Use the Hive sorting-profiles skill at ${skillUrl}. My API key is ${assistantKey.token}.` : ''
	);

	// "Assistant", or the next free "Assistant 2" when one is in use, so a
	// version's origin ("saved by Assistant 2") says which one made it.
	function assistantName(): string {
		const taken = new Set(apiKeys.filter((k) => !k.revoked_at).map((k) => k.name));
		if (!taken.has('Assistant')) return 'Assistant';
		let n = 2;
		while (taken.has(`Assistant ${n}`)) n++;
		return `Assistant ${n}`;
	}

	async function connectAssistant() {
		if (assistantBusy) return;
		assistantBusy = true;
		assistantError = null;
		try {
			const resp = await api.createApiKey(assistantName(), ASSISTANT_SCOPES);
			assistantKey = { name: resp.summary.name, token: resp.raw_token };
			assistantShown = true;
			await loadApiKeys();
		} catch (e: any) {
			assistantError = e.error || 'Could not make the key';
		} finally {
			assistantBusy = false;
		}
	}

	// The keys list only has a machines column when some key is limited to machines.
	const keysHaveMachines = $derived(apiKeys.some((key) => key.machine_ids?.length));

	function formatDay(iso: string) {
		return new Date(iso).toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' });
	}

	function formatDate(iso: string | null) {
		if (!iso) return '-';
		return new Date(iso).toLocaleString(undefined, {
			year: 'numeric',
			month: 'short',
			day: 'numeric',
			hour: '2-digit',
			minute: '2-digit'
		});
	}

	$effect(() => {
		if (auth.user) {
			void loadApiKeys();
			void api
				.getMachines({ scope: 'mine' })
				.then((m) => {
					apiKeyMachines = m;
				})
				.catch(() => {
					apiKeyMachines = [];
				});
		}
	});

	// AI / OpenRouter
	let openrouterApiKey = $state('');
	let preferredAiModel = $state(auth.user?.preferred_ai_model ?? '');
	let aiError = $state<string | null>(null);
	let aiSaved = $state(false);
	let aiSaving = $state(false);
	let aiCatalog = $state<AiModelCatalog | null>(null);

	$effect(() => {
		void (async () => {
			try {
				const catalog = await api.listAiModels();
				aiCatalog = catalog;
				if (!preferredAiModel) preferredAiModel = catalog.default_model;
			} catch {
				aiCatalog = null;
			}
		})();
	});

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
		if (teacherSettingSaving) return;
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
		if (aiSaving) return;
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
		if (perceptronSaving) return;
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

{#if auth.user}
	<div class="mx-auto flex w-full max-w-4xl flex-col gap-(--gap-panels)">
		<PageHeader title="Account settings" />

		<Panel title="Profile" flush>
			<div class="divide-y divide-line">
				<SettingRow label="Display name">
					{#if editingName}
						<div class="flex flex-wrap items-center gap-2">
							<Input size="sm" class="w-48" bind:value={displayName} />
							<Button
								size="sm"
								variant="ghost"
								onclick={() => {
									editingName = false;
									displayName = auth.user?.display_name ?? '';
								}}>Cancel</Button
							>
							<Button size="sm" variant="primary" onclick={handleSaveName}>Save</Button>
						</div>
					{:else}
						<span class="text-sm font-medium text-ink">{auth.user.display_name}</span>
						{#if nameSaved}<Badge tone="success">Saved</Badge>{/if}
						<Button
							size="sm"
							variant="ghost"
							icon={Pencil}
							label="Edit the display name"
							onclick={() => {
								editingName = true;
								displayName = auth.user?.display_name ?? '';
							}}
						/>
					{/if}
				</SettingRow>
				{#if nameError}
					<div class="px-(--pad-panel) py-3"><Alert tone="danger">{nameError}</Alert></div>
				{/if}
				<SettingRow label="Email">
					<span class="text-sm break-all text-ink">{auth.user.email}</span>
				</SettingRow>
				<SettingRow label="GitHub">
					<span class="text-sm {auth.user.github_login ? 'text-ink' : 'text-ink-muted'}"
						>{auth.user.github_login ? `@${auth.user.github_login}` : 'Not connected'}</span
					>
				</SettingRow>
				<SettingRow label="Role">
					<Badge tone={roleVariant[auth.user.role] ?? 'neutral'}>{sentence(auth.user.role)}</Badge>
				</SettingRow>
				<SettingRow label="Member since">
					<span class="text-sm text-ink">{new Date(auth.user.created_at).toLocaleDateString()}</span>
				</SettingRow>
			</div>
		</Panel>

		<Panel title="Appearance" flush>
			<div class="divide-y divide-line">
				<SettingRow label="Theme" help="Applies at once, on this browser.">
					<SegmentedControl
						label="Theme"
						size="sm"
						value={$theme}
						onchange={(mode: Theme) => theme.setTheme(mode)}
						options={[
							{ value: 'light', label: 'Light', icon: Sun },
							{ value: 'dark', label: 'Dark', icon: Moon }
						]}
					/>
				</SettingRow>
			</div>
		</Panel>

		<div id="password" class="scroll-mt-16">
			<Panel
				title={auth.user.has_password ? 'Change password' : 'Set a password'}
				description={auth.user.has_password
					? undefined
					: 'This account signs in with GitHub only. Set a password to sign in with your email too.'}
			>
				<form
					id="password-form"
					class="flex max-w-md flex-col gap-4"
					onsubmit={(e) => {
						e.preventDefault();
						handleChangePassword();
					}}
				>
					{#if auth.user.has_password}
						<Field label="Current password" for="current-password">
							<Input id="current-password" type="password" bind:value={currentPassword} />
						</Field>
					{/if}
					<Field
						label={auth.user.has_password ? 'New password' : 'Password'}
						for="new-password"
						help="At least 8 characters."
					>
						<Input id="new-password" type="password" bind:value={newPassword} />
					</Field>
					<Field label="Confirm the password" for="confirm-password">
						<Input id="confirm-password" type="password" bind:value={confirmPassword} />
					</Field>
					{#if passwordError}<Alert tone="danger">{passwordError}</Alert>{/if}
					{#if passwordSaved}<Alert tone="success">Password changed.</Alert>{/if}
				</form>
				{#snippet footer()}
					<Button type="submit" form="password-form" variant="primary"
						>{auth.user?.has_password ? 'Change password' : 'Set password'}</Button
					>
				{/snippet}
			</Panel>
		</div>

		{#if identities.length > 0 || providerEnabled('github') || providerEnabled('discord')}
			<!-- The id is a deep link into this panel that older links still use; a
			     Discord bot's "Claim your machine" points at /settings?link=discord,
			     which opens the Connect Discord dialog below instead. -->
			<div id="connected-accounts" class="scroll-mt-16">
				<Panel
					title="Connected accounts"
					description="Other ways to sign in to this account. A connected Discord account also verifies you on the community server."
					flush
				>
					{#if identitiesError}
						<div class="px-(--pad-panel) pb-3"><Alert tone="danger">{identitiesError}</Alert></div>
					{/if}
					<ul class="divide-y divide-line">
						{#each ['github', 'discord'] as const as provider (provider)}
							{@const linked = identityFor(provider)}
							{#if linked || providerEnabled(provider)}
								<li class="flex items-center justify-between gap-3 px-(--pad-panel) py-3">
									<span class="flex min-w-0 items-center gap-3">
										<BrandMark brand={provider} size={20} />
										{#if linked?.avatar_url}
											<img src={linked.avatar_url} alt="" class="size-6 rounded-full" />
										{/if}
										<span class="min-w-0">
											<span class="block text-sm font-medium text-ink">{OAUTH_PROVIDER_LABELS[provider]}</span>
											<span class="block truncate text-sm text-ink-muted"
												>{linked
													? `Connected${linked.provider_login ? ` as ${linked.provider_login}` : ''}`
													: 'Not connected'}</span
											>
										</span>
									</span>
									{#if linked}
										<Button size="sm" onclick={() => handleUnlink(provider)}>Disconnect</Button>
									{:else}
										<Button size="sm" href={api.oauthLinkUrl(provider)} icon={Plus}>Connect</Button>
									{/if}
								</li>
							{/if}
						{/each}
					</ul>
				</Panel>
			</div>
		{/if}

		<Panel
			title="AI assistant"
			description="Hive uses your own OpenRouter key, on the server, for building profiles, suggesting rules and helping with edits."
		>
			<form
				id="ai-form"
				class="flex flex-col gap-4"
				onsubmit={(e) => {
					e.preventDefault();
					handleSaveAiSettings();
				}}
			>
				<Field
					label="OpenRouter key"
					for="openrouter-key"
					help="Stored encrypted, and used only when you ask for help."
				>
					<div class="flex items-center gap-2">
						<Input
							id="openrouter-key"
							type="password"
							class="flex-1"
							bind:value={openrouterApiKey}
							placeholder={auth.user.openrouter_configured ? 'Leave blank to keep the saved key' : 'sk-or-v1-...'}
						/>
						<Badge tone={auth.user.openrouter_configured ? 'success' : 'neutral'} dot
							>{auth.user.openrouter_configured ? 'Saved' : 'None'}</Badge
						>
					</div>
				</Field>
				<Field
					label="Model"
					for="preferred-model"
					help={aiCatalog ? undefined : "The model list didn't load; type an OpenRouter model id."}
				>
					{#if aiCatalog}
						<ModelSelect
							id="preferred-model"
							bind:value={preferredAiModel}
							groups={aiCatalog.groups}
							baselineModel={aiCatalog.baseline_model}
						/>
					{:else}
						<Input id="preferred-model" bind:value={preferredAiModel} placeholder="OpenRouter model id" />
					{/if}
				</Field>
				<AiUsagePanel />
				{#if aiError}<Alert tone="danger">{aiError}</Alert>{/if}
				{#if aiSaved}<Alert tone="success">AI settings saved.</Alert>{/if}
			</form>
			{#snippet footer()}
				{#if auth.user?.openrouter_configured}
					<Button variant="ghost" disabled={aiSaving} onclick={handleClearAiKey}>Remove the key</Button>
				{/if}
				<Button type="submit" form="ai-form" variant="primary" loading={aiSaving}>Save</Button>
			{/snippet}
		</Panel>

		{#snippet connectFooter()}
			<a
				href={skillUrl}
				target="_blank"
				rel="noopener noreferrer"
				class="mr-auto inline-flex items-center gap-1 text-sm text-primary-ink hover:underline"
				>What the assistant reads<ArrowUpRight size={14} /></a
			>
			<Button variant="primary" icon={KeyRound} loading={assistantBusy} onclick={() => void connectAssistant()}
				>Make a key</Button
			>
		{/snippet}

		<Panel
			title="Connect an assistant"
			description="Let an AI assistant you already use make and change your sorting profiles and kits."
			footer={connectFooter}
		>
			<div class="flex flex-col gap-3">
				<ul class="flex flex-col gap-2 text-sm text-ink" aria-label="What the key can do">
					<li class="flex items-center gap-2">
						<Check size={16} class="shrink-0" />Read and change your sorting profiles and kits
					</li>
					<li class="flex items-center gap-2">
						<Check size={16} class="shrink-0" />Read what your machines sorted
					</li>
				</ul>
				<p class="text-sm text-ink-muted">It cannot run your machines, and you can revoke it at any time.</p>
				{#if assistantError}<Alert tone="danger">{assistantError}</Alert>{/if}
			</div>
		</Panel>

		<Panel
			title="API keys"
			description="A key signs in command line tools, bots and agents. It can do only what its scopes allow: grant the least it needs, and keep it like a password."
			flush
		>
			<div class="flex flex-col gap-4 px-(--pad-panel) pb-(--pad-panel)">
				{#if apiKeysError}<Alert tone="danger">{apiKeysError}</Alert>{/if}

				<form onsubmit={handleCreateApiKey} class="flex flex-col gap-4 rounded-control bg-well p-4">
					<div class="flex flex-wrap items-end gap-3">
						<Field label="Name" for="token-name" class="w-full sm:w-72">
							<Input id="token-name" bind:value={apiKeyName} placeholder="For example: training laptop" />
						</Field>
						<Field label="Expires in days" for="token-expiry" class="w-36">
							<Input id="token-expiry" bind:value={apiKeyExpiresInDays} placeholder="Never" />
						</Field>
						<Button type="submit" variant="primary" icon={Plus} loading={apiKeysLoading}>Create key</Button>
					</div>
					<div class="grid gap-4 lg:grid-cols-2">
						<fieldset class="flex flex-col gap-2">
							<legend class="mb-2 text-sm font-medium text-ink">Scopes, at least one</legend>
							{#each visibleScopes as { scope, label } (scope)}
								<Checkbox
									checked={apiKeySelectedScopes.includes(scope)}
									onchange={() => toggleApiKeyScope(scope)}
									><span class="font-mono">{scope}</span> <span class="text-ink-muted">{label}</span></Checkbox
								>
							{/each}
						</fieldset>
						{#if apiKeyMachines.length > 0}
							<fieldset class="flex flex-col gap-2">
								<legend class="mb-2 text-sm font-medium text-ink"
									>Only these machines <span class="font-normal text-ink-muted">(none chosen means all you can reach)</span></legend
								>
								{#each apiKeyMachines as machine (machine.id)}
									<Checkbox
										checked={apiKeySelectedMachines.includes(machine.id)}
										onchange={() => toggleApiKeyMachine(machine.id)}>{machine.name}</Checkbox
									>
								{/each}
							</fieldset>
						{/if}
					</div>
				</form>
			</div>

			{#if apiKeys.length === 0}
				<p class="border-t border-line px-(--pad-panel) py-3 text-sm text-ink-muted">No keys yet.</p>
			{:else}
				<div class="overflow-x-auto border-t border-line">
					<table class="data-table min-w-[44rem]">
						<thead>
							<tr>
								<th>Key</th><th>Scopes</th>{#if keysHaveMachines}<th>Machines</th>{/if}<th>Last used</th><th>Status</th
								><th aria-label="Actions"></th>
							</tr>
						</thead>
						<tbody>
							{#each apiKeys as key (key.id)}
								<tr>
									<td>
										<div class="font-mono">{key.name}</div>
										<div class="font-mono whitespace-nowrap text-ink-muted">{key.token_prefix}...</div>
									</td>
									<td>
										{#if key.scopes?.length}
											<div class="flex flex-wrap gap-1">
												{#each key.scopes as scope (scope)}<Badge><span class="font-mono">{scope}</span></Badge>{/each}
											</div>
										{:else}
											<span class="text-ink-muted">-</span>
										{/if}
									</td>
									{#if keysHaveMachines}
										<td class="text-ink-muted"
											>{key.machine_ids?.length ? key.machine_ids.map(machineName).join(', ') : 'All'}</td
										>
									{/if}
									<td class="whitespace-nowrap">
										<div class={key.last_used_at ? '' : 'text-ink-muted'}>
											{key.last_used_at ? formatDate(key.last_used_at) : 'Never used'}
										</div>
										<div class="text-ink-muted">Made {formatDay(key.created_at)}</div>
									</td>
									<td class="whitespace-nowrap">
										{#if key.revoked_at}
											<Badge>Revoked</Badge>
										{:else if key.expires_at && new Date(key.expires_at) <= new Date()}
											<Badge tone="warning">Expired</Badge>
										{:else}
											<Badge tone="success">Active</Badge>
										{/if}
										{#if key.expires_at && !key.revoked_at}
											<div class="text-ink-muted">Expires {formatDay(key.expires_at)}</div>
										{/if}
									</td>
									<td class="text-right">
										{#if !key.revoked_at}
											<Button size="sm" variant="ghost" onclick={() => handleRevokeApiKey(key.id)}>Revoke</Button>
										{/if}
									</td>
								</tr>
							{/each}
						</tbody>
					</table>
				</div>
			{/if}
		</Panel>

		{#if auth.user.role === 'admin'}
			<Panel title="Catalog sync">
				{#snippet actions()}
					<Button href="/settings/catalog-sync" icon={ArrowRight}>Open catalog sync</Button>
				{/snippet}
				<p class="text-sm text-ink-muted">
					Sync the Rebrickable parts, categories and colors and the BrickLink prices, with live progress and resume
					after a restart.
				</p>
			</Panel>

			<Panel title="Perceptron teacher">
				{#snippet actions()}
					<Badge tone={auth.user?.perceptron_configured ? 'success' : 'neutral'} dot
						>{auth.user?.perceptron_configured ? 'Key saved' : 'No key'}</Badge
					>
				{/snippet}
				<p class="mb-4 text-sm text-ink-muted">
					For the Perceptron Mk1 teacher, which calls Perceptron's own API instead of going through OpenRouter.
					Get a key at <a href="https://docs.perceptron.inc" target="_blank" rel="noopener noreferrer" class="text-primary-ink hover:underline"
						>docs.perceptron.inc</a
					>.
				</p>
				<form
					id="perceptron-form"
					class="flex flex-col gap-4"
					onsubmit={(e) => {
						e.preventDefault();
						handleSavePerceptronKey();
					}}
				>
					<Field
						label="Perceptron key"
						for="perceptron-key"
						help="Stored encrypted, and used only when you run Perceptron Mk1 to compare or re-run a teacher."
					>
						<Input
							id="perceptron-key"
							type="password"
							bind:value={perceptronApiKey}
							placeholder={auth.user.perceptron_configured ? 'Leave blank to keep the saved key' : 'pk_...'}
						/>
					</Field>
					{#if perceptronError}<Alert tone="danger">{perceptronError}</Alert>{/if}
					{#if perceptronSaved}<Alert tone="success">Perceptron key saved.</Alert>{/if}
				</form>
				{#snippet footer()}
					{#if auth.user?.perceptron_configured}
						<Button variant="ghost" disabled={perceptronSaving} onclick={handleClearPerceptronKey}>Remove the key</Button>
					{/if}
					<Button type="submit" form="perceptron-form" variant="primary" loading={perceptronSaving}>Save</Button>
				{/snippet}
			</Panel>

			<Panel
				title="Default teacher model"
				description="For re-running a teacher (Gemini, Perceptron and others) over samples. Separate from the assistant's model, because finding pieces and chatting use different kinds of model."
			>
				<form
					id="teacher-form"
					onsubmit={(e) => {
						e.preventDefault();
						handleSaveTeacherModel();
					}}
					class="flex flex-col gap-4"
				>
					<Field
						label="Teacher model"
						for="teacher-model"
						help="Used when you re-run the teacher on a sample, start a backfill, or run a comparison without choosing a model."
					>
						<Select
							id="teacher-model"
							bind:value={preferredTeacherModel}
							options={[
								{ value: '', label: 'The system default (Gemini 3 Flash)' },
								...teacherModels.map((m) => ({ value: m.model_id, label: m.display_name, hint: m.adapter_kind }))
							]}
						/>
					</Field>
					{#if teacherSettingError}<Alert tone="danger">{teacherSettingError}</Alert>{/if}
					{#if teacherSettingSaved}<Alert tone="success">Default teacher model saved.</Alert>{/if}
				</form>
				{#snippet footer()}
					<Button type="submit" form="teacher-form" variant="primary" loading={teacherSettingSaving}>Save</Button>
				{/snippet}
			</Panel>
		{/if}

		<Panel title="Delete your account">
			{#snippet actions()}
				<Button icon={Trash2} onclick={() => (showDeleteModal = true)}>Delete account</Button>
			{/snippet}
			<p class="text-sm text-ink-muted">This removes your machines, samples and reviews for good.</p>
		</Panel>
	</div>
{/if}

<Modal open={pendingConfirm !== null} title={pendingConfirm?.title ?? ''} size="sm" onclose={() => (pendingConfirm = null)}>
	<p class="text-sm text-ink">{pendingConfirm?.text}</p>
	{#snippet footer()}
		<Button variant="ghost" onclick={() => (pendingConfirm = null)}>Cancel</Button>
		<Button variant="danger" loading={confirming} onclick={runConfirmed}>{pendingConfirm?.action}</Button>
	{/snippet}
</Modal>

<!-- The dialogs that show something to copy are wide, so an address or a key fits on a line of its own. -->
<Modal bind:open={assistantShown} title="Connect an assistant" size="lg" onclose={() => (assistantKey = null)}>
	{#if assistantKey}
		<CopyField
			label="Paste this into your assistant"
			name="message"
			value={assistantMessage}
			note={`Hive shows this key only now. It is listed under API keys as “${assistantKey.name}”, where you can revoke it.`}
		>
			Use the Hive sorting-profiles skill at <span class="font-mono">{skillUrl}</span>. My API key is
			<span class="font-mono">{assistantKey.token}</span>.
		</CopyField>
	{/if}
	{#snippet footer()}
		<Button onclick={() => (assistantShown = false)}>Done</Button>
	{/snippet}
</Modal>

<Modal bind:open={apiKeyShown} title="New API key" size="lg" onclose={() => (apiKeyJustCreated = null)}>
	{#if apiKeyJustCreated}
		<CopyField
			label={apiKeyJustCreated.name}
			name="API key"
			value={apiKeyJustCreated.token}
			mono
			note="Hive shows a key only when it is made. Keep it like a password."
		/>
	{/if}
	{#snippet footer()}
		<Button onclick={() => (apiKeyShown = false)}>Done</Button>
	{/snippet}
</Modal>

<Modal bind:open={showDeleteModal} title="Delete your account" size="sm">
	{#if deleteError}<Alert tone="danger" class="mb-3">{deleteError}</Alert>{/if}
	<p class="text-sm text-ink-muted">This deletes all your machines, samples and data. It cannot be undone.</p>
	{#snippet footer()}
		<Button variant="ghost" onclick={() => (showDeleteModal = false)}>Cancel</Button>
		<Button variant="danger" onclick={handleDelete}>Delete my account</Button>
	{/snippet}
</Modal>

<Modal
	open={linkModalOpen}
	title={discordIdentity ? 'Discord connected' : 'Connect Discord'}
	size="sm"
	onclose={closeLinkModal}
>
	{#if discordIdentity}
		<p class="text-sm text-ink">
			Your Discord account{discordIdentity.provider_login ? ` @${discordIdentity.provider_login}` : ''} is already connected.
		</p>
	{:else if providerEnabled('discord')}
		<p class="text-sm text-ink-muted">
			Connecting Discord verifies you on the community server, and credits the machines you register to you there.
		</p>
	{:else}
		<p class="text-sm text-ink-muted">Discord sign-in isn't set up on this Hive.</p>
	{/if}
	{#snippet footer()}
		{#if !discordIdentity && providerEnabled('discord')}
			<Button variant="ghost" onclick={closeLinkModal}>Not now</Button>
			<Button variant="primary" href={api.oauthLinkUrl('discord', '/settings?link=discord')}>
				<BrandMark brand="discord" size={16} />Connect Discord
			</Button>
		{:else}
			<Button variant="primary" onclick={closeLinkModal}>Done</Button>
		{/if}
	{/snippet}
</Modal>
