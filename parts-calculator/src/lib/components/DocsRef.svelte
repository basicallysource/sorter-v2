<script lang="ts">
	import { tip } from '$lib/popover';
	// A documentation page named in the middle of a sentence, from a
	// `[[docs:<path>|<label>]]` token. It leaves this site, so it says so with
	// the same small arrow every other outbound link here gets from layout.css; otherwise it is
	// an ordinary underlined link, because in running prose a badge would
	// compete with the sentence.

	let { href, label }: { href: string; label: string } = $props();
</script>

<a
	class="docs-ref"
	{href}
	target="_blank"
	rel="noopener"
	use:tip={'Opens the documentation site'}>{label}</a
>

<style>
	.docs-ref {
		color: var(--color-primary);
		text-decoration: none;
		white-space: nowrap;
	}
	.docs-ref:hover,
	.docs-ref:focus-visible {
		text-decoration: underline;
	}
</style>
