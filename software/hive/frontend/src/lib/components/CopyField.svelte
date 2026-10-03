<!--
	docs/components.md#fields. Something to copy, shown whole: a key, a token,
	a message with one in it. Laid out like a Field: a label above, then the
	text in a well with one Copy button at its edge, then one sentence under
	it. The button copies the text and says Copied for a moment; where the page
	cannot write to the clipboard (a plain http address), it selects the text
	instead, so Cmd or Ctrl C copies it, and says Selected.

	`mono` sets a bare token in monospace, broken anywhere; a sentence breaks
	at its spaces. `children` shows the text with parts of it marked (the
	address and the key in a message, say); `value` is still what is copied.
	`note` is the sentence under it: a secret shown only once says so there,
	quietly, never in a warning. `name` is what the button copies, for its
	accessible name ("Copy the API key").

	<CopyField label="API key" name="API key" value={token} mono note="Shown only now." />
-->
<script lang="ts">
	import type { Snippet } from 'svelte';
	import Check from '@lucide/svelte/icons/check';
	import Copy from '@lucide/svelte/icons/copy';
	import Button from './Button.svelte';

	let {
		value,
		label,
		name,
		note,
		mono = false,
		children,
		oncopy,
		class: className = ''
	}: {
		// What is copied.
		value: string;
		// Above the well, like a field's label.
		label?: string;
		// What the button copies, for its accessible name; the label when not given.
		name?: string;
		// One sentence under the well.
		note?: string;
		mono?: boolean;
		// How the text is shown, when not as it is copied.
		children?: Snippet;
		oncopy?: () => void;
		class?: string;
	} = $props();

	const id = $props.id();
	let text = $state<HTMLElement | null>(null);
	let outcome = $state<'idle' | 'copied' | 'selected'>('idle');
	let timer: ReturnType<typeof setTimeout> | undefined;

	async function write(): Promise<boolean> {
		try {
			if (navigator.clipboard && window.isSecureContext) {
				await navigator.clipboard.writeText(value);
				return true;
			}
		} catch {
			// fall through to the older way
		}
		const area = document.createElement('textarea');
		area.value = value;
		area.setAttribute('readonly', '');
		area.style.position = 'fixed';
		area.style.opacity = '0';
		document.body.appendChild(area);
		area.select();
		let done = false;
		try {
			done = document.execCommand('copy');
		} catch {
			done = false;
		}
		area.remove();
		return done;
	}

	async function copy() {
		clearTimeout(timer);
		if (await write()) {
			outcome = 'copied';
			oncopy?.();
		} else if (text) {
			const range = document.createRange();
			range.selectNodeContents(text);
			const selection = window.getSelection();
			selection?.removeAllRanges();
			selection?.addRange(range);
			outcome = 'selected';
		}
		timer = setTimeout(() => (outcome = 'idle'), outcome === 'selected' ? 6000 : 2000);
	}

	$effect(() => () => clearTimeout(timer));
</script>

<div role="group" aria-labelledby={label ? `${id}-label` : undefined} class="flex flex-col gap-1.5 {className}">
	{#if label}
		<div id="{id}-label" class="text-sm font-medium text-ink">{label}</div>
	{/if}
	<div class="flex items-start gap-3 rounded-control bg-well py-2 pr-2 pl-3">
		<div
			bind:this={text}
			class="min-w-0 flex-1 py-1 text-sm text-ink select-all {mono ? 'font-mono break-all' : 'break-words'}"
		>
			{#if children}{@render children()}{:else}{value}{/if}
		</div>
		<Button
			size="sm"
			variant="secondary"
			icon={outcome === 'copied' ? Check : Copy}
			aria-label={outcome === 'idle' ? `Copy the ${name ?? label ?? 'text'}` : undefined}
			onclick={copy}
			class="shrink-0"
		>
			{outcome === 'copied' ? 'Copied' : outcome === 'selected' ? 'Selected' : 'Copy'}
		</Button>
	</div>
	{#if note}<p class="text-sm text-ink-muted">{note}</p>{/if}
</div>
