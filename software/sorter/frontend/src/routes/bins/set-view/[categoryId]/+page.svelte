<script lang="ts">
	import { onMount } from 'svelte';
	import { page } from '$app/state';
	import QRCode from 'qrcode';
	import Minus from '@lucide/svelte/icons/minus';
	import Plus from '@lucide/svelte/icons/plus';
	import Printer from '@lucide/svelte/icons/printer';
	import Alert from '$lib/components/ui/Alert.svelte';
	import Badge from '$lib/components/ui/Badge.svelte';
	import Button from '$lib/components/ui/Button.svelte';
	import EmptyState from '$lib/components/ui/EmptyState.svelte';
	import Panel from '$lib/components/ui/Panel.svelte';
	import Spinner from '$lib/components/ui/Spinner.svelte';
	import Tabs from '$lib/components/ui/Tabs.svelte';

	type PartUserState = 'auto' | 'deferred' | 'complete';

	type SetViewPart = {
		part_num: string;
		color_id: string;
		part_name?: string | null;
		color_name?: string | null;
		quantity_needed: number;
		quantity_found: number;
		img_url?: string | null;
		manual_override_count?: number | null;
		user_state?: PartUserState;
	};

	type SetViewData = {
		category_id: string;
		set_num: string;
		name: string;
		img_url?: string | null;
		year?: number | null;
		num_parts?: number | null;
		total_needed: number;
		total_found: number;
		pct: number;
		parts: SetViewPart[];
	};

	type EffectiveStatus = 'unknown' | 'deferred' | 'complete';
	type FilterKey = 'all' | 'unknown' | 'deferred' | 'complete';

	let loading = $state(true);
	let error = $state<string | null>(null);
	let data = $state<SetViewData | null>(null);
	let filter = $state<FilterKey>('unknown');
	let qrDataUrl = $state<string | null>(null);
	let pendingKeys = $state<Set<string>>(new Set());
	// Paper is light whatever the page's mode: while printing, the page takes the light tokens.
	let printing = $state(false);

	const categoryId = $derived(decodeURIComponent(page.url.pathname.split('/').at(-1) || ''));

	function baseUrl(): string {
		return page.url.searchParams.get('base') || '';
	}

	function partKey(part: SetViewPart): string {
		return `${part.part_num}::${part.color_id}`;
	}

	function effectiveFound(part: SetViewPart): number {
		if (part.manual_override_count != null) return part.manual_override_count;
		if (part.user_state === 'complete') return part.quantity_needed;
		return part.quantity_found;
	}

	function effectiveStatus(part: SetViewPart): EffectiveStatus {
		if (part.user_state === 'deferred') return 'deferred';
		if (effectiveFound(part) >= part.quantity_needed) return 'complete';
		return 'unknown';
	}

	async function loadSetView() {
		loading = true;
		error = null;
		try {
			const res = await fetch(
				`${baseUrl()}/sorting-profile/set-view/${encodeURIComponent(categoryId)}`
			);
			if (!res.ok) {
				const body = await res.json().catch(() => null);
				throw new Error(body?.detail ?? `HTTP ${res.status}`);
			}
			data = await res.json();
		} catch (e: unknown) {
			error = e instanceof Error ? e.message : 'Failed to load set checklist';
		} finally {
			loading = false;
		}
	}

	async function updatePartState(
		part: SetViewPart,
		next: { manual_override_count: number | null; user_state: PartUserState }
	) {
		if (!data) return;
		const key = partKey(part);
		pendingKeys = new Set([...pendingKeys, key]);
		// Optimistic update
		const prevOverride = part.manual_override_count ?? null;
		const prevState = part.user_state ?? 'auto';
		part.manual_override_count = next.manual_override_count;
		part.user_state = next.user_state;
		try {
			const res = await fetch(
				`${baseUrl()}/sorting-profile/set-view/${encodeURIComponent(categoryId)}/part/state`,
				{
					method: 'POST',
					headers: { 'Content-Type': 'application/json' },
					body: JSON.stringify({
						part_num: part.part_num,
						color_id: part.color_id,
						manual_override_count: next.manual_override_count,
						user_state: next.user_state
					})
				}
			);
			if (!res.ok) {
				const body = await res.json().catch(() => null);
				throw new Error(body?.detail ?? `HTTP ${res.status}`);
			}
			const result = await res.json();
			part.manual_override_count = result.manual_override_count ?? null;
			part.user_state = (result.user_state as PartUserState) || 'auto';
		} catch (e) {
			// Revert
			part.manual_override_count = prevOverride;
			part.user_state = prevState;
			error = e instanceof Error ? e.message : 'Failed to update part state';
		} finally {
			const updated = new Set(pendingKeys);
			updated.delete(key);
			pendingKeys = updated;
		}
	}

	function onIncrement(part: SetViewPart) {
		const current = effectiveFound(part);
		updatePartState(part, {
			manual_override_count: current + 1,
			user_state: part.user_state === 'deferred' ? 'auto' : part.user_state ?? 'auto'
		});
	}

	function onDecrement(part: SetViewPart) {
		const current = effectiveFound(part);
		const nextCount = Math.max(0, current - 1);
		updatePartState(part, {
			manual_override_count: nextCount,
			user_state: part.user_state === 'deferred' ? 'auto' : part.user_state ?? 'auto'
		});
	}

	function onDefer(part: SetViewPart) {
		updatePartState(part, {
			manual_override_count: part.manual_override_count ?? null,
			user_state: 'deferred'
		});
	}

	function onComplete(part: SetViewPart) {
		updatePartState(part, {
			manual_override_count: null,
			user_state: 'complete'
		});
	}

	function onReset(part: SetViewPart) {
		updatePartState(part, { manual_override_count: null, user_state: 'auto' });
	}

	const filteredParts = $derived.by<SetViewPart[]>(() => {
		if (!data) return [];
		return data.parts.filter((part) => {
			if (filter === 'all') return true;
			return effectiveStatus(part) === filter;
		});
	});

	const counts = $derived.by(() => {
		if (!data) return { all: 0, unknown: 0, deferred: 0, complete: 0 };
		let unknown = 0;
		let deferred = 0;
		let complete = 0;
		for (const p of data.parts) {
			const s = effectiveStatus(p);
			if (s === 'unknown') unknown += 1;
			else if (s === 'deferred') deferred += 1;
			else complete += 1;
		}
		return { all: data.parts.length, unknown, deferred, complete };
	});

	const totals = $derived.by(() => {
		if (!data) return { found: 0, needed: 0, pct: 0 };
		let found = 0;
		let needed = 0;
		for (const p of data.parts) {
			needed += p.quantity_needed;
			found += Math.min(effectiveFound(p), p.quantity_needed);
		}
		return {
			found,
			needed,
			pct: needed > 0 ? Math.round((found / needed) * 100) : 0
		};
	});

	const tabs = $derived(
		(
			[
				['all', 'All'],
				['unknown', 'Unknown'],
				['deferred', 'Deferred'],
				['complete', 'Complete']
			] as [FilterKey, string][]
		).map(([value, label]) => ({ value, label, count: counts[value] }))
	);

	onMount(() => {
		void loadSetView();
		// Generate QR code with permalink to this view
		try {
			// A QR code is dark on light whatever the mode: the image's own colors.
			QRCode.toDataURL(window.location.href, {
				margin: 1,
				width: 160,
				color: { dark: '#000000', light: '#ffffff' }
			})
				.then((url) => {
					qrDataUrl = url;
				})
				.catch(() => {
					qrDataUrl = null;
				});
		} catch {
			qrDataUrl = null;
		}
	});
</script>

<svelte:head>
	<title>{data ? `${data.name} checklist` : 'Set checklist'}</title>
</svelte:head>

<svelte:window onbeforeprint={() => (printing = true)} onafterprint={() => (printing = false)} />

<div class="min-h-dvh bg-canvas px-4 py-6 text-ink sm:px-6 print:p-0 {printing ? 'light' : ''}">
	{#if loading}
		<p class="flex items-center gap-2 text-sm text-ink-muted">
			<Spinner size={16} />
			Loading the set checklist
		</p>
	{:else if error && !data}
		<Alert tone="danger" title="The checklist did not load">{error}</Alert>
	{:else if data}
		<div class="mx-auto flex max-w-[1400px] flex-col gap-(--gap-panels) print:max-w-none">
			<Panel class="print:p-0">
				<div class="flex flex-wrap items-start justify-between gap-4">
					<div class="flex items-start gap-4">
						{#if data.img_url}
							<img
								src={data.img_url}
								alt={data.name}
								class="size-28 shrink-0 rounded-control object-contain"
							/>
						{/if}
						<div>
							<div class="num text-sm text-ink-muted">
								Set {data.set_num}{#if data.year}
									&middot; {data.year}{/if}
							</div>
							<h1 class="mt-0.5 text-xl font-semibold tracking-tight text-ink">{data.name}</h1>
							<div class="mt-3 flex flex-wrap gap-2">
								<Badge>{totals.found} / {totals.needed} found</Badge>
								<Badge>{totals.pct}%</Badge>
								{#if data.num_parts}<Badge>{data.num_parts} parts total</Badge>{/if}
							</div>
						</div>
					</div>
					<div class="flex items-start gap-3">
						{#if qrDataUrl}
							<div class="flex flex-col items-center gap-1">
								<img src={qrDataUrl} alt="QR code linking to this checklist" class="size-28" />
								<div class="text-sm text-ink-muted">Scan to continue</div>
							</div>
						{/if}
						<div class="print:hidden">
							<Button icon={Printer} onclick={() => window.print()}>Print or save as PDF</Button>
						</div>
					</div>
				</div>
			</Panel>

			{#if error}<Alert tone="danger" title="The update failed">{error}</Alert>{/if}

			<div class="print:hidden">
				<Tabs label="Parts to show" bind:value={filter} items={tabs} />
			</div>

			<div class="grid grid-cols-1 gap-(--gap-panels) sm:grid-cols-2 xl:grid-cols-4 print:grid-cols-3">
				{#each filteredParts as part (partKey(part))}
					{@const status = effectiveStatus(part)}
					{@const found = effectiveFound(part)}
					{@const isPending = pendingKeys.has(partKey(part))}
					<div
						class="flex flex-col overflow-hidden rounded-panel {status === 'complete'
							? 'bg-success-soft'
							: status === 'deferred'
								? 'bg-warning-soft'
								: 'bg-surface'} print:break-inside-avoid {isPending ? 'opacity-60' : ''}"
					>
						<div class="relative p-4">
							{#if part.img_url}
								<img
									src={part.img_url}
									alt={part.part_name || part.part_num}
									class="h-52 w-full object-contain"
								/>
							{/if}
							<span
								class="dark num absolute right-3 bottom-3 rounded-badge bg-scrim px-3 py-1 text-2xl font-medium text-ink"
							>
								{part.quantity_needed}
							</span>
						</div>
						<div class="flex flex-1 flex-col gap-3 px-4 pb-4">
							<div>
								<div class="text-base font-semibold text-ink">{part.part_name || part.part_num}</div>
								<div class="mt-1 text-sm text-ink-muted">
									{part.part_num}{#if part.color_name}
										&middot; {part.color_name}{/if}
								</div>
							</div>

							<div class="flex items-center gap-2 print:hidden">
								<Button
									size="lg"
									icon={Minus}
									label="Decrement found count"
									disabled={isPending || found <= 0}
									onclick={() => onDecrement(part)}
								/>
								<div class="num flex h-(--size-control-lg) flex-1 items-center justify-center rounded-control bg-well text-base font-medium text-ink">
									{found} / {part.quantity_needed}
								</div>
								<Button
									size="lg"
									icon={Plus}
									label="Increment found count"
									disabled={isPending}
									onclick={() => onIncrement(part)}
								/>
							</div>

							<div class="hidden items-center justify-between text-sm print:flex">
								<span class="text-ink-muted">Found</span>
								<span class="num font-medium text-ink">{found} / {part.quantity_needed}</span>
							</div>

							<div class="flex gap-2 print:hidden">
								{#if status === 'complete'}
									<Button class="flex-1" disabled={isPending} onclick={() => onReset(part)}>Reset</Button>
								{:else if status === 'deferred'}
									<Button class="flex-1" disabled={isPending} onclick={() => onReset(part)}>Resume</Button>
									<Button variant="primary" class="flex-1" disabled={isPending} onclick={() => onComplete(part)}>
										Complete
									</Button>
								{:else}
									<Button class="flex-1" disabled={isPending} onclick={() => onDefer(part)}>Defer</Button>
									<Button variant="primary" class="flex-1" disabled={isPending} onclick={() => onComplete(part)}>
										Complete
									</Button>
								{/if}
							</div>
						</div>
					</div>
				{/each}
			</div>

			{#if filteredParts.length === 0}
				<EmptyState title="No parts in this view" />
			{/if}
		</div>
	{/if}
</div>
