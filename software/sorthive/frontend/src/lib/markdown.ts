import { marked } from 'marked';
import sanitizeHtml from 'sanitize-html';

const SANITIZE_OPTIONS: sanitizeHtml.IOptions = {
	allowedTags: [
		...sanitizeHtml.defaults.allowedTags,
		'h1',
		'h2',
		'h3',
		'h4',
		'h5',
		'h6',
		'table',
		'thead',
		'tbody',
		'tfoot',
		'tr',
		'th',
		'td',
		'hr'
	],
	allowedAttributes: {
		...sanitizeHtml.defaults.allowedAttributes,
		a: ['href', 'name', 'target', 'rel'],
		code: ['class'],
		th: ['colspan', 'rowspan', 'align'],
		td: ['colspan', 'rowspan', 'align']
	},
	transformTags: {
		a: sanitizeHtml.simpleTransform('a', {
			target: '_blank',
			rel: 'noopener noreferrer'
		})
	}
};

export function renderMarkdown(content: string | null | undefined): string {
	if (!content) return '';
	const html = marked.parse(content, {
		gfm: true,
		breaks: true
	}) as string;
	return sanitizeHtml(html, SANITIZE_OPTIONS);
}
