import { signOut } from "@/auth";
import { Icon } from "@/components/Icon";

export function SignOut() {
  return (
    <form
      action={async () => {
        "use server";
        await signOut({ redirectTo: "/signin" });
      }}
    >
      <button className="li" type="submit">
        <span className="lead"><Icon n="logout" /></span>
        <span className="txt"><span className="h">Sign out</span></span>
      </button>
    </form>
  );
}
