import { Empty } from "@/components/Empty";
import { FilterChips } from "@/components/FilterChips";
import { Icon } from "@/components/Icon";
import { TopBar } from "@/components/TopBar";
import { api, ENVS, type Deployment, type Env } from "@/lib/api";
import { fmtDate } from "@/lib/format";

export const metadata = { title: "Deployments" };

const RESULT: Record<Deployment["result"], { cls: string; label: string; icon: string; lead: string }> = {
  running: { cls: "info", label: "Running", icon: "progress_activity", lead: "pri" },
  succeeded: { cls: "ok", label: "Succeeded", icon: "check", lead: "ok" },
  failed: { cls: "err", label: "Failed", icon: "error", lead: "err" },
  rolled_back: { cls: "warn", label: "Rolled back", icon: "undo", lead: "warn" },
};

export default async function DeploymentsPage({ searchParams }: { searchParams: Promise<{ app?: string; env?: string }> }) {
  const sp = await searchParams;
  const env = ENVS.includes(sp.env as Env) ? (sp.env as Env) : undefined;
  const [deps, apps] = await Promise.all([api.deployments(sp.app, env), api.apps()]);
  return (
    <div className="page">
      <TopBar title="Deployments" back="/more" />
      <div className="content">
        <FilterChips base="/deployments" apps={apps.map((a) => a.id)} app={sp.app} env={env} />
        {deps.length === 0 ? <Empty icon="rocket_launch" text="No deployments match this filter." /> : (
          <div className="list" style={{ marginTop: 12 }}>
            {deps.map((d) => {
              const r = RESULT[d.result];
              return (
                <div className="li" key={d.id}>
                  <span className={`lead ${r.lead}`}><Icon n={r.icon} /></span>
                  <span className="txt">
                    <span className="h" style={{ display: "block" }}>{d.app} · {d.env} · {d.release ?? "unreleased"}</span>
                    <span className="s mono" style={{ display: "block", fontSize: 12 }}>{d.git_sha.slice(0, 7)} · {d.image_digest.slice(0, 19)}…</span>
                    <span className="s" style={{ display: "block" }}>{fmtDate(d.started_at)}{d.approver ? ` · approved by ${d.approver}` : ""}</span>
                  </span>
                  <span className="trail"><span className={`tag ${r.cls}`}>{r.label}</span></span>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
