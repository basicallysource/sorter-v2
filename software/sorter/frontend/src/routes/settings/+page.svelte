<script lang="ts">
	import PageHeader from '$lib/components/ui/PageHeader.svelte';
	import Panel from '$lib/components/ui/Panel.svelte';
	import GeneralSection from '$lib/components/settings/GeneralSection.svelte';
	import ApiKeysSection from '$lib/components/settings/ApiKeysSection.svelte';
</script>

<svelte:head><title>Sorter - Settings</title></svelte:head>

<PageHeader title="General" description="This machine's name, its keys and the setup wizard." />

<GeneralSection />

<Panel title="OpenRouter" description="The key used for cloud-assisted detection.">
	<ApiKeysSection />
</Panel>
