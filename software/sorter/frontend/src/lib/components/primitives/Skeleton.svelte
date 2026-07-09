<script lang="ts">
	// General-purpose loading placeholder: a sharp-edged gray block that pulses
	// until the real content replaces it. Size it from the call site via class
	// (h-*, w-*, aspect-*); it has no intrinsic dimensions of its own.
	let { class: className = '' }: { class?: string } = $props();
</script>

<div class="animate-pulse bg-[#E8E6E1] {className}" aria-hidden="true"></div>
