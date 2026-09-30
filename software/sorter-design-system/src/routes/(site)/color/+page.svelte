<!--
	Every token in both modes at once: each column is a `light` or `dark`
	subtree, so it shows what app.css gives that mode whatever the page's own.
	The values and contrast ratios are measured from what the browser draws.
-->
<script lang="ts">
	import Check from '@lucide/svelte/icons/check';
	import TriangleAlert from '@lucide/svelte/icons/triangle-alert';
	import PageHeader from '$lib/site/PageHeader.svelte';
	import SiteSection from '$lib/site/SiteSection.svelte';
	import Panel from '$lib/components/Panel.svelte';
	import ColorPicker from '$lib/components/ColorPicker.svelte';
	import Button from '$lib/components/Button.svelte';
	import { theme, contrast } from '$lib/theme.svelte';
	import { drawn, resolved } from '$lib/site/measure';

	type Row = {
		token: string;
		use: string;
		// What it is read against: text tokens get a contrast ratio.
		on?: string[];
		// A translucent fill, drawn over this plane to show it.
		over?: string;
		// Text drawn on this fill to show it (on-primary, on-success...).
		textOn?: string;
		min?: number;
	};

	const groups: { title: string; lead: string; rows: Row[] }[] = [
		{
			title: 'Planes',
			lead: 'The fills a screen is built from (Surfaces).',
			rows: [
				{ token: 'canvas', use: 'The page.' },
				{ token: 'surface', use: 'A panel.' },
				{ token: 'well', use: 'Sunk into a panel.' },
				{ token: 'raised', use: 'What floats: popovers, menus, dialogs.' },
				{ token: 'media', use: 'Behind camera feeds and photos; dark in both modes.' }
			]
		},
		{
			title: 'Controls',
			lead: 'The inside of a field, and the parts of a control that slides.',
			rows: [
				{ token: 'field', use: 'The inside of a field, and of a segmented control.' },
				{ token: 'track', use: 'The groove of a progress bar.' },
				{ token: 'knob', use: 'The knob of a switch.' }
			]
		},
		{
			title: 'Lines',
			lead: 'Both 1px. The divider between items, and the outline of a control.',
			rows: [
				{ token: 'line', use: 'Between items on one plane.', on: ['surface'], min: 1 },
				{
					token: 'line-strong',
					use: 'Around a field, a select, a checkbox.',
					on: ['surface'],
					min: 1.5
				}
			]
		},
		{
			title: 'Text',
			lead: 'Ink, muted ink for what explains, faint ink for placeholders and what is off.',
			rows: [
				{ token: 'ink', use: 'All text that matters.', on: ['surface', 'canvas'], min: 4.5 },
				{
					token: 'ink-muted',
					use: 'Help, descriptions, labels.',
					on: ['surface', 'canvas'],
					min: 4.5
				},
				{
					token: 'ink-faint',
					use: 'Placeholders, disabled, a unit hint. Never something someone must read.',
					on: ['surface'],
					min: 2
				}
			]
		},
		{
			title: 'State',
			lead: 'Translucent, so the same token works on every plane. Shown here over a surface.',
			rows: [
				{ token: 'hover', use: 'Under the pointer.', over: 'surface' },
				{ token: 'pressed', use: 'While pressed.', over: 'surface' },
				{ token: 'primary-soft', use: 'The chosen item, the current page.', over: 'surface' }
			]
		},
		{
			title: 'Primary',
			lead: 'The operator picks it on a machine; Hive is LEGO red. Its text colors are worked out from its contrast.',
			rows: [
				{
					token: 'primary',
					use: 'The one thing to do, the current page, focus.',
					textOn: 'on-primary',
					min: 4.5
				},
				{ token: 'primary-ink', use: 'The primary as text.', on: ['surface', 'canvas'], min: 4.5 }
			]
		}
	];

	const tones = ['success', 'warning', 'danger', 'info'] as const;

	let columns: Record<'light' | 'dark', HTMLElement | undefined> = $state({
		light: undefined,
		dark: undefined
	});
	// Measured values, keyed by mode then token; recomputed when the primary changes.
	let measured = $state<Record<string, Record<string, string>>>({ light: {}, dark: {} });

	const allTokens = [
		...groups.flatMap((g) => g.rows.map((r) => r.token)),
		'surface',
		'canvas',
		'on-primary',
		...tones.flatMap((t) => [t, `${t}-soft`, `${t}-ink`, `on-${t}`])
	];

	function measure() {
		for (const mode of ['light', 'dark'] as const) {
			const el = columns[mode];
			if (!el) continue;
			const surface = drawn(resolved(el, 'surface'));
			const out: Record<string, string> = {};
			for (const token of allTokens) out[token] = drawn(resolved(el, token), surface);
			measured[mode] = out;
		}
	}

	$effect(() => {
		void theme.primary;
		// After the new primary is on <html>.
		requestAnimationFrame(measure);
	});

	function grounds(row: Row): string[] {
		return row.textOn ? [row.token] : (row.on ?? []);
	}

	function ratio(mode: string, a: string, b: string) {
		const x = measured[mode][a];
		const y = measured[mode][b];
		return x && y ? contrast(x, y) : 0;
	}

	let colorId = $state(theme.colorId);
</script>

<svelte:head><title>Color · Sorter design system</title></svelte:head>

<PageHeader
	title="Color"
	lead="Neutrals for structure, the primary for what someone acts on, four LEGO colors for status. Every color is a token with a light and a dark value; both are below, measured as drawn."
	doc="color"
/>

{#snippet swatch(mode: 'light' | 'dark', row: Row)}
	<div class="flex items-center gap-3 py-2">
		{#if row.textOn}
			<span
				class="flex size-9 shrink-0 items-center justify-center text-sm font-semibold"
				style:background-color="var(--{row.token})"
				style:color="var(--{row.textOn})">Aa</span
			>
		{:else if row.on}
			<span
				class="flex size-9 shrink-0 items-center justify-center rounded-control border border-line bg-surface text-sm font-semibold"
				style:color={row.token.startsWith('line') ? undefined : `var(--${row.token})`}
			>
				{#if row.token.startsWith('line')}
					<span class="h-px w-6" style:background-color="var(--{row.token})"></span>
				{:else}Aa{/if}
			</span>
		{:else}
			<span
				class="size-9 shrink-0 rounded-control border border-line {row.over ? 'bg-surface' : ''}"
				style:background-image={row.over
					? `linear-gradient(var(--${row.token}), var(--${row.token}))`
					: undefined}
				style:background-color={row.over ? undefined : `var(--${row.token})`}
			></span>
		{/if}
		<div class="min-w-0 flex-1">
			<div class="flex items-baseline justify-between gap-2">
				<code class="truncate font-mono text-sm text-ink">{row.token}</code>
				<span class="num shrink-0 text-xs text-ink-muted">{measured[mode][row.token] ?? ''}</span>
			</div>
			{#if row.on || row.textOn}
				<div class="flex flex-wrap gap-x-3 text-xs text-ink-muted">
					{#each grounds(row) as ground (ground)}
						{@const r = row.textOn
							? ratio(mode, row.textOn, row.token)
							: ratio(mode, row.token, ground)}
						<span
							class="inline-flex items-center gap-1 {r >= (row.min ?? 4.5)
								? ''
								: 'text-danger-ink'}"
						>
							{#if r >= (row.min ?? 4.5)}<Check size={12} />{:else}<TriangleAlert size={12} />{/if}
							<span class="num">{r.toFixed(2)}</span>
							{row.textOn ? `for ${row.textOn}` : `on ${ground}`}
						</span>
					{/each}
				</div>
			{/if}
		</div>
	</div>
{/snippet}

{#each groups as group (group.title)}
	<SiteSection title={group.title} lead={group.lead}>
		<div class="grid gap-4 md:grid-cols-2">
			{#each ['light', 'dark'] as const as mode (mode)}
				<div class="{mode} rounded-panel bg-surface px-5 py-3">
					<div class="label mb-1">{mode}</div>
					<div class="divide-y divide-line">
						{#each group.rows as row (row.token)}
							{@render swatch(mode, row)}
						{/each}
					</div>
				</div>
			{/each}
		</div>
		{#if group.title === 'Text'}
			<p class="max-w-2xl text-sm text-ink-muted">
				Text must reach 4.5 to 1 against what it sits on. Faint ink does not, on purpose: it is for
				what someone can skip.
			</p>
		{/if}
	</SiteSection>
{/each}

<SiteSection
	title="Status"
	lead="LEGO green, yellow, red and blue, the same in both modes and whatever the primary. Each has a tint for notices and badges, an ink for text on a surface or on that tint, and a color for text on the solid."
>
	<div class="grid gap-4 md:grid-cols-2">
		{#each ['light', 'dark'] as const as mode (mode)}
			<div bind:this={columns[mode]} class="{mode} rounded-panel bg-surface px-5 py-3">
				<div class="label mb-1">{mode}</div>
				<div class="divide-y divide-line">
					{#each tones as tone (tone)}
						<div class="flex items-center gap-3 py-2.5">
							<span
								class="flex h-9 w-12 shrink-0 items-center justify-center text-sm font-semibold"
								style:background-color="var(--{tone})"
								style:color="var(--on-{tone})">Aa</span
							>
							<span
								class="flex h-9 w-12 shrink-0 items-center justify-center text-sm font-semibold"
								style:background-color="var(--{tone}-soft)"
								style:color="var(--{tone}-ink)">Aa</span
							>
							<div class="min-w-0 flex-1">
								<div class="flex items-baseline justify-between gap-2">
									<code class="font-mono text-sm text-ink">{tone}</code>
									<span class="num text-xs text-ink-muted">{measured[mode][tone] ?? ''}</span>
								</div>
								<div class="flex flex-wrap gap-x-3 text-xs text-ink-muted">
									{#each [{ label: `on-${tone}`, r: ratio(mode, `on-${tone}`, tone) }, { label: `${tone}-ink on the tint`, r: ratio(mode, `${tone}-ink`, `${tone}-soft`) }, { label: `${tone}-ink on surface`, r: ratio(mode, `${tone}-ink`, 'surface') }] as pair (pair.label)}
										<span
											class="inline-flex items-center gap-1 {pair.r >= 4.5
												? ''
												: 'text-danger-ink'}"
										>
											{#if pair.r >= 4.5}<Check size={12} />{:else}<TriangleAlert size={12} />{/if}
											<span class="num">{pair.r.toFixed(2)}</span>
											{pair.label}
										</span>
									{/each}
								</div>
							</div>
						</div>
					{/each}
				</div>
			</div>
		{/each}
	</div>
	<p class="max-w-2xl text-sm text-ink-muted">
		Text on the yellow fill is always dark (on-warning), because the yellow does not change with the
		mode; the yellow ink for text on a dark surface is a different token.
	</p>
</SiteSection>

<SiteSection
	title="The primary"
	lead="On a machine the operator picks it from the LEGO colors. The text on a primary fill, and the primary used as text, are worked out from its contrast, so every color reads. Pick one to see every page change."
>
	<Panel flush>
		<div class="grid grid-cols-1 gap-px bg-line md:grid-cols-[minmax(0,1fr)_18rem]">
			<div class="min-w-0 bg-surface p-5">
				<ColorPicker bind:value={colorId} onchange={(id) => theme.setColor(id)} />
			</div>
			<div class="flex flex-col gap-3 bg-surface p-5">
				<div class="flex flex-wrap items-center gap-2">
					<Button variant="primary">Home</Button>
					<Button>Rescan</Button>
				</div>
				<p class="text-sm text-primary-ink">The primary as text.</p>
				<div
					class="flex h-8 items-center bg-primary-soft px-3 text-sm font-medium text-primary-ink"
				>
					The current page
				</div>
			</div>
		</div>
	</Panel>
</SiteSection>

<SiteSection title="Rules">
	<ul class="divide-y divide-line overflow-hidden rounded-panel bg-surface text-sm">
		<li class="px-5 py-3">
			<span class="font-medium text-ink">Markup names a token, never a value.</span>
			<span class="text-ink-muted"
				>No hex, and none of Tailwind's own palette (bg-white, text-gray-500): neither follows the
				mode. The exceptions are the data a color is (the LEGO colors), categorical colors drawn
				over a photo, and static images.</span
			>
		</li>
		<li class="px-5 py-3">
			<span class="font-medium text-ink">A status color means that status.</span>
			<span class="text-ink-muted"
				>Green is running or done, yellow needs attention, red has failed or will destroy, blue is
				information. None of them decorates. If the primary is the same color as a status, the
				status still wins on its own component.</span
			>
		</li>
		<li class="px-5 py-3">
			<span class="font-medium text-ink">Tints, not borders, for tone.</span>
			<span class="text-ink-muted">A notice or a badge is its tone's tint, with no outline.</span>
		</li>
	</ul>
</SiteSection>
