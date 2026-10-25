import NextAuth from "next-auth";
import MicrosoftEntraID from "next-auth/providers/microsoft-entra-id";

// Multi-tenant app restricted to the client's tenant(s). The backend checks the tenant again on every call.
const allowed = (process.env.ALLOWED_TENANTS ?? "").split(",").map((t) => t.trim()).filter(Boolean);

export const { handlers, auth, signIn, signOut } = NextAuth({
  providers: [
    MicrosoftEntraID({
      clientId: process.env.ENTRA_CLIENT_ID,
      clientSecret: process.env.ENTRA_CLIENT_SECRET,
      issuer: `https://login.microsoftonline.com/${allowed[0] ?? "organizations"}/v2.0`,
      authorization: { params: { scope: `openid profile offline_access api://${process.env.ENTRA_CLIENT_ID}/access_as_user` } },
    }),
  ],
  callbacks: {
    async signIn({ profile }) {
      return allowed.includes(String((profile as { tid?: string })?.tid ?? ""));
    },
    async jwt({ token, account }) {
      if (account?.access_token) token.accessToken = account.access_token;
      return token;
    },
    async session({ session, token }) {
      return { ...session, accessToken: token.accessToken as string | undefined };
    },
  },
});
