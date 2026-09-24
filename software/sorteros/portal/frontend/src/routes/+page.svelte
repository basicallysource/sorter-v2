<script lang="ts">
	import { flushSync, onMount, tick, untrack } from 'svelte';
	import {
		finish,
		getState,
		isEnterprise,
		startJoin,
		startScan,
		type JoinRequest,
		type State
	} from '$lib/api';
	import { createRendezvous, lookupUrl } from '$lib/rendezvous';
	import Alert from '$lib/components/Alert.svelte';
	import ChooseNetwork from '$lib/components/ChooseNetwork.svelte';
	import Details from '$lib/components/Details.svelte';
	import Header from '$lib/components/Header.svelte';
	import JoinForm, { type JoinDraft, type Target } from '$lib/components/JoinForm.svelte';
	import Joined from '$lib/components/Joined.svelte';
	import Joining from '$lib/components/Joining.svelte';
	import Spinner from '$lib/components/Spinner.svelte';

	// Find my sorter is on Hive, the same Hive the Sorter tells its address to.
	const HIVE_URL = 'https://hive.basically.website';
	const POLL_MS = 1500;

	// ── The Sorter's state. Polled for as long as the page is open, and the
	// only thing that decides the screen, so a reload, a phone that drops off
	// and comes back, or a second phone all land on the same one.
	let live = $state<State | null>(null);
	let misses = $state(0); // polls in a row that didn't reach the Sorter
	let finished = $state(false); // Done was accepted: the setup network is closing

	let timer: ReturnType<typeof setTimeout> | undefined;
	let latest = 0;

	async function refresh() {
		clearTimeout(timer);
		if (finished) return;
		const mine = ++latest;
		try {
			const next = await getState();
			if (mine !== latest) return;
			live = next;
			misses = 0;
		} catch {
			if (mine !== latest) return;
			misses += 1;
		}
		if (!finished) timer = setTimeout(refresh, POLL_MS);
	}

	onMount(() => {
		refresh();
		const wake = () => document.visibilityState === 'visible' && refresh();
		document.addEventListener('visibilitychange', wake);
		return () => {
			clearTimeout(timer);
			document.removeEventListener('visibilitychange', wake);
		};
	});

	const join = $derived(live?.join ?? null);
	const failure = $derived(join?.state === 'failed' ? join : null);
	const lost = $derived(!finished && misses >= (live ? 2 : 1));
	const online = $derived(live?.networks.find((n) => n.internet) ?? null);
	// One row per name (a network on two bands can be listed twice).
	const scanned = $derived.by(() => {
		const seen = new Set<string>();
		return (live?.scan.networks ?? []).filter(
			(n) => n.ssid !== '' && !seen.has(n.ssid) && seen.add(n.ssid)
		);
	});

	// ── Choosing. Which network the form is for (null shows the list), and the
	// drafts, kept here so a failed join comes back to them.
	let target = $state<Target | null>(null);
	let ssid = $state('');
	let password = $state('');
	let name = $state('');
	let naming = $state(false);
	let form = $state<ReturnType<typeof JoinForm>>();
	// A joined network the person chose to replace: its join's `at`.
	let replacing = $state<number | null>(null);

	const screen = $derived(
		!live
			? 'loading'
			: join?.state === 'joining'
				? 'joining'
				: join?.state === 'joined' && replacing !== join.at
					? 'joined'
					: 'choose'
	);

	$effect(() => {
		void screen;
		untrack(() => window.scrollTo(0, 0));
	});

	/** A tap on the list. The form renders inside the tap so the password can
	 *  take focus and bring up the keyboard, which iOS only allows then. */
	function openForm(next: Target) {
		flushSync(() => {
			if (next.hidden !== target?.hidden || next.ssid !== target?.ssid) {
				password = '';
				ssid = next.ssid;
			}
			target = next;
			joinError = null;
		});
		window.scrollTo(0, 0);
		form?.focusFirst();
	}

	function backToList() {
		target = null;
		joinError = null;
		window.scrollTo(0, 0);
	}

	// A join that failed opens the form for that network again, once per
	// failure, with the password focused.
	let handledFailure = '';
	$effect(() => {
		if (!failure) return;
		const key = `${failure.ssid}\n${failure.at}`;
		if (key === handledFailure) return;
		handledFailure = key;
		untrack(() => {
			const listed = scanned.find((n) => n.ssid === failure.ssid);
			joinError = null;
			if (listed && isEnterprise(listed)) {
				target = null;
				return;
			}
			target = listed
				? { ssid: listed.ssid, security: listed.security, hidden: false }
				: { ssid: failure.ssid, security: '', hidden: true };
			if (!listed) ssid = failure.ssid;
			if (failure.reason === 'password') password = '';
			tick().then(() => form?.focusFirst());
		});
	});

	// ── Joining. The Find my sorter id is made once per page; the link is only
	// offered for a join this page sent, since that's the id the Sorter has.
	const rendezvous = createRendezvous();
	let joinBusy = $state(false);
	let joinError = $state<string | null>(null);
	let sentSsid = $state<string | null>(null);

	async function sendJoin(draft: JoinDraft) {
		joinBusy = true;
		joinError = null;
		const req: JoinRequest = { ssid: draft.ssid, password: draft.password, hidden: draft.hidden };
		const timezone = Intl.DateTimeFormat().resolvedOptions().timeZone;
		if (timezone) req.timezone = timezone;
		if (draft.name) req.name = draft.name;
		if (rendezvous) req.rendezvous_id = rendezvous.id;
		try {
			await startJoin(req);
			sentSsid = draft.ssid;
			await refresh();
		} catch (e) {
			joinError = (e as Error).message;
		} finally {
			joinBusy = false;
		}
	}

	const findLink = $derived(
		rendezvous && join?.state === 'joined' && join.ssid === sentSsid
			? lookupUrl(HIVE_URL, rendezvous)
			: null
	);

	let scanAsked = $state(false);
	const scanning = $derived(scanAsked || !!live?.scan.scanning);

	async function rescan() {
		scanAsked = true;
		// A refusal needs no words of its own: the next poll shows whether it's
		// scanning, and a Sorter that can't be reached says so above.
		await startScan().catch(() => {});
		await refresh();
		scanAsked = false;
	}

	function chooseAnother() {
		replacing = join?.at ?? null;
		target = null;
	}

	let finishing = $state(false);
	let finishError = $state<string | null>(null);

	async function done() {
		finishing = true;
		finishError = null;
		try {
			await finish();
			finished = true;
			clearTimeout(timer);
		} catch (e) {
			finishError = (e as Error).message;
		} finally {
			finishing = false;
		}
	}
</script>

<svelte:head>
	<title>Sorter setup</title>
</svelte:head>

<Header name={live?.sorter.name ?? null} />

<main class="mx-auto flex w-full max-w-md flex-col gap-6 px-4 pt-6 pb-16">
	{#if lost}
		<Alert variant="warning">
			Lost the connection to the Sorter. If your phone left
			<span class="font-medium">{live?.setup_network.ssid ?? "the Sorter's setup network"}</span>,
			rejoin it.
		</Alert>
	{/if}

	{#if !live}
		{#if !lost}
			<div class="flex justify-center py-16 text-text-muted"><Spinner size={24} /></div>
		{/if}
	{:else if screen === 'joining' && join}
		<Joining ssid={join.ssid} seconds={live.now - join.at} />
	{:else if screen === 'joined' && join}
		<Joined
			{join}
			mdns={live.sorter.mdns}
			software={live.sorter.software}
			{findLink}
			{finished}
			{finishing}
			{finishError}
			ondone={done}
			onchoose={chooseAnother}
		/>
	{:else if target}
		<JoinForm
			bind:this={form}
			{target}
			failure={failure?.ssid === target.ssid ? failure : null}
			currentName={live.sorter.name}
			busy={joinBusy}
			error={joinError}
			bind:ssid
			bind:password
			bind:name
			bind:naming
			onback={backToList}
			onjoin={sendJoin}
		/>
	{:else}
		<ChooseNetwork
			networks={scanned}
			{scanning}
			{online}
			{failure}
			onrefresh={rescan}
			onpick={(n) => openForm({ ssid: n.ssid, security: n.security, hidden: false })}
			onother={() => openForm({ ssid: '', security: '', hidden: true })}
		/>
	{/if}

	{#if live}
		<Details state={live} />
	{/if}
</main>
