<script lang="ts">
	import { api, type KitSummary } from '$lib/api';
	import { kitSource, plural } from '$lib/profile-display';
	import { sentence } from '$lib/text';
	import Alert from '$lib/components/Alert.svelte';
	import Badge from '$lib/components/Badge.svelte';
	import Button from '$lib/components/Button.svelte';
	import Card from '$lib/components/Card.svelte';
	import EmptyState from '$lib/components/EmptyState.svelte';
	import Input from '$lib/components/Input.svelte';
	import PageHeader from '$lib/components/PageHeader.svelte';
	import Panel from '$lib/components/Panel.svelte';
	import Spinner from '$lib/components/Spinner.svelte';
	import Tabs from '$lib/components/Tabs.svelte';
	import KitPicture from '$lib/components/profile/KitPicture.svelte';
	import Boxes from '@lucide/svelte/icons/boxes';
	import Plus from '@lucide/svelte/icons/plus';
	import TriangleAlert from '@lucide/svelte/icons/triangle-alert';

	type Scope = 'mine' | 'public';

	let scope = $state<Scope>('mine');
	let query = $state('');
	let kits = $state<KitSummary[]>([]);
	let loading = $state(true);
	let error = $state<string | null>(null);
	let counts = $state<Partial<Record<Scope, number>>>({});

	// Asking again for each scope and each pause in typing; an answer that
	// arrives after a newer question is dropped.
	let asked = 0;
	let listedScope: Scope | null = null;
	$effect(() => {
		const which = scope;
		const text = query.trim();
		const turn = ++asked;
		loading = true;
		// The other tab's kits are not this tab's while it loads.
		if (listedScope !== which) {
			kits = [];
			listedScope = which;
		}
		const timer = setTimeout(
			() => {
				api
					.listKits({ scope: which, q: text || undefined })
					.then((list) => {
						if (turn !== asked) return;
						kits = list;
						error = null;
						if (!text) counts[which] = list.length;
					})
					.catch((e: any) => {
						if (turn === asked) error = e.error || 'Failed to load kits';
					})
					.finally(() => {
						if (turn === asked) loading = false;
					});
			},
			text ? 250 : 0
		);
		return () => clearTimeout(timer);
	});

	const tabs = $derived([
		{ value: 'mine' as Scope, label: 'Yours', count: counts.mine },
		{ value: 'public' as Scope, label: 'Public', count: counts.public }
	]);
</script>

<svelte:head><title>Kits - Hive</title></svelte:head>

<PageHeader
	title="Kits"
	description="Parts in colors with quantities: a LEGO set, an order, a build. A kit bin in a profile collects a kit until it is full."
>
	{#snippet actions()}
		<Button href="/kits/new" variant="primary" icon={Plus}>New kit</Button>
	{/snippet}
</PageHeader>

{#if error}<Alert tone="danger">{error}</Alert>{/if}

<Tabs label="Kits" value={scope} items={tabs} onchange={(next) => (scope = next)} />

<Input
	type="search"
	class="w-full sm:w-72"
	bind:value={query}
	placeholder="Search by name or set number"
	aria-label="Search kits"
/>

{#if loading && kits.length === 0}
	<div class="flex justify-center p-8"><Spinner size={32} /></div>
{:else if kits.length === 0}
	<Panel>
		<EmptyState icon={Boxes} title={query.trim() ? 'No kits match' : scope === 'mine' ? 'No kits yet' : 'No public kits yet'}>
			{#if query.trim()}
				Try a different name or set number.
			{:else if scope === 'mine'}
				Make a kit from a LEGO set, a BrickLink list, or by adding parts yourself.
			{:else}
				Kits other people make public show up here.
			{/if}
			{#snippet action()}
				{#if scope === 'mine' && !query.trim()}
					<Button href="/kits/new" variant="primary" icon={Plus}>New kit</Button>
				{/if}
			{/snippet}
		</EmptyState>
	</Panel>
{:else}
	<div class="grid gap-(--gap-panels) sm:grid-cols-2 xl:grid-cols-3" aria-busy={loading}>
		{#each kits as kit (kit.id)}
			<Card href="/kits/{kit.id}" label={kit.name}>
				<div class="flex items-start gap-3">
					<KitPicture src={kit.image_url} class="size-16 shrink-0" />
					<div class="min-w-0 flex-1">
						<h2 class="truncate text-base font-semibold text-ink">{kit.name}</h2>
						<p class="truncate text-sm text-ink-muted">{kitSource(kit)}</p>
						<p class="num text-sm text-ink-muted">
							{plural(kit.line_count, 'part')}, {plural(kit.total_quantity, 'piece')}
						</p>
					</div>
				</div>
				<div class="mt-3 flex flex-wrap items-center gap-x-2 gap-y-1.5 text-sm text-ink-muted">
					{#if kit.any_color_lines > 0}
						<Badge tone="warning"
							><TriangleAlert size={12} />{plural(kit.any_color_lines, 'part')} in any color</Badge
						>
					{/if}
					{#if !kit.is_owner}
						<span class="truncate">By {kit.owner.display_name ?? kit.owner.github_login ?? 'unknown'}</span>
					{:else if scope === 'mine'}
						<Badge>{sentence(kit.visibility)}</Badge>
					{/if}
				</div>
			</Card>
		{/each}
	</div>
{/if}
