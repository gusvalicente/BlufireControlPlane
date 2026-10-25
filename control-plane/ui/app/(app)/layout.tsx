import { NavBar, NavRail } from "@/components/Nav";
import { api } from "@/lib/api";

// Every screen shows live data for the signed-in user: never prerender.
export const dynamic = "force-dynamic";

export default async function AppLayout({ children }: { children: React.ReactNode }) {
  let pending = 0;
  try {
    pending = (await api.changes("pending")).length;
  } catch {
    // The badge is optional; the page itself reports API errors.
  }
  return (
    <div className="shell">
      <NavRail pending={pending} />
      <div className="main">{children}</div>
      <NavBar pending={pending} />
    </div>
  );
}
