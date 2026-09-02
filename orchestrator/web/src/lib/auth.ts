// Control-plane token handling for the browser.
//
// The server requires a bearer token on every API route and both WebSockets.
// A browser cannot set headers on a WebSocket handshake, and the operator has
// to get the token into the page somehow, so the flow is the one Jupyter uses:
// the server logs a sign-in URL carrying ?token=..., the page stores it once,
// and the query parameter is stripped from the address bar so it does not sit
// in history or get copied into a shared link.

const STORAGE_KEY = 'clade.apiToken';

let cached: string | null = null;

/** Read ?token= out of the URL, persist it, and strip it from the address bar. */
export function bootstrapToken(): void {
  try {
    const url = new URL(window.location.href);
    const fromUrl = url.searchParams.get('token');
    if (fromUrl) {
      window.localStorage.setItem(STORAGE_KEY, fromUrl);
      cached = fromUrl;
      url.searchParams.delete('token');
      window.history.replaceState({}, '', url.toString());
    }
  } catch {
    // Private mode, blocked storage, or a non-browser context. The app still
    // renders; requests will surface a 401 the user can act on.
  }
}

export function getToken(): string {
  if (cached !== null) return cached;
  try {
    cached = window.localStorage.getItem(STORAGE_KEY) ?? '';
  } catch {
    cached = '';
  }
  return cached;
}

export function setToken(token: string): void {
  cached = token;
  try {
    window.localStorage.setItem(STORAGE_KEY, token);
  } catch {
    // Non-persistent fallback: the in-memory copy still serves this tab.
  }
}

/** Authorization header for fetch, or nothing when no token is stored yet. */
export function authHeaders(): Record<string, string> {
  const token = getToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

/** Append the token to a WebSocket URL — the handshake carries no headers. */
export function withToken(url: string): string {
  const token = getToken();
  if (!token) return url;
  const separator = url.includes('?') ? '&' : '?';
  return `${url}${separator}token=${encodeURIComponent(token)}`;
}
