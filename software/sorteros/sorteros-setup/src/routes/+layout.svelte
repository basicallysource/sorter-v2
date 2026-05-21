<script lang="ts">
    import '../app.css';
    import { onMount } from 'svelte';

    let { children } = $props();

    onMount(() => {
        document.documentElement.className = 'light';
    });
</script>

{@render children?.()}
