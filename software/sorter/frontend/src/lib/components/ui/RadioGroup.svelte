<!--
	docs/components.md#forms. One choice from a few, when each needs a
	sentence to explain it. Short choices that apply at once are a
	SegmentedControl; a long list is a Select. The radios follow the corner
	tokens (square at 0, round otherwise) and fill with the primary when chosen.
-->
<script lang="ts" generics="T extends string">
	type Option = { value: T; label: string; help?: string; disabled?: boolean };

	let {
		value = $bindable(),
		options,
		name,
		label,
		onchange
	}: {
		value: T;
		options: Option[];
		// The inputs' shared name.
		name: string;
		// The group's accessible name.
		label: string;
		onchange?: (value: T) => void;
	} = $props();
</script>

<div role="radiogroup" aria-label={label} class="flex flex-col gap-3">
	{#each options as option (option.value)}
		<label
			class="flex gap-3 {option.disabled ? 'pointer-events-none opacity-45' : 'cursor-pointer'}"
		>
			<span class="relative mt-0.5 inline-flex size-4 shrink-0">
				<input
					type="radio"
					{name}
					value={option.value}
					disabled={option.disabled}
					bind:group={value}
					onchange={() => onchange?.(option.value)}
					class="peer size-4 cursor-pointer appearance-none rounded-radio border border-line-strong bg-field transition-colors checked:border-primary hover:border-ink-faint checked:hover:border-primary-hover"
				/>
				<span
					class="pointer-events-none absolute inset-1 rounded-radio bg-primary opacity-0 peer-checked:opacity-100"
				></span>
			</span>
			<span class="min-w-0">
				<span class="block text-sm font-medium text-ink">{option.label}</span>
				{#if option.help}<span class="block text-sm text-ink-muted">{option.help}</span>{/if}
			</span>
		</label>
	{/each}
</div>
