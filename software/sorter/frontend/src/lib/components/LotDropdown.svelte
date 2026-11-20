<!--
	The top bar's lot menu, beside the sorting profile: which lot the pieces
	sorted from now on belong to, or none, and whether they are new to the lot
	or the lot's own pieces going through again. Choosing is bookkeeping only,
	so it works while the machine runs: the pieces seen from that moment on go
	to a new sorting run (see the backend's sorting_runs.setNow).
-->
<script lang="ts">
	import { tick, untrack } from 'svelte';
	import { getMachinesContext } from '$lib/machines/context';
	import { selectedBaseUrl } from '$lib/machines/system-actions';
	import { sortingNow } from '$lib/stores/sortingNow.svelte';
	import Check from '@lucide/svelte/icons/check';
	import ChevronDown from '@lucide/svelte/icons/chevron-down';
	import Plus from '@lucide/svelte/icons/plus';
	import Repeat from '@lucide/svelte/icons/repeat';
	import X from '@lucide/svelte/icons/x';
	import Alert from '$lib/components/ui/Alert.svelte';
	import Badge from '$lib/components/ui/Badge.svelte';
	import Button from '$lib/components/ui/Button.svelte';
	import Input from '$lib/components/ui/Input.svelte';
	import Popover from '$lib/components/ui/Popover.svelte';
	import SegmentedControl from '$lib/components/ui/SegmentedControl.svelte';
	import Spinner from '$lib/components/ui/Spinner.svelte';

	type Mode = 'add' | 'resort';

	const REFRESH_MS = 60_000;
	const MODES = [
		{ value: 'add' as const, label: 'Adding to it', icon: Plus },
		{ value: 'resort' as const, label: 'Re-sorting it', icon: Repeat }
	];

	const manager = getMachinesContext();

	let open = $state(false);
	let error = $state<string | null>(null);
	// What a request is out for: a lot's id, 'none', 'new' or 'mode'.
	let busy = $state<string | null>(null);
	let naming = $state(false);
	let newName = $state('');
	let nameInput = $state<HTMLInputElement>();
	let mode = $state<Mode>('add');

	const base = $derived(selectedBaseUrl(manager));
	const now = $derived(sortingNow.for(base));
	const lots = $derived(now?.lots ?? []);
	const lotId = $derived(now?.run?.lot_id ?? null);
	const lotName = $derived(now?.run?.lot_name ?? null);
	const resorting = $derived(lotId !== null && now?.run?.adds_to_lot === false);

	$effect(() => {
		mode = resorting ? 'resort' : 'add';
	});

	// Another browser, or the records page, can change the run: ask again now
	// and then, and when this window comes back into view.
	$effect(() => {
		if (!manager.selectedMachineId) return;
		const from = base;
		const refresh = (maxAgeMs: number) => {
			if (document.visibilityState !== 'visible') return;
			void sortingNow.refresh(from, maxAgeMs).catch(() => {});
		};
		const shown = () => refresh(REFRESH_MS / 2);
		shown();
		const timer = setInterval(() => refresh(0), REFRESH_MS);
		document.addEventListener('visibilitychange', shown);
		return () => {
			clearInterval(timer);
			document.removeEventListener('visibilitychange', shown);
		};
	});

	// Opening the menu shows the lots as they are now.
	$effect(() => {
		if (!open) return;
		untrack(() => {
			error = null;
			naming = false;
			newName = '';
			void sortingNow.refresh(base).catch((e: unknown) => (error = message(e)));
		});
	});

	function message(e: unknown): string {
		return e instanceof Error ? e.message : String(e);
	}

	async function act(key: string, change: () => Promise<void>): Promise<boolean> {
		busy = key;
		error = null;
		try {
			await change();
			return true;
		} catch (e) {
			error = message(e);
			return false;
		} finally {
			busy = null;
		}
	}

	async function chooseNone() {
		if (await act('none', () => sortingNow.set(base, null, true))) open = false;
	}

	// A lot is chosen adding to it; the menu stays open for the other choice.
	function chooseLot(id: string) {
		void act(id, () => sortingNow.set(base, id, true));
	}

	async function chooseMode(next: Mode) {
		if (lotId === null) return;
		const id = lotId;
		const done = await act('mode', () => sortingNow.set(base, id, next === 'add'));
		if (!done) mode = resorting ? 'resort' : 'add';
	}

	async function startNaming() {
		naming = true;
		await tick();
		nameInput?.focus();
	}

	async function createLot() {
		const name = newName.trim();
		if (!name) return;
		if (await act('new', () => sortingNow.createLot(base, name))) {
			naming = false;
			newName = '';
		}
	}
</script>

{#snippet mark(on: boolean, waiting: boolean)}
	<span class="flex size-4 shrink-0 items-center justify-center text-primary-ink">
		{#if waiting}<Spinner size={14} />{:else if on}<Check size={16} />{/if}
	</span>
{/snippet}

<Popover label="Lot" placement="bottom-end" width="22rem" padded={false} bind:open>
	{#snippet trigger(props)}
		<button
			{...props}
			type="button"
			disabled={!manager.selectedMachineId}
			title={resorting
				? 'Re-sorting this lot: its pieces are not counted again'
				: lotId
					? 'Pieces sorted now are added to this lot'
					: 'Pieces sorted now belong to no lot'}
			class="flex h-(--size-control-sm) max-w-52 items-center gap-2 rounded-control border border-line-strong bg-field pr-2 pl-2.5 text-sm text-ink transition-colors hover:border-ink-faint disabled:pointer-events-none disabled:opacity-45"
		>
			{#if lotId}<span class="shrink-0 text-ink-muted">Lot</span>{/if}
			<span class="truncate font-medium">{lotId ? (lotName ?? 'Lot') : 'No lot'}</span>
			{#if resorting}<Badge tone="info">Re-sort</Badge>{/if}
			<ChevronDown size={16} class="shrink-0 text-ink-muted" />
		</button>
	{/snippet}

	{#if error}
		<div class="px-4 pt-3"><Alert tone="danger">{error}</Alert></div>
	{/if}

	<div class="label flex items-center justify-between gap-2 border-b border-line px-4 py-1.5">
		<span>Lot</span>
		<span>Pieces</span>
	</div>

	<div class="max-h-[50dvh] divide-y divide-line overflow-y-auto">
		<button
			type="button"
			onclick={() => void chooseNone()}
			disabled={busy !== null}
			aria-pressed={now !== null && lotId === null}
			class="flex w-full items-center gap-2 px-4 py-2.5 text-left transition-colors hover:bg-hover disabled:pointer-events-none"
		>
			{@render mark(now !== null && lotId === null, busy === 'none')}
			<span class="min-w-0 flex-1 truncate font-medium text-ink">No lot</span>
		</button>

		{#if now === null && !error}
			<div class="flex justify-center px-4 py-3"><Spinner /></div>
		{/if}

		{#each lots as lot (lot.id)}
			{#if lot.id === lotId}
				<div class="bg-primary-soft px-4 py-2.5">
					<div class="flex items-center gap-2">
						{@render mark(true, false)}
						<span class="min-w-0 flex-1 truncate font-medium text-ink">{lot.name}</span>
						<span class="num shrink-0 text-ink-muted">{lot.pieces.toLocaleString()}</span>
					</div>
					<div class="mt-2 pl-6">
						<SegmentedControl
							bind:value={mode}
							options={MODES}
							label="What sorting does to this lot"
							size="sm"
							full
							onchange={(next) => void chooseMode(next)}
						/>
						{#if resorting}
							<p class="mt-1 text-right text-sm text-ink-muted">pieces already counted in this lot</p>
						{/if}
					</div>
				</div>
			{:else}
				<button
					type="button"
					onclick={() => chooseLot(lot.id)}
					disabled={busy !== null}
					aria-pressed="false"
					class="flex w-full items-center gap-2 px-4 py-2.5 text-left transition-colors hover:bg-hover disabled:pointer-events-none"
				>
					{@render mark(false, busy === lot.id)}
					<span class="min-w-0 flex-1 truncate font-medium text-ink">{lot.name}</span>
					<span class="num shrink-0 text-ink-muted">{lot.pieces.toLocaleString()}</span>
				</button>
			{/if}
		{/each}
	</div>

	<div class="flex items-center gap-2 border-t border-line px-4 py-2.5">
		{#if naming}
			<form
				class="flex min-w-0 flex-1 items-center gap-2"
				onsubmit={(e) => {
					e.preventDefault();
					void createLot();
				}}
			>
				<Input
					bind:value={newName}
					bind:element={nameInput}
					size="sm"
					class="min-w-0 flex-1"
					placeholder="New lot's name"
					aria-label="New lot's name"
					autocomplete="off"
				/>
				<Button
					type="submit"
					size="sm"
					variant="primary"
					loading={busy === 'new'}
					disabled={!newName.trim() || busy !== null}
				>
					Create
				</Button>
				<Button
					size="sm"
					variant="ghost"
					icon={X}
					label="Cancel the new lot"
					onclick={() => (naming = false)}
				/>
			</form>
		{:else}
			<Button size="sm" icon={Plus} disabled={busy !== null} onclick={() => void startNaming()}>
				New lot
			</Button>
			<Button size="sm" class="ml-auto" onclick={() => (open = false)}>Done</Button>
		{/if}
	</div>
</Popover>
