<script lang="ts">
	interface Props {
		text: string;
		variant?: 'success' | 'warning' | 'danger' | 'info' | 'neutral';
	}

	let { text, variant = 'neutral' }: Props = $props();

	const colors: Record<string, string> = {
		success: 'bg-emerald-50 text-[#00852B]',
		warning: 'bg-amber-50 text-amber-800',
		danger: 'bg-[#FEF2F2] text-[#9B1D20]',
		info: 'bg-sky-50 text-[#0055BF]',
		neutral: 'bg-gray-100 text-gray-800'
	};

	function formatText(value: string): string {
		return value.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
	}
</script>

<span class="inline-flex items-center px-2.5 py-0.5 text-xs font-medium {colors[variant]}">
	{formatText(text)}
</span>
