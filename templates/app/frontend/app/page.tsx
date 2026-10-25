import { auth, signIn } from "@/auth";

// Server component: the browser never calls the backend directly; BACKEND_URL is internal to Azure.
export default async function Home() {
  const session = (await auth()) as { accessToken?: string } | null;
  if (!session?.accessToken) {
    return (
      <form action={async () => { "use server"; await signIn("microsoft-entra-id"); }}>
        <button type="submit">Sign in with Microsoft</button>
      </form>
    );
  }
  const res = await fetch(`${process.env.BACKEND_URL}/api/me`, {
    headers: { Authorization: `Bearer ${session.accessToken}` },
    cache: "no-store",
  });
  const me = res.ok ? await res.json() : { error: res.status };
  return <pre>{JSON.stringify(me, null, 2)}</pre>;
}
