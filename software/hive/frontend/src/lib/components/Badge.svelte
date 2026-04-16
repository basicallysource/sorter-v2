<script lang="ts">
	interface Props {
		text: string;
		variant?: 'success' | 'warning' | 'danger' | 'info' | 'neutral';
	}

	let { text, variant = 'neutral' }: Props = $props();

	const colors: Record<string, string> = {
		success: 'border border-success/30 bg-success/10 text-success',
		warning: 'border border-warning/30 bg-warning/15 text-[#A16207]',
		danger: 'border border-primary/30 bg-primary/8 text-primary',
		info: 'border border-info/30 bg-info/8 text-info',
		neutral: 'border border-border bg-bg text-text-muted'
	};

	function formatText(value: string): string {
		return value.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
	}
</script>

<span class="inline-flex items-center px-2.5 py-0.5 text-xs font-medium {colors[variant]}">
	{formatText(text)}
</span>
