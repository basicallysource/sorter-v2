declare global {
	namespace App {}
}

declare module '*.md?raw' {
	const content: string;
	export default content;
}

export {};
