// Browser side of the encrypted LAN-IP rendezvous.
//
// We generate an RSA-OAEP keypair in the browser. The PUBLIC key goes to the
// Pi (it encrypts its LAN IP with it). The PRIVATE key never leaves the
// browser — it rides along in the Hive lookup URL's fragment so the lookup
// page (a different origin) can decrypt. Hive only ever relays ciphertext.

export type Rendezvous = {
	id: string;
	publicKeyB64: string; // SPKI DER, base64 — sent to the Pi
	privateKeyB64url: string; // PKCS8 DER, base64url — carried in the URL fragment
};

function bytesToB64(bytes: ArrayBuffer): string {
	const arr = new Uint8Array(bytes);
	let bin = '';
	for (let i = 0; i < arr.length; i++) bin += String.fromCharCode(arr[i]);
	return btoa(bin);
}

function b64ToB64url(b64: string): string {
	return b64.replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

function randomId(): string {
	const bytes = new Uint8Array(16);
	crypto.getRandomValues(bytes);
	let bin = '';
	for (let i = 0; i < bytes.length; i++) bin += String.fromCharCode(bytes[i]);
	return b64ToB64url(btoa(bin));
}

/**
 * Generate a fresh rendezvous keypair + id. Returns null when WebCrypto's
 * subtle API is unavailable (e.g. an insecure non-localhost http origin) —
 * the caller then falls back to the .local-only handoff.
 */
export async function createRendezvous(): Promise<Rendezvous | null> {
	if (typeof crypto === 'undefined' || !crypto.subtle) return null;
	try {
		const pair = await crypto.subtle.generateKey(
			{
				name: 'RSA-OAEP',
				modulusLength: 2048,
				publicExponent: new Uint8Array([1, 0, 1]),
				hash: 'SHA-256'
			},
			true,
			['encrypt', 'decrypt']
		);
		const spki = await crypto.subtle.exportKey('spki', pair.publicKey);
		const pkcs8 = await crypto.subtle.exportKey('pkcs8', pair.privateKey);
		return {
			id: randomId(),
			publicKeyB64: bytesToB64(spki),
			privateKeyB64url: b64ToB64url(bytesToB64(pkcs8))
		};
	} catch {
		return null;
	}
}

/** Build the unlisted Hive lookup URL carrying id + private key in the fragment. */
export function lookupUrl(hiveBaseUrl: string, r: Rendezvous): string {
	const base = hiveBaseUrl.replace(/\/+$/, '');
	return `${base}/machine-ip-lookup#id=${r.id}&k=${r.privateKeyB64url}`;
}
