<!--
	docs/components.md#choices. One choice from a few that a picture tells
	apart (which kind of chute a machine has): each option is a tile with its
	picture, its name and one sentence, chosen like a radio. The tiles sit on a
	well inside a panel; the chosen one takes the primary's tint, the pointer
	lays a faint fill over any other, and the arrow keys move the choice, as in
	any radio group. A picture holds its place before it loads, and one that
	cannot load leaves a quiet blank, never a broken-image icon, so the choice
	still reads from its name and sentence. An option that cannot be chosen
	says why in `note`.

	<PictureChoice name="chute" label="Which chute" bind:value options={[...]} />
-->
<script lang="ts" generics="T extends string">
	type Option = {
		value: T;
		label: string;
		// One sentence about it.
		help?: string;
		picture?: string | null;
		// What the picture shows, when the label does not say it.
		alt?: string;
		disabled?: boolean;
		// Why it cannot be chosen, or anything else under the sentence.
		note?: string;
	};

	let {
		value = $bindable(),
		options,
		name,
		label,
		plane = 'well',
		onchange,
		class: className = ''
	}: {
		value: T | null;
		options: Option[];
		// The inputs' shared name.
		name: string;
		// The group's accessible name.
		label: string;
		// The plane the tiles are drawn on: a well in a panel, a surface in a well.
		plane?: 'well' | 'surface';
		onchange?: (value: T) => void;
		class?: string;
	} = $props();

	// The pictures that failed to load, each tried once.
	let failed = $state<string[]>([]);

	function fail(url: string) {
		if (!failed.includes(url)) failed = [...failed, url];
	}

	// A picture that failed before the page took over never raises an error
	// event, so each one is asked when it mounts.
	function checkLoaded(img: HTMLImageElement, url: string) {
		if (img.complete && img.naturalWidth === 0) fail(url);
	}

	const tile = $derived(plane === 'well' ? 'bg-well' : 'bg-surface');
</script>

<div
	role="radiogroup"
	aria-label={label}
	class="grid grid-cols-1 gap-3 sm:grid-cols-[repeat(auto-fill,minmax(14rem,19rem))] {className}"
>
	{#each options as option (option.value)}
		{@const chosen = value === option.value}
		{@const picture = option.picture && !failed.includes(option.picture) ? option.picture : null}
		<label
			class="group relative isolate flex min-w-0 flex-col gap-3 rounded-control p-3 transition-colors has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-offset-2 has-[:focus-visible]:outline-primary {chosen
				? 'bg-primary-soft'
				: tile} {option.disabled ? 'cursor-default' : 'cursor-pointer'}"
		>
			{#if !option.disabled && !chosen}
				<span
					aria-hidden="true"
					class="pointer-events-none absolute inset-0 -z-10 rounded-control transition-colors group-hover:bg-hover group-active:bg-pressed"
				></span>
			{/if}
			<input
				type="radio"
				{name}
				value={option.value}
				checked={chosen}
				disabled={option.disabled}
				onchange={() => {
					value = option.value;
					onchange?.(option.value);
				}}
				class="sr-only"
			/>
			<span class="block aspect-4/3 w-full {option.disabled ? 'opacity-45' : ''}">
				{#if picture}
					<img
						src={picture}
						alt={option.alt ?? ''}
						loading="lazy"
						decoding="async"
						use:checkLoaded={picture}
						onerror={() => fail(picture)}
						class="block size-full object-contain"
					/>
				{:else}
					<span aria-hidden="true" class="block size-full rounded-item bg-hover"></span>
				{/if}
			</span>
			<span class="flex min-w-0 items-start gap-2.5">
				<span
					aria-hidden="true"
					class="relative mt-0.5 inline-flex size-4 shrink-0 rounded-radio border bg-field {chosen
						? 'border-primary'
						: 'border-line-strong'}"
				>
					{#if chosen}<span class="absolute inset-1 rounded-radio bg-primary"></span>{/if}
				</span>
				<span class="min-w-0">
					<span class="block text-sm font-medium {option.disabled ? 'text-ink-muted' : 'text-ink'}">
						{option.label}
					</span>
					{#if option.help}<span class="block text-sm text-ink-muted">{option.help}</span>{/if}
					{#if option.note}<span class="mt-1 block text-sm text-ink-muted">{option.note}</span>{/if}
				</span>
			</span>
		</label>
	{/each}
</div>
