<script lang="ts">
	interface Props {
		text: string;
		variant?: 'success' | 'warning' | 'danger' | 'info' | 'neutral';
	}

	let { text, variant = 'neutral' }: Props = $props();

	const colors: Record<string, string> = {
		success: 'bg-[#00852B]/10 text-[#00852B]',
		warning: 'bg-[#FFD500]/15 text-[#A16207]',
		danger: 'bg-[#D01012]/8 text-[#D01012]',
		info: 'bg-[#0055BF]/8 text-[#0055BF]',
		neutral: 'bg-[#F7F6F3] text-[#1A1A1A]'
	};

	function formatText(value: string): string {
		return value.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
	}
</script>

<span class="inline-flex items-center px-2.5 py-0.5 text-xs font-medium {colors[variant]}">
	{formatText(text)}
</span>
