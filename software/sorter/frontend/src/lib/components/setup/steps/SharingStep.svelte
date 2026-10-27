<!--
	What this sorter shares, and the person's agreement to it: the setup step, and
	the notice Settings > Hive shows before it pairs with a Hive. It loads what
	the machine shares (`/api/sharing`), lets the person turn off what can be
	turned off, and records the agreement with the switches as they are.

	All the words of the notice are in the module script below, in one place.
-->
<script lang="ts" module>
	export const sharingStepTitle = 'What this sorter shares';
	export const sharingStepDescription =
		'What leaves this sorter, and what you can turn off. You can change it any time in Settings > Data.';

	const ALWAYS_TITLE = 'Always';
	const ALWAYS = [
		'Piece photos go to Brickognize, which recognizes each part. Only the photo is sent.',
		'Once an hour a status report goes to basically: the software version, the hardware and how much this sorter has sorted. No pictures and no piece records.'
	];
	const WITH_HIVE_TITLE = 'With a Hive connected';
	const TRAINING =
		'Pictures and piece records train the recognition models every sorter uses. Keeping them on helps the most.';
	const DOCS_LABEL = 'Everything that leaves the machine';
	const DOCS_URL = 'https://docs.basically.website/sorter/what-leaves-the-machine/';
	const AGREE = 'Agree and continue';
</script>

<script lang="ts">
	import ArrowUpRight from '@lucide/svelte/icons/arrow-up-right';
	import StreamRows from '$lib/components/data/StreamRows.svelte';
	import Alert from '$lib/components/ui/Alert.svelte';
	import Button from '$lib/components/ui/Button.svelte';
	import Panel from '$lib/components/ui/Panel.svelte';
	import Spinner from '$lib/components/ui/Spinner.svelte';
	import {
		acceptSharing,
		everyHiveValues,
		getSharing,
		saveSharing,
		sharedWith,
		type Sharing
	} from '$lib/sharing/api';

	let {
		base,
		onagreed,
		oncancel
	}: {
		// The machine's address.
		base: string;
		// The agreement is recorded; gets the state the machine answered with.
		onagreed: (sharing: Sharing) => void;
		// A way out, where the notice interrupts something (pairing from Settings).
		oncancel?: () => void;
	} = $props();

	let sharing = $state<Sharing | null>(null);
	let loadError = $state<string | null>(null);
	let saveError = $state<string | null>(null);
	let saving = $state(false);
	// The optional streams as the switches show them, until the person agrees.
	let draft = $state<Record<string, boolean>>({});

	// Agreeing is asked for until the person has, and again when it changes.
	const needsAgreement = $derived(
		sharing !== null && (sharing.consent.needs_consent || sharing.consent.needs_review)
	);

	function message(e: unknown): string {
		return e instanceof Error ? e.message : String(e);
	}

	async function load(from: string) {
		try {
			const next = await getSharing(from);
			if (from !== base) return;
			sharing = next;
			draft = everyHiveValues(next);
			loadError = null;
		} catch (e) {
			if (from === base) loadError = `Couldn't load what this sorter shares: ${message(e)}`;
		}
	}

	$effect(() => {
		void load(base);
	});

	async function agree() {
		if (!sharing) return;
		const current = sharing;
		const changed = current.streams.some(
			(stream) => !stream.required && draft[stream.key] !== sharedWith(current, stream, null)
		);
		saving = true;
		saveError = null;
		try {
			const next = needsAgreement
				? await acceptSharing(base, current.consent.current_version, draft)
				: changed
					? await saveSharing(base, null, draft)
					: current;
			onagreed(next);
		} catch (e) {
			saveError = message(e);
		} finally {
			saving = false;
		}
	}
</script>

<div class="flex flex-col gap-(--gap-panels)">
	{#if loadError}
		<Alert tone="danger">
			{loadError}
			{#snippet actions()}
				<Button size="sm" onclick={() => void load(base)}>Try again</Button>
			{/snippet}
		</Alert>
	{:else if !sharing}
		<Panel>
			<p class="flex items-center gap-2 text-sm text-ink-muted"><Spinner size={16} /> Loading</p>
		</Panel>
	{:else}
		{@const current = sharing}
		<Panel title={ALWAYS_TITLE} flush>
			<ul class="divide-y divide-line">
				{#each ALWAYS as line (line)}
					<li class="px-(--pad-panel) py-(--pad-row) text-sm text-ink">{line}</li>
				{/each}
			</ul>
		</Panel>

		<Panel title={WITH_HIVE_TITLE} flush>
			<div class="divide-y divide-line">
				<StreamRows
					streams={current.streams}
					value={(stream) => draft[stream.key] ?? stream.default}
					onchange={(stream, on) => (draft = { ...draft, [stream.key]: on })}
				/>
			</div>
			<p class="border-t border-line px-(--pad-panel) py-3 text-sm text-ink-muted">{TRAINING}</p>
			{#snippet footer()}
				<a
					href={DOCS_URL}
					target="_blank"
					rel="noopener noreferrer"
					class="mr-auto inline-flex min-w-0 items-center gap-1 text-sm text-primary-ink hover:underline"
				>
					{DOCS_LABEL}
					<ArrowUpRight size={14} class="shrink-0" />
				</a>
				{#if oncancel}<Button variant="ghost" onclick={oncancel}>Cancel</Button>{/if}
				<Button variant="primary" loading={saving} onclick={agree}>
					{needsAgreement ? AGREE : 'Continue'}
				</Button>
			{/snippet}
		</Panel>

		{#if saveError}<Alert tone="danger">{saveError}</Alert>{/if}
	{/if}
</div>
