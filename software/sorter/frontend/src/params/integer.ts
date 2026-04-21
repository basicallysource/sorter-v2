import type { ParamMatcher } from '@sveltejs/kit';

/**
 * Match a positive integer segment. Used to disambiguate
 * /tracked/[globalId=integer] (tracker record) from
 * /tracked/[uuid] (per-piece detail keyed by UUID).
 */
export const match: ParamMatcher = (param) => /^[0-9]+$/.test(param);
