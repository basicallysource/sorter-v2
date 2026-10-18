<!--
	docs/components.md#steps. One step of a guided task: a number, its name,
	a line under the name, and while it is open what to do and why. A task is
	an `ol` of steps (`divide-y divide-line`) in a flush Panel. A step is done
	(a check in the success tint; the line says what came of it), current (the
	number in the primary's tint, open) or locked (the number muted; the line
	says what to finish first). The app says which, and which is open; `actions`
	sit at the right of the name (a Badge, a "Change" button).
-->
<script lang="ts">
	import type { Snippet } from 'svelte';
	import Check from '@lucide/svelte/icons/check';

	type Status = 'locked' | 'current' | 'done';

	let {
		n,
		title,
		status,
		hint,
		open,
		actions,
		children
	}: {
		n: number;
		title: string;
		status: Status;
		// Under the name: the result of a done step, what a locked one waits for.
		hint?: string;
		// Shows the body. Only the current step is open unless the app says so.
		open?: boolean;
		actions?: Snippet;
		children?: Snippet;
	} = $props();

	const marks: Record<Status, string> = {
		done: 'bg-success-soft text-success-ink',
		current: 'bg-primary-soft text-primary-ink',
		locked: 'bg-well text-ink-muted'
	};
	const shown = $derived(open ?? status === 'current');
</script>

<li aria-current={status === 'current' ? 'step' : undefined} class="px-(--pad-panel) py-4">
	<div class="flex min-h-(--size-control-sm) items-center gap-3">
		<span
			aria-hidden="true"
			class="flex size-6 shrink-0 items-center justify-center rounded-badge text-sm font-medium {marks[
				status
			]}"
		>
			{#if status === 'done'}<Check size={14} />{:else}{n}{/if}
		</span>
		<h3
			class="min-w-0 flex-1 text-sm font-medium {status === 'locked'
				? 'text-ink-muted'
				: 'text-ink'}"
		>
			{#if status !== 'current'}<span class="sr-only"
					>{status === 'done' ? 'Done: ' : 'Locked: '}</span
				>{/if}{title}
		</h3>
		{#if actions}<div class="flex shrink-0 items-center gap-2">{@render actions()}</div>{/if}
	</div>
	{#if hint}<p class="pl-9 text-sm text-ink-muted">{hint}</p>{/if}
	{#if shown && children}
		<div class="mt-3 pl-9">{@render children()}</div>
	{/if}
</li>
