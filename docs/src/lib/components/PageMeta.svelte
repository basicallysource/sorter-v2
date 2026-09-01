<script lang="ts">
	import type { Frontmatter } from '$lib/server/content';

	let { fm }: { fm: Frontmatter } = $props();

	const show = $derived(
		fm.type != null &&
			fm.type !== 'landing' &&
			(fm.audience != null || fm.applies_to != null || fm.last_verified != null)
	);
</script>

{#if show}
	<aside class="page-meta" aria-label="Page metadata">
		<dl>
			{#if fm.audience}
				<div><dt>Audience</dt><dd>{fm.audience}</dd></div>
			{/if}
			{#if fm.applies_to}
				<div><dt>Applies to</dt><dd>{fm.applies_to}</dd></div>
			{/if}
			{#if fm.last_verified}
				<div><dt>Last verified</dt><dd>{fm.last_verified}</dd></div>
			{/if}
			{#if fm.owner}
				<div><dt>Owner</dt><dd>{fm.owner}</dd></div>
			{/if}
		</dl>
	</aside>
{/if}
