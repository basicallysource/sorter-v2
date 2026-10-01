// A confirmation is the design system's Modal (docs/overlays.md): what will
// happen in a sentence, and a button that says the action, in danger when it
// destroys or stops something. `confirmDialog` resolves true on the action and
// false on Cancel, Escape or the close button; ConfirmHost draws it.
export type Confirmation = { title: string; message: string; action: string; danger?: boolean };

let current = $state<(Confirmation & { resolve: (ok: boolean) => void }) | null>(null);

export const confirmation = {
	get current() {
		return current;
	},
	settle(ok: boolean) {
		const pending = current;
		current = null;
		pending?.resolve(ok);
	}
};

export function confirmDialog(options: Confirmation): Promise<boolean> {
	return new Promise((resolve) => {
		current?.resolve(false);
		current = { ...options, resolve };
	});
}
