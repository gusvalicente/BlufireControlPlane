import Link from "next/link";
import { AppCard } from "@/components/AppCard";
import { Empty } from "@/components/Empty";
import { Icon } from "@/components/Icon";
import { ThemeToggle } from "@/components/ThemeToggle";
import { TopBar } from "@/components/TopBar";
import { api } from "@/lib/api";
import { usd } from "@/lib/format";

export default async function FleetPage({ searchParams }: { searchParams: Promise<{ client?: string; issues?: string }> }) {
  const sp = await searchParams;
  const [fleet, me] = await Promise.all([api.fleet(), api.me()]);
  const clients = [...new Map(fleet.apps.map((a) => [a.client, a.client_name])).entries()];
  const apps = fleet.apps.filter(
    (a) =>
      (!sp.client || a.client === sp.client) &&
      (!sp.issues || a.badges.length > 0 || a.envs.some((e) => e.health === "down" || e.health === "degraded")),
  );
  const allUp = fleet.prod_up === fleet.prod_total;

  return (
    <div className="page">
      <TopBar
        title="BluFire Ops"
        actions={
          <>
            <ThemeToggle />
            <span className="avatar" title={me.name}>{me.name.slice(0, 1)}</span>
          </>
        }
      />
      <div className="content">
        <div className={`hero ${allUp ? "" : "bad"}`}>
          <Icon n={allUp ? "verified_user" : "error"} fill className="" />
          <div>
            <div className="title-m">{fleet.headline}</div>
            <div className="body-m" style={{ opacity: 0.85 }}>{fleet.detail}</div>
          </div>
        </div>

        <div className="grid2 four" style={{ marginTop: 12 }}>
          <Link href="/security?tab=incidents" className={`stat ${fleet.open_p1 ? "alert" : ""}`}>
            <span className="num">{fleet.open_p1}</span>
            <span className="lbl"><Icon n="notifications_active" size="xs" />Open P1s</span>
          </Link>
          <Link href="/changes" className={`stat ${fleet.pending_approvals ? "warn" : ""}`}>
            <span className="num">{fleet.pending_approvals}</span>
            <span className="lbl"><Icon n="approval" size="xs" />Pending approvals</span>
          </Link>
          <Link href="/security?severity=critical" className={`stat ${fleet.critical_findings ? "alert" : ""}`}>
            <span className="num">{fleet.critical_findings}</span>
            <span className="lbl"><Icon n="bug_report" size="xs" />Critical findings</span>
          </Link>
          <Link href="/drift" className="stat">
            <span className="num">{fleet.drift_open}</span>
            <span className="lbl"><Icon n="difference" size="xs" />Drift items</span>
          </Link>
        </div>

        <div className="spread" style={{ margin: "20px 4px 8px" }}>
          <span className="title-s" style={{ color: "var(--primary)" }}>Apps</span>
          <Link href="/costs" className="body-s muted">
            Cost MTD <b style={{ color: "var(--on-surface)", fontWeight: 500 }}>{usd(fleet.cost_mtd_usd)}</b>
          </Link>
        </div>
        <div className="chips">
          <Link href="/" className={`chip ${!sp.client && !sp.issues ? "sel" : ""}`}>
            {!sp.client && !sp.issues && <Icon n="check" />}All clients
          </Link>
          <Link href="/?issues=1" className={`chip ${sp.issues ? "sel" : ""}`}>
            {sp.issues && <Icon n="check" />}Issues only
          </Link>
          {clients.map(([id, name]) => (
            <Link key={id} href={`/?client=${id}`} className={`chip ${sp.client === id ? "sel" : ""}`}>
              {sp.client === id && <Icon n="check" />}{name}
            </Link>
          ))}
        </div>

        <div className="app-grid" style={{ marginTop: 8 }}>
          {apps.map((a) => <AppCard key={a.id} app={a} />)}
        </div>
        {apps.length === 0 && <Empty icon="apps" text="No apps match this filter." />}
      </div>
    </div>
  );
}
