<script lang="ts">
	import { Alert } from '$lib/components/primitives';

	let { message }: { message: string } = $props();

	// Backend errors arrive as the raw response body — usually FastAPI's
	// {"detail": "..."} JSON. Show just the detail when it's a plain string;
	// otherwise (validation lists, non-JSON, etc.) fall back to the raw text.
	function humanize(raw: string): string {
		try {
			const parsed = JSON.parse(raw);
			if (parsed && typeof parsed.detail === 'string') return parsed.detail;
		} catch {
			// not JSON — show as-is
		}
		return raw;
	}

	const text = $derived(humanize(message));
</script>

<Alert variant="danger">{text}</Alert>
