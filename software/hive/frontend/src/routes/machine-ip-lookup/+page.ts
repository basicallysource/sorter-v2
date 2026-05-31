// Client-only: the page reads keys from the URL fragment and uses WebCrypto,
// neither of which exists during SSR.
export const ssr = false;
