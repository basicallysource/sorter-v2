<script lang="ts">
import GeneralSection from '$lib/components/settings/GeneralSection.svelte';
import RuntimeVarsSection from '$lib/components/settings/RuntimeVarsSection.svelte';
import ApiKeysSection from '$lib/components/settings/ApiKeysSection.svelte';
import SortHiveSection from '$lib/components/settings/SortHiveSection.svelte';
import SectionCard from '$lib/components/settings/SectionCard.svelte';
</script>

<div class="flex flex-col gap-6">
	<SectionCard
		title="Connection & Appearance"
		description="Connect to a machine, manage existing sessions, and set the UI theme."
	>
		<GeneralSection />
	</SectionCard>

	<SectionCard
		title="SortHive"
		description="Connect this sorter to SortHive for registration, uploads, and backfill of archived samples."
	>
		<SortHiveSection />
	</SectionCard>

	<SectionCard
		title="OpenRouter"
		description="Configure the OpenRouter key used for cloud-assisted detection."
	>
		<ApiKeysSection />
	</SectionCard>

	<SectionCard
		title="Runtime Variables"
		description="Adjust live backend tunables that are exposed for the current machine."
	>
		<RuntimeVarsSection />
	</SectionCard>
</div>
