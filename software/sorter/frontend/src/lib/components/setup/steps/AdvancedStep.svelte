<script lang="ts">
	import { Check } from 'lucide-svelte';
</script>

<div
	class="setup-panel relative overflow-hidden border-success/40 bg-gradient-to-br from-[#EAF7EE] via-[#F3FBF5] to-white px-8 py-10 text-center dark:from-[#0F2B18] dark:via-[#0B1F12] dark:to-bg"
>
	<div class="mx-auto flex max-w-xl flex-col items-center gap-4">
		<div class="flex h-20 w-20 items-center justify-center rounded-full bg-success text-white">
			<Check size={44} strokeWidth={3} />
		</div>
		<div class="flex flex-col gap-2">
			<div class="text-2xl font-bold text-text">Setup Complete!</div>
			<div class="text-sm text-text-muted">
				Your sorter is configured and ready to go. Open the dashboard, home the machine if it's
				still in standby, and give it a first run.
			</div>
		</div>
	</div>
</div>
