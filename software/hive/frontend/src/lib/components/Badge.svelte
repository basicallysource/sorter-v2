<script lang="ts">
	interface Props {
		text: string;
		variant?: 'success' | 'warning' | 'danger' | 'info' | 'neutral';
	}

	let { text, variant = 'neutral' }: Props = $props();

	const colors: Record<string, string> = {
		success: 'border border-[#00852B]/30 bg-[#00852B]/10 text-[#00852B]',
		warning: 'border border-[#FFD500]/30 bg-[#FFD500]/15 text-[#A16207]',
		danger: 'border border-[#D01012]/30 bg-[#D01012]/8 text-[#D01012]',
		info: 'border border-[#0055BF]/30 bg-[#0055BF]/8 text-[#0055BF]',
		neutral: 'border border-[#E2E0DB] bg-[#F7F6F3] text-[#7A7770]'
	};

	function formatText(value: string): string {
		return value.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
	}
</script>

<span class="inline-flex items-center px-2.5 py-0.5 text-xs font-medium {colors[variant]}">
	{formatText(text)}
</span>
