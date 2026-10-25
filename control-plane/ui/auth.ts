import NextAuth from "next-auth";
import MicrosoftEntraID from "next-auth/providers/microsoft-entra-id";
import { apiScope, refreshAccessToken } from "@/lib/entra";

export const PROVIDER_ID = "microsoft-entra-id";

export const { handlers, auth, signIn, signOut } = NextAuth({
  trustHost: true,
  session: { strategy: "jwt", maxAge: 8 * 60 * 60 },
  providers: [
    MicrosoftEntraID({
      clientId: process.env.AUTH_MICROSOFT_ENTRA_ID_ID,
      clientSecret: process.env.AUTH_MICROSOFT_ENTRA_ID_SECRET,
      issuer: process.env.AUTH_MICROSOFT_ENTRA_ID_ISSUER,
      authorization: {
        params: { scope: `openid profile email offline_access ${apiScope()}`.trim() },
      },
    }),
  ],
  pages: { signIn: "/signin" },
  callbacks: {
    async jwt({ token, account }) {
      if (account) {
        // First sign-in or step-up: keep the API access token in the encrypted cookie only.
        return {
          ...token,
          access_token: account.access_token,
          refresh_token: account.refresh_token,
          expires_at: account.expires_at,
          // The ID token proves a fresh MFA sign-in for step-up actions (sent as X-Step-Up-Token).
          id_token: account.id_token,
        };
      }
      if (Number(token.expires_at ?? 0) * 1000 > Date.now() + 60_000) return token;
      if (!token.refresh_token) return { ...token, error: "RefreshTokenMissing" };
      const refreshed = await refreshAccessToken(String(token.refresh_token));
      if (!refreshed) return { ...token, error: "RefreshTokenError" };
      return {
        ...token,
        access_token: refreshed.access_token,
        expires_at: refreshed.expires_at,
        refresh_token: refreshed.refresh_token ?? token.refresh_token,
        error: undefined,
      };
    },
    async session({ session, token }) {
      // Deliberately does not copy access_token or refresh_token into the session.
      return { ...session, error: token.error as string | undefined };
    },
  },
});
