// Browser side of the encrypted LAN-IP rendezvous (portal half).
//
// The portal runs on plain http://10.42.0.1, where the browser disables
// crypto.subtle (WebCrypto needs a secure context). So the portal can ONLY
// mint a random id — crypto.getRandomValues works everywhere. The actual
// keypair is generated later on the Hive lookup page (https), which fetches
// the public key to the sorter and keeps the private key. The id is the
// unguessable capability that ties browser ↔ Hive ↔ sorter together.

export type Rendezvous = {
	id: string;
};

function b64url(bytes: Uint8Array): string {
	let bin = '';
	for (let i = 0; i < bytes.length; i++) bin += String.fromCharCode(bytes[i]);
	return btoa(bin).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

/** Mint a fresh random rendezvous id. Returns null only if getRandomValues
 *  is somehow unavailable (it isn't, in any real browser). */
export function createRendezvous(): Rendezvous | null {
	if (typeof crypto === 'undefined' || !crypto.getRandomValues) return null;
	const bytes = new Uint8Array(16);
	crypto.getRandomValues(bytes);
	return { id: b64url(bytes) };
}

/** The unlisted Hive lookup URL carrying just the id in the fragment. The
 *  fragment never reaches the Hive server. */
export function lookupUrl(hiveBaseUrl: string, r: Rendezvous): string {
	return `${hiveBaseUrl.replace(/\/+$/, '')}/machine-ip-lookup#id=${r.id}`;
}
