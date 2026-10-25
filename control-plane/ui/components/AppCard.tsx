import Link from "next/link";
import type { AppSummary, BadgeKind } from "@/lib/types";
import { ENV_LABEL, healthDot } from "@/lib/format";
import { Icon } from "./Icon";

const BADGE: Record<BadgeKind, { cls: string; icon: string; label: (n: number) => string }> = {
  critical_finding: { cls: "err", icon: "bug_report", label: (n) => `${n} critical` },
  approval: { cls: "info", icon: "approval", label: (n) => (n > 1 ? `${n} approvals` : "Approval") },
  drift: { cls: "neutral", icon: "difference", label: () => "Drift" },
  client_data_in_sandbox: { cls: "warn", icon: "warning", label: () => "Client data in sandbox" },
};

export function AppCard({ app }: { app: AppSummary }) {
  const prod = app.envs.find((e) => e.env === "prod");
  const meta = [app.client_name, prod?.release, prod?.p95_ms != null ? `p95 ${prod.p95_ms} ms` : null].filter(Boolean).join(" · ");
  return (
    <Link href={`/apps/${app.id}`} className="app-card">
      <div className="top">
        <div style={{ flex: 1, minWidth: 0 }}>
          <div className="name">{app.name}</div>
          <div className="client">{meta}</div>
        </div>
        {app.stage === "incubating" && <span className="tag neutral"><Icon n="science" />Sandbox</span>}
      </div>
      {app.badges.length > 0 && (
        <div className="tags" style={{ marginTop: 8 }}>
          {app.badges.map((b) => {
            const d = BADGE[b.kind];
            return (
              <span key={b.kind} className={`tag ${d.cls}`}>
                <Icon n={d.icon} />
                {d.label(b.count)}
              </span>
            );
          })}
        </div>
      )}
      <div className="envs">
        {app.envs.map((e) => (
          <div className="env" key={e.env}>
            <span className="e"><i className={healthDot(e.health)} />{ENV_LABEL[e.env]}</span>
            <span className="v">{e.summary}</span>
          </div>
        ))}
      </div>
    </Link>
  );
}
