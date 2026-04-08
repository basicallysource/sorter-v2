<script lang="ts">
	import { onMount } from 'svelte';
	import { page } from '$app/state';
	import QRCode from 'qrcode';

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

	const tabs: { key: FilterKey; label: string }[] = [
		{ key: 'all', label: 'All' },
		{ key: 'unknown', label: 'Unknown' },
		{ key: 'deferred', label: 'Deferred' },
		{ key: 'complete', label: 'Complete' }
	];

	onMount(() => {
		void loadSetView();
		// Generate QR code with permalink to this view
		try {
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
	<title>{data ? `${data.name} Checklist` : 'Set Checklist'}</title>
	<style>
		@media print {
			.no-print {
				display: none !important;
			}
			html,
			body {
				background: #ffffff !important;
				color: #000000 !important;
			}
		}
	</style>
</svelte:head>

<div class="min-h-screen bg-bg px-6 py-6 text-text print:px-0 print:py-0">
	{#if loading}
		<div class="text-sm text-text-muted">Loading set checklist…</div>
	{:else if error && !data}
		<div class="border border-[#D01012]/40 bg-[#D01012]/[0.06] px-3 py-2">
			<div class="text-[11px] font-semibold uppercase tracking-wider text-[#5C0708]">
				Could not load checklist
			</div>
			<div class="mt-1 text-xs leading-relaxed text-text">{error}</div>
		</div>
	{:else if data}
		<div class="mx-auto max-w-[1400px] space-y-6 print:max-w-none">
			<!-- Header card -->
			<div
				class="flex flex-wrap items-start justify-between gap-4 border border-border bg-surface px-5 py-5 print:border-none print:px-0"
			>
				<div class="flex items-start gap-4">
					{#if data.img_url}
						<img
							src={data.img_url}
							alt={data.name}
							class="h-28 w-28 border border-border bg-bg object-contain"
						/>
					{/if}
					<div>
						<div class="text-[11px] font-semibold uppercase tracking-wider text-text-muted">
							Set {data.set_num}{#if data.year}
								&middot; {data.year}{/if}
						</div>
						<h1 class="mt-0.5 text-2xl font-bold text-text">{data.name}</h1>
						<div class="mt-3 flex flex-wrap gap-2 text-sm text-text-muted">
							<span class="border border-border bg-bg px-3 py-1 tabular-nums"
								>{totals.found} / {totals.needed} found</span
							>
							<span class="border border-border bg-bg px-3 py-1 tabular-nums">{totals.pct}%</span>
							{#if data.num_parts}
								<span class="border border-border bg-bg px-3 py-1 tabular-nums"
									>{data.num_parts} parts total</span
								>
							{/if}
						</div>
					</div>
				</div>
				<div class="flex items-start gap-3">
					{#if qrDataUrl}
						<div class="flex flex-col items-center gap-1">
							<img
								src={qrDataUrl}
								alt="QR code linking to this checklist"
								class="h-28 w-28 border border-border bg-white"
							/>
							<div
								class="text-[10px] font-semibold uppercase tracking-wider text-text-muted"
							>
								Scan to continue
							</div>
						</div>
					{/if}
					<div class="flex flex-wrap items-center gap-2 print:hidden">
						<button
							type="button"
							onclick={() => window.print()}
							class="setup-button-primary inline-flex items-center gap-2 px-4 py-2 text-sm font-medium transition-colors"
						>
							Print / PDF
						</button>
					</div>
				</div>
			</div>

			{#if error}
				<div class="border border-[#D01012]/40 bg-[#D01012]/[0.06] px-3 py-2">
					<div class="text-[11px] font-semibold uppercase tracking-wider text-[#5C0708]">
						Update failed
					</div>
					<div class="mt-1 text-xs leading-relaxed text-text">{error}</div>
				</div>
			{/if}

			<!-- Tabs -->
			<div
				class="flex items-center justify-end gap-4 border-b border-border pb-2 text-sm text-text-muted print:hidden"
			>
				{#each tabs as tab}
					<button
						type="button"
						onclick={() => (filter = tab.key)}
						class={`pb-2 transition-colors ${filter === tab.key ? 'border-b-2 border-primary font-medium text-primary' : 'hover:text-text'}`}
					>
						{tab.label}
						<span class="ml-1 text-[11px] tabular-nums text-text-muted">({counts[tab.key]})</span>
					</button>
				{/each}
			</div>

			<!-- Cards grid -->
			<div class="grid gap-4 sm:grid-cols-2 xl:grid-cols-4 print:grid-cols-3">
				{#each filteredParts as part (partKey(part))}
					{@const status = effectiveStatus(part)}
					{@const found = effectiveFound(part)}
					{@const isPending = pendingKeys.has(partKey(part))}
					{@const cardBorder =
						status === 'complete'
							? 'border-[#00852B]/40 bg-[#00852B]/[0.04]'
							: status === 'deferred'
								? 'border-[#F2A900]/50 bg-[#F2A900]/[0.04]'
								: 'border-border bg-surface'}
					<div
						class={`flex flex-col overflow-hidden border ${cardBorder} print:break-inside-avoid`}
						class:opacity-60={isPending}
					>
						<div class="relative bg-surface p-4">
							{#if part.img_url}
								<img
									src={part.img_url}
									alt={part.part_name || part.part_num}
									class="h-52 w-full object-contain"
								/>
							{/if}
							<div
								class="absolute right-3 bottom-3 flex h-12 min-w-12 items-center justify-center border border-primary bg-primary px-3 text-2xl font-semibold text-primary-contrast tabular-nums"
							>
								{part.quantity_needed}
							</div>
						</div>
						<div class="flex flex-1 flex-col px-4 py-3">
							<div class="text-lg font-medium text-text">{part.part_name || part.part_num}</div>
							<div class="mt-1 text-sm text-text-muted">
								{part.part_num}{#if part.color_name}
									&middot; {part.color_name}{/if}
							</div>

							<!-- +/- counter row -->
							<div class="mt-3 flex items-stretch print:hidden">
								<button
									type="button"
									onclick={() => onDecrement(part)}
									disabled={isPending || found <= 0}
									class="setup-button-secondary flex h-12 w-14 flex-shrink-0 items-center justify-center text-2xl font-semibold text-text transition-colors disabled:cursor-not-allowed disabled:opacity-40"
									aria-label="Decrement found count"
								>
									−
								</button>
								<div
									class="flex flex-1 items-center justify-center border-y border-border bg-bg text-base font-semibold tabular-nums text-text"
								>
									{found} / {part.quantity_needed}
								</div>
								<button
									type="button"
									onclick={() => onIncrement(part)}
									disabled={isPending}
									class="setup-button-secondary flex h-12 w-14 flex-shrink-0 items-center justify-center text-2xl font-semibold text-text transition-colors disabled:cursor-not-allowed disabled:opacity-40"
									aria-label="Increment found count"
								>
									+
								</button>
							</div>

							<!-- Print-only count row -->
							<div class="mt-3 hidden items-center justify-between text-sm print:flex">
								<span class="text-text-muted">Found</span>
								<span class="font-medium tabular-nums text-text"
									>{found} / {part.quantity_needed}</span
								>
							</div>

							<!-- Action buttons -->
							<div class="mt-3 flex gap-2 print:hidden">
								{#if status === 'complete'}
									<button
										type="button"
										onclick={() => onReset(part)}
										disabled={isPending}
										class="setup-button-secondary flex-1 px-2 py-1.5 text-[11px] font-semibold uppercase tracking-wider text-text transition-colors disabled:cursor-not-allowed disabled:opacity-40"
									>
										Reset
									</button>
								{:else if status === 'deferred'}
									<button
										type="button"
										onclick={() => onReset(part)}
										disabled={isPending}
										class="setup-button-secondary flex-1 px-2 py-1.5 text-[11px] font-semibold uppercase tracking-wider text-text transition-colors disabled:cursor-not-allowed disabled:opacity-40"
									>
										Resume
									</button>
									<button
										type="button"
										onclick={() => onComplete(part)}
										disabled={isPending}
										class="setup-button-primary flex-1 px-2 py-1.5 text-[11px] font-semibold uppercase tracking-wider transition-colors disabled:cursor-not-allowed disabled:opacity-40"
									>
										Complete
									</button>
								{:else}
									<button
										type="button"
										onclick={() => onDefer(part)}
										disabled={isPending}
										class="setup-button-secondary flex-1 px-2 py-1.5 text-[11px] font-semibold uppercase tracking-wider text-text transition-colors disabled:cursor-not-allowed disabled:opacity-40"
									>
										Defer
									</button>
									<button
										type="button"
										onclick={() => onComplete(part)}
										disabled={isPending}
										class="setup-button-primary flex-1 px-2 py-1.5 text-[11px] font-semibold uppercase tracking-wider transition-colors disabled:cursor-not-allowed disabled:opacity-40"
									>
										Complete
									</button>
								{/if}
							</div>

						</div>
					</div>
				{/each}
			</div>

			{#if filteredParts.length === 0}
				<div class="border border-border bg-surface px-4 py-12 text-center text-sm text-text-muted">
					No parts in this view.
				</div>
			{/if}
		</div>
	{/if}
</div>
