import "server-only";
import { headers } from "next/headers";
import { getToken } from "next-auth/jwt";
import { refreshAccessToken } from "./entra";

// Reads the signed-in user's API access token from the encrypted Auth.js cookie (server side only).
// The token is never placed in the session object, so /api/auth/session cannot leak it to the browser.
async function readJwt() {
  const secureCookie = (process.env.AUTH_URL ?? "").startsWith("https://") || process.env.NODE_ENV === "production";
  return getToken({ req: { headers: await headers() }, secureCookie });
}

// ID token from the latest interactive sign-in. Not refreshed on purpose: its auth_time must reflect a real MFA prompt.
export async function getIdToken(): Promise<string | null> {
  const jwt = await readJwt();
  return jwt?.id_token ? String(jwt.id_token) : null;
}

export async function getAccessToken(): Promise<string | null> {
  const jwt = await readJwt();
  if (!jwt?.access_token) return null;

  const expiresAt = Number(jwt.expires_at ?? 0);
  if (expiresAt * 1000 > Date.now() + 60_000) return String(jwt.access_token);

  // Expired: refresh inline for this request. The middleware persists a refreshed token on the next navigation.
  if (!jwt.refresh_token) return null;
  const refreshed = await refreshAccessToken(String(jwt.refresh_token));
  return refreshed?.access_token ?? null;
}
