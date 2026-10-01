<script lang="ts">
	import { page } from '$app/state';
	import { onMount } from 'svelte';
	import {
		api,
		getApiBaseUrl,
		type ApiError,
		type Machine,
		type MachineConfigBackupSummary,
		type MachineWithToken
	} from '$lib/api';
	import { auth } from '$lib/auth.svelte';
	import Spinner from '$lib/components/Spinner.svelte';
	import { randomMachineName } from '$lib/machineName';
	import Shuffle from '@lucide/svelte/icons/shuffle';
	import ExternalLink from '@lucide/svelte/icons/external-link';
	import Alert from '$lib/components/Alert.svelte';
	import Button from '$lib/components/Button.svelte';
	import Field from '$lib/components/Field.svelte';
	import Input from '$lib/components/Input.svelte';
	import KeyValue from '$lib/components/KeyValue.svelte';
	import PageHeader from '$lib/components/PageHeader.svelte';
	import Panel from '$lib/components/Panel.svelte';
	import RadioGroup from '$lib/components/RadioGroup.svelte';
	import Select from '$lib/components/Select.svelte';
	import Textarea from '$lib/components/Textarea.svelte';

	type LinkMode = 'existing' | 'new';

	let machineName = $state(page.url.searchParams.get('suggested_machine_name') || randomMachineName());
	let description = $state('');
	let error = $state<string | null>(null);
	let submitting = $state(false);
	let linkMode = $state<LinkMode>(page.url.searchParams.get('intent') === 'restore' ? 'existing' : 'new');
	// Set once the user picks a mode by hand so the async machine load does
	// not flip their choice afterwards.
	let modeTouched = $state(false);
	let machines = $state<Machine[]>([]);
	let machineBackups = $state<Record<string, MachineConfigBackupSummary[]>>({});
	let selectedMachineId = $state('');
	let loadingMachines = $state(false);
	let machineLoadError = $state<string | null>(null);

	const restoreIntent = $derived(page.url.searchParams.get('intent') === 'restore');

	function returnToUrl(): URL | null {
		const raw = page.url.searchParams.get('return_to');
		if (!raw) return null;
		try {
			const parsed = new URL(raw);
			if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') return null;
			return parsed;
		} catch {
			return null;
		}
	}

	function stateToken(): string {
		return page.url.searchParams.get('state') ?? '';
	}

	function targetName(): string {
		return page.url.searchParams.get('target_name') || 'Hive';
	}

	function sorterOrigin(): string | null {
		const raw = page.url.searchParams.get('sorter_origin');
		if (!raw) return null;
		try {
			const parsed = new URL(raw);
			if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') return null;
			return parsed.origin;
		} catch {
			return null;
		}
	}

	function destinationLabel(): string {
		const callback = returnToUrl();
		return callback ? callback.host : 'Unknown sorter';
	}

	function canSubmit(): boolean {
		if (!returnToUrl() || !stateToken()) return false;
		if (linkMode === 'existing') return Boolean(selectedMachineId);
		return Boolean(machineName.trim());
	}

	function hiveApiBaseUrl(): string {
		const apiBaseUrl = getApiBaseUrl();
		if (apiBaseUrl) return apiBaseUrl;
		return window.location.origin;
	}

	function backupCount(machineId: string): number {
		return machineBackups[machineId]?.length ?? 0;
	}

	function selectedMachine(): Machine | null {
		return machines.find((machine) => machine.id === selectedMachineId) ?? null;
	}

	async function loadExistingMachines() {
		loadingMachines = true;
		machineLoadError = null;
		try {
			const list = await api.getMachines({ scope: 'mine' });
			machines = list;
			if (!selectedMachineId && list.length > 0) {
				selectedMachineId = list[0].id;
			}
			// Accounts that already own machines almost always want to
			// reconnect one of them — make that the default for every intent.
			if (list.length > 0 && !modeTouched) {
				linkMode = 'existing';
			}

			if (restoreIntent) {
				const backupEntries = await Promise.all(
					list.map(async (machine) => {
						try {
							const backups = await api.getMachineConfigBackups(machine.id);
							return [machine.id, backups] as const;
						} catch {
							return [machine.id, []] as const;
						}
					})
				);
				const nextBackups = Object.fromEntries(backupEntries);
				machineBackups = nextBackups;
				const firstWithBackups = list.find((machine) => (nextBackups[machine.id]?.length ?? 0) > 0);
				if (firstWithBackups && (!selectedMachineId || backupCount(selectedMachineId) === 0)) {
					selectedMachineId = firstWithBackups.id;
				}
			} else {
				machineBackups = {};
			}
			if (list.length === 0) {
				linkMode = 'new';
			}
		} catch (e) {
			const apiError = e as Partial<ApiError>;
			machineLoadError = apiError.error ?? (e instanceof Error ? e.message : 'Machines could not be loaded.');
			if (machines.length === 0) {
				linkMode = 'new';
			}
		} finally {
			loadingMachines = false;
		}
	}

	onMount(() => {
		void loadExistingMachines();
	});

	async function handleSubmit(e: Event) {
		e.preventDefault();
		if (submitting) return;
		error = null;
		if (!canSubmit()) {
			error = 'The Sorter link request is incomplete. Please start the Hive link again from Sorter.';
			return;
		}

		submitting = true;
		try {
			let machine: MachineWithToken;
			if (linkMode === 'existing') {
				const existing = selectedMachine();
				if (!existing) throw new Error('Choose an existing machine profile.');
				machine = await api.rotateToken(existing.id);
			} else {
				machine = await api.createMachine(
					machineName.trim(),
					description.trim() || undefined
				);
			}
			const callback = returnToUrl();
			if (!callback) throw new Error('The Sorter callback URL is invalid.');

			callback.hash = new URLSearchParams({
				hive_link: '1',
				state: stateToken(),
				api_token: machine.raw_token,
				machine_id: machine.id,
				machine_name: machine.name,
				target_name: targetName(),
				token_prefix: machine.token_prefix,
				api_base_url: hiveApiBaseUrl()
			}).toString();
			window.location.href = callback.toString();
		} catch (e) {
			const apiError = e as Partial<ApiError>;
			error = apiError.error ?? (e instanceof Error ? e.message : 'Machine link failed.');
			submitting = false;
		}
	}
</script>

<svelte:head>
	<title>Link a sorter - Hive</title>
</svelte:head>

<div class="mx-auto flex w-full max-w-2xl flex-col gap-(--gap-panels)">
	<PageHeader
		title={restoreIntent ? 'Restore this sorter from Hive' : 'Connect this sorter to Hive'}
		description={restoreIntent
			? 'Choose one of your machines or make a new one. Hive sends a machine token straight back to the Sorter.'
			: 'Choose one of your machines if this Sorter was registered before, or make a new one. Hive sends the machine token straight back to the Sorter.'}
	/>
	<Panel>
		{#if !returnToUrl() || !stateToken()}
			<Alert tone="danger">This link is incomplete. Go back to the Sorter and start linking again.</Alert>
		{:else}
			<div class="rounded-control bg-well px-4 py-1">
				<KeyValue
					items={[
						{ label: 'Signed in as', value: auth.user?.display_name || auth.user?.email || '' },
						{ label: 'Sends the token to', value: destinationLabel(), mono: true },
						...(sorterOrigin() ? [{ label: 'Started from', value: sorterOrigin() ?? '', mono: true }] : [])
					]}
				/>
			</div>

			<form id="link-form" onsubmit={handleSubmit} class="mt-4 flex flex-col gap-4">
				<RadioGroup
					name="link-mode"
					label="Machine"
					value={linkMode}
					onchange={(mode) => {
						linkMode = mode;
						modeTouched = true;
					}}
					options={[
						{
							value: 'existing',
							label: 'One of my machines',
							help: 'Reconnect this Sorter to a machine already in Hive.',
							disabled: submitting || loadingMachines || machines.length === 0
						},
						{
							value: 'new',
							label: 'A new machine',
							help: 'Start fresh; the Sorter sends its first backup later.',
							disabled: submitting
						}
					]}
				/>

				{#if machineLoadError}<Alert tone="danger">{machineLoadError}</Alert>{/if}

				{#if linkMode === 'existing'}
					{#if loadingMachines}
						<p class="flex items-center gap-2 text-sm text-ink-muted"><Spinner size={14} />Loading your machines</p>
					{:else if machines.length === 0}
						<p class="text-sm text-ink-muted">This account has no machines yet.</p>
					{:else}
						<Field
							label="Machine"
							for="link-machine"
							help="Hive gives this machine a new token; the old one stops working."
						>
							<Select
								id="link-machine"
								bind:value={selectedMachineId}
								disabled={submitting}
								options={machines.map((machine) => ({
									value: machine.id,
									label: machine.name,
									hint: restoreIntent
										? `${backupCount(machine.id)} backup${backupCount(machine.id) === 1 ? '' : 's'}`
										: undefined
								}))}
							/>
						</Field>
					{/if}
				{:else}
					<Field label="Name in Hive" for="machine-name">
						<div class="flex items-center gap-2">
							<Input id="machine-name" class="flex-1" bind:value={machineName} disabled={submitting} />
							<Button icon={Shuffle} disabled={submitting} onclick={() => (machineName = randomMachineName())}
								>New name</Button
							>
						</div>
					</Field>
					<Field label="Description" for="machine-description" help="Optional.">
						<Textarea
							id="machine-description"
							bind:value={description}
							rows={3}
							disabled={submitting}
							placeholder="Where this sorter lives, who looks after it, or what it is for."
						/>
					</Field>
				{/if}

				{#if error}<Alert tone="danger">{error}</Alert>{/if}
			</form>
		{/if}
		{#snippet footer()}
			{#if returnToUrl() && stateToken()}
				<p class="mr-auto text-sm text-ink-muted">
					Confirm only if you trust <span class="font-mono break-all text-ink">{destinationLabel()}</span>.
				</p>
				<Button
					type="submit"
					form="link-form"
					variant="primary"
					icon={ExternalLink}
					loading={submitting}
					disabled={!canSubmit()}>{linkMode === 'existing' ? 'Reconnect machine' : 'Link machine'}</Button
				>
			{/if}
		{/snippet}
	</Panel>
</div>
