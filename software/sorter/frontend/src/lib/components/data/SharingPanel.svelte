<!--
	Settings > Data: what this sorter shares, for every Hive or for one. Every
	Hive has the machine-wide values; a Hive can be set differently, and the
	rows that differ say so and put the Hive back to what every Hive gets.
-->
<script lang="ts">
	import { page } from '$app/state';
	import { getBackendHttpBase, machineHttpBaseUrlFromWsUrl } from '$lib/backend';
	import { getMachineContext } from '$lib/machines/context';
	import StreamRows from '$lib/components/data/StreamRows.svelte';
	import Alert from '$lib/components/ui/Alert.svelte';
	import Button from '$lib/components/ui/Button.svelte';
	import Panel from '$lib/components/ui/Panel.svelte';
	import Select from '$lib/components/ui/Select.svelte';
	import SettingRow from '$lib/components/ui/SettingRow.svelte';
	import Spinner from '$lib/components/ui/Spinner.svelte';
	import {
		acceptSharing,
		defaultOf,
		everyHiveValues,
		getSharing,
		optionalStreams,
		resetSharing,
		saveSharing,
		sharedWith,
		withValue,
		type Sharing,
		type SharingStream
	} from '$lib/sharing/api';

	const machine = getMachineContext();

	const base = $derived(machineHttpBaseUrlFromWsUrl(machine.machine?.url) ?? getBackendHttpBase());

	let sharing = $state<Sharing | null>(null);
	let loadError = $state<string | null>(null);
	let saveError = $state<string | null>(null);
	// A reset or an agreement is being saved.
	let busy = $state(false);
	// 'all', or the id of one Hive.
	let scope = $state('all');

	const target = $derived(
		scope === 'all' ? null : (sharing?.targets.find((t) => t.id === scope) ?? null)
	);
	const targetId = $derived(target?.id ?? null);

	// Only the newest request may write the page: a slow answer to an older one
	// would put an older state over a newer.
	let request = 0;

	function message(e: unknown): string {
		return e instanceof Error ? e.message : String(e);
	}

	async function load(from: string) {
		const mine = ++request;
		try {
			const next = await getSharing(from);
			if (mine !== request) return;
			sharing = next;
			loadError = null;
		} catch (e) {
			if (mine === request) loadError = `Couldn't load what this sorter shares: ${message(e)}`;
		}
	}

	$effect(() => {
		void load(base);
	});

	// "What it receives" on the Hive page links here with ?hive=<id>.
	$effect(() => {
		const wanted = page.url.searchParams.get('hive');
		if (wanted) scope = wanted;
	});

	// A change shows at once and is replaced by the machine's answer; if the
	// machine refuses it, the page goes back to what it was.
	async function save(id: string | null, values: Record<string, boolean>) {
		if (!sharing) return;
		const before = sharing;
		let shown = sharing;
		for (const [key, on] of Object.entries(values)) shown = withValue(shown, id, key, on);
		sharing = shown;
		saveError = null;
		const mine = ++request;
		try {
			const next = await saveSharing(base, id, values);
			if (mine === request) sharing = next;
		} catch (e) {
			if (mine === request) sharing = before;
			saveError = message(e);
		}
	}

	async function settle(change: () => Promise<Sharing>) {
		busy = true;
		saveError = null;
		const mine = ++request;
		try {
			const next = await change();
			if (mine === request) sharing = next;
		} catch (e) {
			saveError = message(e);
		} finally {
			busy = false;
		}
	}

	function backToDefaults() {
		void settle(() => resetSharing(base, targetId));
	}

	// Agrees to the notice as it stands, with the values as they are.
	function agree() {
		if (!sharing) return;
		const current = sharing;
		void settle(() => acceptSharing(base, current.consent.current_version, everyHiveValues(current)));
	}

	// For a stream not at what it should be: every Hive's value is the default;
	// a Hive's is what every Hive gets.
	function resetFor(stream: SharingStream) {
		if (!sharing || stream.required) return null;
		if (target) {
			if (!(stream.key in target.overrides)) return null;
			const every = sharedWith(sharing, stream, null);
			return {
				text: `every Hive (${every ? 'on' : 'off'})`,
				help: `Every Hive gets this ${every ? 'on' : 'off'}. Give ${target.name} the same.`,
				onreset: () => void save(target.id, { [stream.key]: every })
			};
		}
		const fallback = defaultOf(sharing, stream);
		if (sharedWith(sharing, stream, null) === fallback) return null;
		return {
			text: fallback ? 'on' : 'off',
			onreset: () => void save(null, { [stream.key]: fallback })
		};
	}

	const hasOwnValues = $derived.by(() => {
		const current = sharing;
		if (!current) return false;
		if (target) return Object.keys(target.overrides).length > 0;
		return optionalStreams(current).some(
			(stream) => sharedWith(current, stream, null) !== defaultOf(current, stream)
		);
	});

	const scopeOptions = $derived([
		{ value: 'all', label: 'Every Hive' },
		...(sharing?.targets ?? []).map((t) => ({ value: t.id, label: t.name }))
	]);

	const description = $derived(
		sharing && sharing.targets.length === 0
			? 'No Hive is connected yet. What you choose here applies to each one you connect.'
			: 'What each Hive may receive. The icon after a name says what it is for.'
	);
</script>

<Panel title="Shared with Hive" {description} flush>
	{#snippet actions()}
		{#if hasOwnValues}
			<Button variant="ghost" size="sm" loading={busy} onclick={backToDefaults}>
				{target ? "Use every Hive's settings" : 'Reset to defaults'}
			</Button>
		{/if}
	{/snippet}

	{#if loadError}
		<div class="px-(--pad-panel) pb-4">
			<Alert tone="danger">
				{loadError}
				{#snippet actions()}
					<Button size="sm" onclick={() => void load(base)}>Try again</Button>
				{/snippet}
			</Alert>
		</div>
	{:else if !sharing}
		<p class="flex items-center gap-2 px-(--pad-panel) pb-4 text-sm text-ink-muted">
			<Spinner size={14} /> Loading
		</p>
	{:else}
		{@const current = sharing}
		{#if current.consent.needs_consent || current.consent.needs_review}
			<div class="px-(--pad-panel) pb-3">
				<Alert
					tone="info"
					title={current.consent.needs_consent
						? 'Nothing is shared with a Hive yet'
						: 'What this sorter shares has changed'}
				>
					{current.consent.needs_consent
						? 'Look over the list, then agree to start sharing it.'
						: 'Machine telemetry is new. Look over the list, then press OK.'}
					{#snippet actions()}
						<Button size="sm" variant="primary" loading={busy} onclick={agree}>
							{current.consent.needs_consent ? 'Agree' : 'OK'}
						</Button>
					{/snippet}
				</Alert>
			</div>
		{/if}

		<div class="divide-y divide-line">
			{#if current.targets.length > 0}
				<SettingRow
					label="Shared with"
					for="sharing-scope"
					info="Every Hive gets the same unless you set one differently. Choose a Hive to see and change what it receives."
				>
					<Select
						id="sharing-scope"
						value={target?.id ?? 'all'}
						options={scopeOptions}
						onchange={(value) => (scope = value)}
						class="w-full sm:w-64"
					/>
				</SettingRow>
			{/if}
			<StreamRows
				streams={current.streams}
				value={(stream) => sharedWith(current, stream, targetId)}
				onchange={(stream, on) => void save(targetId, { [stream.key]: on })}
				reset={resetFor}
			/>
		</div>

		{#if saveError}
			<div class="border-t border-line px-(--pad-panel) py-3">
				<Alert tone="danger">{saveError}</Alert>
			</div>
		{/if}
	{/if}
</Panel>
