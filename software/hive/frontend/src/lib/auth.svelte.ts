import { api, setUnauthorizedHandler, type User, type ApiError } from './api';

let user = $state<User | null>(null);
let loading = $state(true);
let initialized = $state(false);

setUnauthorizedHandler(() => {
	user = null;
	loading = false;
	initialized = true;
});

export const auth = {
	get user() { return user; },
	set user(val: User | null) { user = val; },
	get loading() { return loading; },
	get initialized() { return initialized; },
	get isAuthenticated() { return user !== null; },
	// Reviewing is open to any logged-in user — the dedicated reviewer role
	// turned out to be unnecessary gatekeeping. The role column still exists
	// for future tightening, but for now any authenticated user can vote.
	get isReviewer() { return user !== null; },
	get isAdmin() { return user?.role === 'admin'; },

	async init() {
		if (initialized) return;
		loading = true;
		try {
			user = await api.me();
		} catch {
			user = null;
		} finally {
			loading = false;
			initialized = true;
		}
	},

	async login(email: string, password: string): Promise<string | null> {
		try {
			user = await api.login(email, password);
			return null;
		} catch (e) {
			const err = e as ApiError;
			return err.error || 'Login failed';
		}
	},

	async register(email: string, password: string, displayName: string): Promise<string | null> {
		try {
			user = await api.register(email, password, displayName);
			return null;
		} catch (e) {
			const err = e as ApiError;
			return err.error || 'Registration failed';
		}
	},

	async logout() {
		try {
			await api.logout();
		} catch {
			// ignore
		}
		user = null;
	},

	async deleteAccount(): Promise<string | null> {
		try {
			await api.deleteAccount();
			user = null;
			return null;
		} catch (e) {
			const err = e as ApiError;
			return err.error || 'Failed to delete account';
		}
	}
};
