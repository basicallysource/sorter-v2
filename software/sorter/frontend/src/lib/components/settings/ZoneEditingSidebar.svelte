<script lang="ts">
	import PencilRuler from '@lucide/svelte/icons/pencil-ruler';

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

<aside class="flex h-full min-w-0 flex-col border border-line bg-well xl:min-h-[32rem]">
	<div class="border-b border-line bg-surface px-4 py-3">
		<div class="flex items-start gap-3">
			<div class="flex h-9 w-9 items-center justify-center rounded-full bg-well text-ink">
				<PencilRuler size={16} />
			</div>
			<div class="min-w-0">
				<div class="text-sm font-semibold text-ink">Zone Editing</div>
				<p class="mt-1 text-xs leading-5 text-ink-muted">
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
						? 'border-danger bg-danger-soft text-danger-ink'
						: 'border-line bg-surface text-ink-muted'
				}`}
			>
				{statusMessage}
			</div>
		{/if}

		<div class="flex flex-col gap-3 text-sm text-ink">
			<div class="font-medium">How to edit</div>
			{#if isArc}
				<div class="text-sm leading-6 text-ink-muted">
					Drag the
					<span class="font-medium text-ink">Drop Start</span>,
					<span class="font-medium text-ink">Drop End</span>,
					<span class="font-medium text-ink">Exit Start</span>,
					<span class="font-medium text-ink">Exit End</span>,
					<span class="font-medium text-ink">Center</span>,
					<span class="font-medium text-ink">Inner</span>, and
					<span class="font-medium text-ink">Outer</span> handles to shape the full ring and its angular
					zones.
				</div>
				<div class="text-sm leading-6 text-ink-muted">
					Drag the purple <span class="font-medium text-ink">Precise Start</span> and
					<span class="font-medium text-ink">Precise End</span> handles to set the
					<span class="font-medium text-ink">holding region</span> — the band just before the exit where
					a piece waits while it is classified and the chute aims.
				</div>
				<div class="text-sm leading-6 text-ink-muted">
					Use <span class="font-medium text-ink">Exit Outer</span> to pull only the exit edge inward
					when the opening exposes the next plate.
				</div>
				<div class="text-sm leading-6 text-ink-muted">
					Drag anywhere inside the ring to move the whole C-channel zone as one piece.
				</div>
				<div class="text-sm leading-6 text-ink-muted">
					Use the mouse wheel for fine radius scaling, and
					<span class="font-medium text-ink"> Shift+Click</span> to set the section-0 reference.
				</div>
			{:else}
				<div class="text-sm leading-6 text-ink-muted">
					Drag the four
					<span class="font-medium text-ink">corner handles</span> to reshape the zone.
				</div>
				<div class="text-sm leading-6 text-ink-muted">
					Drag inside the quad to move the full zone, and use the mouse wheel to scale it.
				</div>
			{/if}
		</div>

		<div class="mt-auto border-t border-line pt-4 text-xs text-ink-muted">
			Use the toolbar above the feed to
			<span class="font-medium text-ink">Save Zone</span>,
			<span class="font-medium text-ink">Cancel</span>, or
			<span class="font-medium text-ink">Reset</span>.
		</div>
	</div>
</aside>
