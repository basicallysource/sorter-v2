<script lang="ts">
	import { PencilRuler } from 'lucide-svelte';

	let {
		label,
		isArc = false,
		statusMessage = ''
	}: {
		label: string;
		isArc?: boolean;
		statusMessage?: string;
	} = $props();
</script>

<aside
	class="dark:border-border-dark dark:bg-bg-dark flex h-full min-w-0 flex-col border border-border bg-bg xl:min-h-[32rem]"
>
	<div
		class="dark:border-border-dark dark:bg-surface-dark border-b border-border bg-surface px-4 py-3"
	>
		<div class="flex items-start gap-3">
			<div
				class="dark:bg-bg-dark dark:text-text-dark flex h-9 w-9 items-center justify-center rounded-full bg-bg text-text"
			>
				<PencilRuler size={16} />
			</div>
			<div class="min-w-0">
				<div class="dark:text-text-dark text-sm font-semibold text-text">Zone Editing</div>
				<p class="dark:text-text-muted-dark mt-1 text-xs leading-5 text-text-muted">
					Adjust the live detection zone for {label}. Changes stay local until you save them.
				</p>
			</div>
		</div>
	</div>

	<div class="flex flex-1 flex-col gap-4 px-4 py-4">
		{#if statusMessage}
			<div
				class={`border px-3 py-2 text-xs ${
					statusMessage.startsWith('Error:')
						? 'border-red-400 bg-red-50 text-red-600 dark:border-red-600 dark:bg-red-900/20 dark:text-red-400'
						: 'dark:border-border-dark dark:bg-surface-dark dark:text-text-muted-dark border-border bg-surface text-text-muted'
				}`}
			>
				{statusMessage}
			</div>
		{/if}

		<div class="dark:text-text-dark flex flex-col gap-3 text-sm text-text">
			<div class="font-medium">How to edit</div>
			{#if isArc}
				<div class="dark:text-text-muted-dark text-sm leading-6 text-text-muted">
					Drag the <span class="dark:text-text-dark font-medium text-text">Start</span>,
					<span class="dark:text-text-dark font-medium text-text">Center</span>,
					<span class="dark:text-text-dark font-medium text-text">Exit</span>,
					<span class="dark:text-text-dark font-medium text-text">Inner</span>, and
					<span class="dark:text-text-dark font-medium text-text">Outer</span> handles to reshape the
					arc.
				</div>
				<div class="dark:text-text-muted-dark text-sm leading-6 text-text-muted">
					Drag anywhere inside the highlighted zone to move the full arc as one piece.
				</div>
				<div class="dark:text-text-muted-dark text-sm leading-6 text-text-muted">
					Use the mouse wheel for fine radius scaling, and
					<span class="dark:text-text-dark font-medium text-text"> Shift+Click</span> to set the section-0
					reference.
				</div>
			{:else}
				<div class="dark:text-text-muted-dark text-sm leading-6 text-text-muted">
					Click to add polygon vertices and
					<span class="dark:text-text-dark font-medium text-text"> right-click</span> a point to remove
					it.
				</div>
				<div class="dark:text-text-muted-dark text-sm leading-6 text-text-muted">
					Drag inside the polygon to move the full zone, and use the mouse wheel to scale it.
				</div>
			{/if}
		</div>

		<div
			class="dark:border-border-dark dark:text-text-muted-dark mt-auto border-t border-border pt-4 text-xs text-text-muted"
		>
			Use the toolbar above the feed to
			<span class="dark:text-text-dark font-medium text-text">Save Zone</span>,
			<span class="dark:text-text-dark font-medium text-text">Cancel</span>, or
			<span class="dark:text-text-dark font-medium text-text">Reset</span>.
		</div>
	</div>
</aside>
