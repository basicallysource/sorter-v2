<!--
	docs/components.md#select. One choice from a list, in our own list rather
	than the browser's, so it looks like the rest of the page on every
	system. The button is drawn as a field; the list floats under it, on the
	raised plane. From the keyboard: Enter, Space or the arrows open it, the
	arrows, Home and End move, typing jumps to the first match, Enter chooses,
	Escape and Tab close. A click outside closes it too.
-->
<script lang="ts" generics="T extends string">
	import Check from '@lucide/svelte/icons/check';
	import ChevronDown from '@lucide/svelte/icons/chevron-down';
	import { place } from './place';

	type Option = { value: T; label: string; hint?: string; disabled?: boolean };

	let {
		value = $bindable(),
		options,
		id,
		label,
		placeholder = 'Choose',
		size = 'md',
		disabled = false,
		invalid = false,
		class: className = '',
		onchange
	}: {
		value?: T;
		options: Option[];
		// For a <label for>; the list gets its own id from it.
		id?: string;
		// The accessible name when no <label> points at it.
		label?: string;
		placeholder?: string;
		size?: 'sm' | 'md';
		disabled?: boolean;
		invalid?: boolean;
		class?: string;
		onchange?: (value: T) => void;
	} = $props();

	const uid = Math.random().toString(36).slice(2, 9);
	const listId = $derived(`${id ?? 'select'}-list-${uid}`);
	let trigger: HTMLButtonElement;
	let list: HTMLElement;
	let open = $state(false);
	let active = $state(-1);
	let typed = '';
	let typedAt = 0;

	const chosen = $derived(options.find((o) => o.value === value));

	function optionId(i: number) {
		return `${listId}-${i}`;
	}

	function enabled(i: number) {
		return i >= 0 && i < options.length && !options[i].disabled;
	}

	function step(from: number, by: number) {
		for (let i = from + by; i >= 0 && i < options.length; i += by) if (enabled(i)) return i;
		return from;
	}

	function ontoggle(event: ToggleEvent) {
		open = event.newState === 'open';
		if (!open) return;
		const box = trigger.getBoundingClientRect();
		list.style.minWidth = `${box.width}px`;
		const at = place(box, list.getBoundingClientRect(), 'bottom-start', 4);
		list.style.top = `${at.top}px`;
		list.style.left = `${at.left}px`;
		active = Math.max(
			options.findIndex((o) => o.value === value),
			step(-1, 1)
		);
		list.focus();
		scrollToActive();
	}

	function scrollToActive() {
		requestAnimationFrame(() =>
			document.getElementById(optionId(active))?.scrollIntoView({ block: 'nearest' })
		);
	}

	function choose(i: number) {
		if (!enabled(i)) return;
		value = options[i].value;
		onchange?.(options[i].value);
		list.hidePopover();
		trigger.focus();
	}

	function onTriggerKey(event: KeyboardEvent) {
		if (['ArrowDown', 'ArrowUp'].includes(event.key)) {
			event.preventDefault();
			list.showPopover();
		}
	}

	function onListKey(event: KeyboardEvent) {
		const moves: Record<string, () => number> = {
			ArrowDown: () => step(active, 1),
			ArrowUp: () => step(active, -1),
			Home: () => step(-1, 1),
			End: () => step(options.length, -1)
		};
		if (event.key in moves) {
			event.preventDefault();
			active = moves[event.key]();
			scrollToActive();
		} else if (event.key === 'Enter' || event.key === ' ') {
			event.preventDefault();
			choose(active);
		} else if (event.key === 'Tab') {
			list.hidePopover();
		} else if (event.key.length === 1 && /\S/.test(event.key)) {
			// Type-ahead: the typed letters so far, reset after a pause.
			const now = Date.now();
			typed = now - typedAt > 600 ? event.key : typed + event.key;
			typedAt = now;
			const match = options.findIndex(
				(o, i) => enabled(i) && o.label.toLowerCase().startsWith(typed.toLowerCase())
			);
			if (match >= 0) {
				active = match;
				scrollToActive();
			}
		}
	}
</script>

<button
	bind:this={trigger}
	type="button"
	{id}
	{disabled}
	popovertarget={listId}
	aria-haspopup="listbox"
	aria-expanded={open}
	aria-controls={listId}
	aria-label={label}
	onkeydown={onTriggerKey}
	class="inline-flex w-full min-w-0 items-center justify-between gap-2 rounded-control border bg-field text-left text-sm transition-colors disabled:pointer-events-none disabled:opacity-45
		{invalid
		? 'border-danger outline-2 -outline-offset-1 outline-danger'
		: open
			? 'border-primary outline-2 -outline-offset-1 outline-primary'
			: 'border-line-strong hover:border-ink-faint'}
		{size === 'sm'
		? 'h-(--size-control-sm) pr-2 pl-(--pad-control-sm)'
		: 'h-(--size-control) pr-2.5 pl-(--pad-control)'} {className}"
>
	<span class="min-w-0 truncate {chosen ? 'text-ink' : 'text-ink-faint'}">
		{chosen?.label ?? placeholder}
	</span>
	<ChevronDown
		size={16}
		class="shrink-0 text-ink-muted transition-transform {open ? 'rotate-180' : ''}"
	/>
</button>

<div
	bind:this={list}
	id={listId}
	popover="auto"
	role="listbox"
	tabindex="-1"
	aria-label={label}
	aria-activedescendant={active >= 0 ? optionId(active) : undefined}
	{ontoggle}
	onkeydown={onListKey}
	class="fixed inset-auto m-0 max-h-72 max-w-[calc(100vw-1rem)] overflow-y-auto rounded-control border border-line bg-raised p-1 text-sm text-ink outline-none"
>
	{#each options as option, i (option.value)}
		{@const on = option.value === value}
		<div
			id={optionId(i)}
			role="option"
			aria-selected={on}
			aria-disabled={option.disabled || undefined}
			tabindex="-1"
			onpointermove={() => enabled(i) && (active = i)}
			onclick={() => choose(i)}
			onkeydown={() => {}}
			class="flex h-(--size-menu-item) cursor-pointer items-center gap-2 rounded-item pr-3 pl-2 whitespace-nowrap
				{i === active ? 'bg-hover' : ''} {option.disabled ? 'pointer-events-none opacity-45' : ''}"
		>
			<Check size={16} class="shrink-0 text-primary-ink {on ? '' : 'invisible'}" />
			<span class="min-w-0 flex-1 truncate {on ? 'font-medium' : ''}">{option.label}</span>
			{#if option.hint}<span class="shrink-0 text-xs text-ink-faint">{option.hint}</span>{/if}
		</div>
	{/each}
</div>
