<!--
	docs/components.md#alert. The one shape for a message in the flow of a
	page: a tint of its tone, the tone's icon, a title and a sentence. The
	tint is the whole edge: no border, and never a colored stripe down one
	side. Severity is the tone, never the layout. With `onclose` it has a
	close button after its actions, for a message its reader may put away.
-->
<script lang="ts">
	import type { Snippet } from 'svelte';
	import Info from '@lucide/svelte/icons/info';
	import CircleCheck from '@lucide/svelte/icons/circle-check';
	import TriangleAlert from '@lucide/svelte/icons/triangle-alert';
	import OctagonAlert from '@lucide/svelte/icons/octagon-alert';
	import X from '@lucide/svelte/icons/x';
	import Button from './Button.svelte';

	type Tone = 'info' | 'success' | 'warning' | 'danger';

	let {
		tone = 'info',
		title,
		actions,
		onclose,
		closing = false,
		children,
		class: className = ''
	}: {
		tone?: Tone;
		title?: string;
		actions?: Snippet;
		// Given, the alert has a close button; `closing` while it is being closed.
		onclose?: () => void;
		closing?: boolean;
		children?: Snippet;
		class?: string;
	} = $props();

	const tones = {
		info: { box: 'bg-info-soft', ink: 'text-info-ink', icon: Info },
		success: { box: 'bg-success-soft', ink: 'text-success-ink', icon: CircleCheck },
		warning: { box: 'bg-warning-soft', ink: 'text-warning-ink', icon: TriangleAlert },
		danger: { box: 'bg-danger-soft', ink: 'text-danger-ink', icon: OctagonAlert }
	} as const;

	const t = $derived(tones[tone]);
</script>

<div
	role={tone === 'danger' || tone === 'warning' ? 'alert' : 'status'}
	class="flex items-start gap-3 rounded-control px-4 py-3 {t.box} {className}"
>
	<t.icon size={18} class="mt-px shrink-0 {t.ink}" />
	<div class="min-w-0 flex-1 text-sm">
		{#if title}<div class="font-semibold text-ink">{title}</div>{/if}
		{#if children}<div class="{title ? 'mt-0.5' : ''} text-ink">{@render children()}</div>{/if}
	</div>
	{#if actions || onclose}<div class="flex shrink-0 items-center gap-2 self-center">
			{#if actions}{@render actions()}{/if}
			{#if onclose}<Button
					variant="ghost"
					size="sm"
					icon={X}
					label="Close"
					loading={closing}
					onclick={onclose}
				/>{/if}
		</div>{/if}
</div>
