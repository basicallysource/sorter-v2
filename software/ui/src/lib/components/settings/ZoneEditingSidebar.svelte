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
	class="flex h-full min-w-0 flex-col border border-border bg-bg xl:min-h-[32rem]"
>
	<div
		class="border-b border-border bg-surface px-4 py-3"
	>
		<div class="flex items-start gap-3">
			<div
				class="flex h-9 w-9 items-center justify-center rounded-full bg-bg text-text"
			>
				<PencilRuler size={16} />
			</div>
			<div class="min-w-0">
				<div class="text-sm font-semibold text-text">Zone Editing</div>
				<p class="mt-1 text-xs leading-5 text-text-muted">
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
						? 'border-[#D01012] bg-[#D01012]/10 text-[#D01012] dark:border-[#D01012] dark:bg-[#D01012]/10 dark:text-red-400'
						: 'border-border bg-surface text-text-muted'
				}`}
			>
				{statusMessage}
			</div>
		{/if}

		<div class="flex flex-col gap-3 text-sm text-text">
			<div class="font-medium">How to edit</div>
			{#if isArc}
				<div class="text-sm leading-6 text-text-muted">
					Drag the
					<span class="font-medium text-text">Drop Start</span>,
					<span class="font-medium text-text">Drop End</span>,
					<span class="font-medium text-text">Exit Start</span>,
					<span class="font-medium text-text">Exit End</span>,
					<span class="font-medium text-text">Center</span>,
					<span class="font-medium text-text">Inner</span>, and
					<span class="font-medium text-text">Outer</span> handles to shape the full
					ring and its angular zones.
				</div>
				<div class="text-sm leading-6 text-text-muted">
					Drag anywhere inside the ring to move the whole C-channel zone as one piece.
				</div>
				<div class="text-sm leading-6 text-text-muted">
					Use the mouse wheel for fine radius scaling, and
					<span class="font-medium text-text"> Shift+Click</span> to set the section-0
					reference.
				</div>
			{:else}
				<div class="text-sm leading-6 text-text-muted">
					Drag the four
					<span class="font-medium text-text">corner handles</span> to reshape the zone.
				</div>
				<div class="text-sm leading-6 text-text-muted">
					Drag inside the quad to move the full zone, and use the mouse wheel to scale it.
				</div>
			{/if}
		</div>

		<div
			class="mt-auto border-t border-border pt-4 text-xs text-text-muted"
		>
			Use the toolbar above the feed to
			<span class="font-medium text-text">Save Zone</span>,
			<span class="font-medium text-text">Cancel</span>, or
			<span class="font-medium text-text">Reset</span>.
		</div>
	</div>
</aside>
