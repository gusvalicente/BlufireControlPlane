import { redirect } from "next/navigation";
import { PROVIDER_ID, signIn } from "@/auth";
import { Icon } from "@/components/Icon";
import { isMock } from "@/lib/mode";

export const dynamic = "force-dynamic";
export const metadata = { title: "Sign in" };

export default async function SignInPage({ searchParams }: { searchParams: Promise<{ callbackUrl?: string; error?: string }> }) {
  const sp = await searchParams;
  const target = sp.callbackUrl?.startsWith("/") && !sp.callbackUrl.startsWith("//") ? sp.callbackUrl : "/";
  if (isMock()) redirect(target);

  return (
    <main className="signin">
      <div className="card tonal">
        <div className="lead pri" style={{ margin: "0 auto 16px", width: 56, height: 56, borderRadius: 16 }}><Icon n="local_fire_department" fill /></div>
        <h1 className="headline-s" style={{ fontWeight: 400 }}>BluFire Ops</h1>
        <p className="body-m muted" style={{ margin: "8px 0 24px" }}>Sign in with your BluFire Microsoft account.</p>
        {sp.error && <div className="banner err" style={{ marginBottom: 16, textAlign: "left" }}><Icon n="error" /><div>Sign-in failed. Try again, or check that your account has the Admin role.</div></div>}
        <form
          action={async () => {
            "use server";
            await signIn(PROVIDER_ID, { redirectTo: target });
          }}
        >
          <button className="btn filled" type="submit" style={{ width: "100%" }}><Icon n="login" />Sign in with Microsoft</button>
        </form>
      </div>
    </main>
  );
}
