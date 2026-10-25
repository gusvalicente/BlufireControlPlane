import Link from "next/link";
import { Icon } from "@/components/Icon";
import { ThemeToggle } from "@/components/ThemeToggle";
import { TopBar } from "@/components/TopBar";
import { api } from "@/lib/api";
import { isMock } from "@/lib/mode";
import { SignOut } from "./SignOut";

export const metadata = { title: "More" };

const LINKS = [
  { href: "/deployments", icon: "rocket_launch", label: "Deployments", sub: "Pipeline runs and approvals" },
  { href: "/backups", icon: "backup", label: "Backups and restores", sub: "Four layers and restore tests" },
  { href: "/drift", icon: "difference", label: "Drift", sub: "Live Azure vs git" },
  { href: "/secrets", icon: "key", label: "Secrets", sub: "Metadata and rotation" },
  { href: "/digest", icon: "summarize", label: "Daily digest", sub: "P1, P2 and P3 summary" },
  { href: "/audit", icon: "receipt_long", label: "Audit log", sub: "Every UI, Claude and CI action" },
  { href: "/costs", icon: "payments", label: "Costs", sub: "Monthly spend by client" },
  { href: "/clients", icon: "domain", label: "Clients", sub: "Tenants, subscriptions, contacts" },
];

export default async function MorePage() {
  const me = await api.me();
  return (
    <div className="page">
      <TopBar title="More" />
      <div className="content">
        <div className="list">
          {LINKS.map((l) => (
            <Link key={l.href} href={l.href} className="li">
              <span className="lead"><Icon n={l.icon} /></span>
              <span className="txt"><span className="h" style={{ display: "block" }}>{l.label}</span><span className="s" style={{ display: "block" }}>{l.sub}</span></span>
              <Icon n="chevron_right" className="muted" />
            </Link>
          ))}
        </div>
        <div className="section-label">Account</div>
        <div className="list">
          <div className="li">
            <span className="avatar" style={{ margin: "0 4px" }}>{me.name.slice(0, 1)}</span>
            <span className="txt"><span className="h" style={{ display: "block" }}>{me.name}</span><span className="s" style={{ display: "block" }}>{me.roles.join(", ") || "No roles"}{isMock() ? " · mock mode" : ""}</span></span>
          </div>
          <ThemeToggle withLabel />
          {!isMock() && <SignOut />}
        </div>
      </div>
    </div>
  );
}
