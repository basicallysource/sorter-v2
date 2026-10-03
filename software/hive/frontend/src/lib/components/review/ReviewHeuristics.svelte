<script lang="ts">
	import { FEATURES } from '$lib/features';
	import Badge from '$lib/components/Badge.svelte';
	import Panel from '$lib/components/Panel.svelte';
</script>

<Panel title="Good training data" description="Accept only pictures where every LEGO part in view has a box, or a corrected one." flush>
	<dl class="divide-y divide-line border-t border-line">
		{#snippet rule(tone: 'success' | 'info' | 'danger', name: string, text: string)}
			<div class="flex flex-col gap-1 px-(--pad-panel) py-2.5">
				<dt><Badge {tone}>{name}</Badge></dt>
				<dd class="text-sm text-ink">{text}</dd>
			</div>
		{/snippet}
		{@render rule('success', 'Accept', 'Every part in view is boxed, and the boxes fit the pieces well enough to train on.')}
		{@render rule(
			'success',
			'Accept an empty one too',
			'An empty frame (a clear C-channel, an empty carousel) teaches the detector what nothing looks like; accept it when there really is nothing to box.'
		)}
		{#if FEATURES.ANNOTATION_EDITING}
			{@render rule('info', 'Annotate first', 'If parts are missing, split wrongly or boxed badly, fix the boxes before you accept.')}
		{/if}
		{@render rule('danger', 'Reject', 'Anything still incomplete or unreliable: parts in view that cannot be boxed cleanly enough to train on.')}
	</dl>
</Panel>
