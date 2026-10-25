// Entra ID token endpoint helpers. Issuer looks like https://login.microsoftonline.com/<tenant>/v2.0
export function tokenEndpoint(): string {
  const issuer = (process.env.AUTH_MICROSOFT_ENTRA_ID_ISSUER ?? "").replace(/\/v2\.0\/?$/, "");
  return `${issuer}/oauth2/v2.0/token`;
}

export function apiScope(): string {
  return process.env.PLATFORM_API_SCOPE ?? "";
}

export interface RefreshedToken {
  access_token: string;
  expires_at: number;
  refresh_token?: string;
}

export async function refreshAccessToken(refreshToken: string): Promise<RefreshedToken | null> {
  const res = await fetch(tokenEndpoint(), {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({
      client_id: process.env.AUTH_MICROSOFT_ENTRA_ID_ID ?? "",
      client_secret: process.env.AUTH_MICROSOFT_ENTRA_ID_SECRET ?? "",
      grant_type: "refresh_token",
      refresh_token: refreshToken,
      scope: `openid profile offline_access ${apiScope()}`.trim(),
    }),
    cache: "no-store",
  });
  if (!res.ok) return null;
  const data = await res.json();
  return {
    access_token: data.access_token,
    expires_at: Math.floor(Date.now() / 1000) + Number(data.expires_in ?? 3600),
    refresh_token: data.refresh_token,
  };
}
