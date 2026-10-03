<script lang="ts">
	import ExternalLink from '@lucide/svelte/icons/external-link';
	import Spinner from '$lib/components/ui/Spinner.svelte';
	import Alert from '$lib/components/ui/Alert.svelte';
	import Button from '$lib/components/ui/Button.svelte';
	import Field from '$lib/components/ui/Field.svelte';
	import Input from '$lib/components/ui/Input.svelte';
	import KeyValue from '$lib/components/ui/KeyValue.svelte';
	import Panel from '$lib/components/ui/Panel.svelte';

	type HiveSetupTarget = {
		id: string;
		name: string;
		url: string;
		machine_id: string | null;
		enabled: boolean;
	};

	let {
		hiveLoading,
		officialHiveTarget,
		defaultHiveUrl,
		hiveUrl = $bindable(),
		hiveConnecting,
		hiveError,
		hiveStatus,
		machineDisplayName,
		onConnect,
		onSkip
	}: {
		hiveLoading: boolean;
		officialHiveTarget: HiveSetupTarget | null;
		defaultHiveUrl: string;
		hiveUrl: string;
		hiveConnecting: boolean;
		hiveError: string | null;
		hiveStatus: string | null;
		machineDisplayName: string;
		onConnect: () => void;
		onSkip: () => void;
	} = $props();
</script>

<div class="flex flex-col gap-(--gap-panels)">
	{#if hiveLoading}
		<Panel>
			<p class="flex items-center gap-2 text-sm text-ink-muted">
				<Spinner size={16} />
				Checking the Hive connection…
			</p>
		</Panel>
	{:else if officialHiveTarget}
		<Alert tone="success" title="Connected to Hive">
			This sorter is registered with <span class="font-mono">{officialHiveTarget.url}</span>.
			{#if officialHiveTarget.machine_id}
				Machine ID <span class="font-mono">{officialHiveTarget.machine_id}</span>.
			{/if}
			You can manage the connection later in Settings > Hive; Continue finishes the setup.
		</Alert>
	{:else}
		<Panel
			title="Link to Hive"
			description="Continue takes you to the Hive server below. Sign in there (or make an account first) and confirm the machine's name; Hive brings you straight back here and finishes the link. No password is ever stored on this sorter."
		>
			<div class="flex max-w-xl flex-col gap-4">
				<Field
					label="Hive server"
					for="setup-hive-url"
					help="The official community platform by default; a local or custom Hive for development."
				>
					<Input
						id="setup-hive-url"
						type="url"
						class="font-mono"
						bind:value={hiveUrl}
						placeholder={defaultHiveUrl}
						disabled={hiveConnecting}
					/>
				</Field>
				<KeyValue items={[{ label: 'Machine name', value: machineDisplayName }]} />
				<p class="text-sm text-ink-muted">
					This is how the sorter appears in Hive. Change it in the first step if it needs to.
				</p>
			</div>
			{#snippet footer()}
				<Button variant="ghost" disabled={hiveConnecting} onclick={onSkip}>Skip for now</Button>
				<Button
					variant="primary"
					icon={ExternalLink}
					loading={hiveConnecting}
					disabled={!hiveUrl.trim()}
					onclick={onConnect}
				>
					{hiveConnecting ? 'Opening Hive…' : 'Continue on Hive'}
				</Button>
			{/snippet}
		</Panel>
	{/if}

	{#if hiveError}
		<Alert tone="danger" title="The Hive connection failed">{hiveError}</Alert>
	{:else if hiveStatus}
		<Alert tone="success">{hiveStatus}</Alert>
	{/if}
</div>
