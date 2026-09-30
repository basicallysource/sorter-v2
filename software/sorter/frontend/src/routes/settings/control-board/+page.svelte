<script lang="ts">
	import ControlBoardSection from '$lib/components/settings/ControlBoardSection.svelte';
	import PageHeader from '$lib/components/ui/PageHeader.svelte';
</script>

<svelte:head><title>Sorter - Control board</title></svelte:head>

<PageHeader title="Control board" description="The machine's control boards and their firmware." />
<ControlBoardSection />
